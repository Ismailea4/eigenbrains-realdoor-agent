"""Grounded parser for the RealDoor synthetic document fixtures.

The parser is deliberately deterministic. It extracts text and geometry from
the PDF itself, associates known labels with nearby values, and returns only
allowlisted fields. Raster pages use an optional Tesseract adapter. Document
text is never interpreted as an instruction and no model or tool call occurs.

All public functions process bytes in memory. They do not persist uploads or
log raw document text.
"""

from __future__ import annotations

import os
import re
import shutil
from collections import defaultdict
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Callable, Iterable, Sequence

import fitz

from app.schemas.profile import (
    ApplicationSummaryData,
    BankDepositStatementData,
    BenefitLetterData,
    DocumentExtraction,
    DocumentType,
    EvidenceRef,
    EmploymentLetterData,
    ExtractedField,
    ExtractionEngine,
    ExtractionStatus,
    FieldName,
    GigStatementData,
    PayStubData,
    RentStatementData,
    SecurityFlag,
    SelfEmploymentStatementData,
    StructuredDocumentData,
)


MAX_DOCUMENT_BYTES = 10 * 1024 * 1024
MAX_PAGES = 5
BOX_UNITS = "pdf_points_bottom_left_origin"


class DocumentExtractionError(ValueError):
    """Base class for safe, user-displayable extraction failures."""


class UnsupportedDocumentError(DocumentExtractionError):
    pass


class NonSyntheticDocumentError(DocumentExtractionError):
    pass


class OCRUnavailableError(DocumentExtractionError):
    pass


@dataclass(frozen=True)
class SourceLine:
    page: int
    text: str
    # PyMuPDF coordinates: x0, top, x1, bottom.
    bbox_top_left: tuple[float, float, float, float]
    page_size: tuple[float, float]
    engine: ExtractionEngine
    confidence: float

    @property
    def normalized(self) -> str:
        return _normalize_label(self.text)

    def evidence(self) -> EvidenceRef:
        x1, top, x2, bottom = self.bbox_top_left
        page_width, page_height = self.page_size
        return EvidenceRef(
            page=self.page,
            bbox=(
                round(max(0.0, x1), 2),
                round(max(0.0, page_height - bottom), 2),
                round(min(page_width, x2), 2),
                round(min(page_height, page_height - top), 2),
            ),
            bbox_units=BOX_UNITS,
            text=self.text.strip(),
            engine=self.engine,
            confidence=round(max(0.0, min(1.0, self.confidence)), 4),
        )


@dataclass(frozen=True)
class FieldSpec:
    labels: tuple[str, ...]
    parser: Callable[[str], str | int | float]


def _normalize_label(value: str) -> str:
    return re.sub(r"\s+", " ", value.strip()).upper()


def _clean_text(value: str) -> str:
    return re.sub(r"\s+", " ", value.strip())


def _parse_text(value: str) -> str:
    cleaned = _clean_text(value)
    if not cleaned:
        raise ValueError("empty text")
    return cleaned


def _parse_date(value: str) -> str:
    match = re.search(r"\b\d{4}-\d{2}-\d{2}\b", value)
    if not match:
        raise ValueError("expected ISO date")
    return date.fromisoformat(match.group(0)).isoformat()


def _parse_month(value: str) -> str:
    match = re.search(r"\b(\d{4})-(\d{2})\b", value)
    if not match or not 1 <= int(match.group(2)) <= 12:
        raise ValueError("expected YYYY-MM month")
    return match.group(0)


def _parse_decimal(value: str) -> float | int:
    cleaned = re.sub(r"[^0-9.\-]", "", value)
    if not cleaned:
        raise ValueError("expected a number")
    try:
        amount = Decimal(cleaned)
    except InvalidOperation as exc:
        raise ValueError("invalid number") from exc
    if amount < 0:
        raise ValueError("negative values are not accepted")
    if amount == amount.to_integral_value():
        return int(amount)
    return float(amount.quantize(Decimal("0.01")))


def _parse_household_size(value: str) -> int:
    parsed = _parse_decimal(value)
    if not isinstance(parsed, int) or not 1 <= parsed <= 20:
        raise ValueError("household size must be an integer from 1 to 20")
    return parsed


def _parse_frequency(value: str) -> str:
    normalized = re.sub(r"[^a-z]", "", value.lower())
    allowed = {"weekly", "biweekly", "semimonthly", "monthly", "annual"}
    if normalized not in allowed:
        raise ValueError("unsupported payment frequency")
    return normalized


COMMON_FIELDS: dict[FieldName, FieldSpec] = {
    FieldName.PERSON_NAME: FieldSpec(
        (
            "EMPLOYEE",
            "RECIPIENT",
            "WORKER",
            "APPLICANT",
            "TENANT",
            "ACCOUNT HOLDER",
            "OWNER",
        ),
        _parse_text,
    )
}

TYPE_FIELDS: dict[DocumentType, dict[FieldName, FieldSpec]] = {
    DocumentType.APPLICATION_SUMMARY: {
        FieldName.HOUSEHOLD_SIZE: FieldSpec(("HOUSEHOLD SIZE",), _parse_household_size),
        FieldName.ADDRESS: FieldSpec(("MAILING ADDRESS", "ADDRESS"), _parse_text),
        FieldName.APPLICATION_DATE: FieldSpec(("APPLICATION DATE",), _parse_date),
    },
    DocumentType.PAY_STUB: {
        FieldName.PAY_DATE: FieldSpec(("PAY DATE",), _parse_date),
        FieldName.PAY_PERIOD_START: FieldSpec(("PAY PERIOD",), _parse_date),
        FieldName.PAY_PERIOD_END: FieldSpec(("THROUGH",), _parse_date),
        FieldName.PAY_FREQUENCY: FieldSpec(("PAY FREQUENCY",), _parse_frequency),
        FieldName.REGULAR_HOURS: FieldSpec(("REGULAR HOURS",), _parse_decimal),
        FieldName.HOURLY_RATE: FieldSpec(("HOURLY RATE",), _parse_decimal),
        FieldName.GROSS_PAY: FieldSpec(("GROSS PAY",), _parse_decimal),
        FieldName.NET_PAY: FieldSpec(("NET PAY",), _parse_decimal),
    },
    DocumentType.EMPLOYMENT_LETTER: {
        FieldName.DOCUMENT_DATE: FieldSpec(("DOCUMENT DATE", "LETTER DATE"), _parse_date),
        FieldName.WEEKLY_HOURS: FieldSpec(
            ("HOURS PER WEEK", "WEEKLY HOURS"), _parse_decimal
        ),
        FieldName.HOURLY_RATE: FieldSpec(("HOURLY RATE",), _parse_decimal),
    },
    DocumentType.BENEFIT_LETTER: {
        FieldName.DOCUMENT_DATE: FieldSpec(("DOCUMENT DATE", "LETTER DATE"), _parse_date),
        FieldName.MONTHLY_BENEFIT: FieldSpec(("MONTHLY AMOUNT",), _parse_decimal),
        FieldName.BENEFIT_FREQUENCY: FieldSpec(("FREQUENCY",), _parse_frequency),
    },
    DocumentType.GIG_STATEMENT: {
        FieldName.STATEMENT_MONTH: FieldSpec(("STATEMENT MONTH",), _parse_month),
        FieldName.GROSS_RECEIPTS: FieldSpec(("GROSS RECEIPTS",), _parse_decimal),
        FieldName.PLATFORM_FEES: FieldSpec(("PLATFORM FEES",), _parse_decimal),
    },
    DocumentType.RENT_STATEMENT: {
        FieldName.PROPERTY_NAME: FieldSpec(("PROPERTY NAME",), _parse_text),
        FieldName.ADDRESS: FieldSpec(("PROPERTY ADDRESS",), _parse_text),
        FieldName.UNIT_NUMBER: FieldSpec(("UNIT NUMBER",), _parse_text),
        FieldName.STATEMENT_DATE: FieldSpec(("STATEMENT DATE",), _parse_date),
        FieldName.LEASE_START_DATE: FieldSpec(("LEASE START",), _parse_date),
        FieldName.LEASE_END_DATE: FieldSpec(("LEASE END",), _parse_date),
        FieldName.MONTHLY_RENT: FieldSpec(("MONTHLY RENT",), _parse_decimal),
        FieldName.CURRENT_BALANCE: FieldSpec(("CURRENT BALANCE",), _parse_decimal),
    },
    DocumentType.BANK_DEPOSIT_STATEMENT: {
        FieldName.STATEMENT_PERIOD_START: FieldSpec(
            ("STATEMENT PERIOD START",), _parse_date
        ),
        FieldName.STATEMENT_PERIOD_END: FieldSpec(
            ("STATEMENT PERIOD END",), _parse_date
        ),
        FieldName.TOTAL_DEPOSITS: FieldSpec(("TOTAL DEPOSITS",), _parse_decimal),
    },
    DocumentType.SELF_EMPLOYMENT_STATEMENT: {
        FieldName.BUSINESS_NAME: FieldSpec(("BUSINESS NAME",), _parse_text),
        FieldName.STATEMENT_MONTH: FieldSpec(("STATEMENT MONTH",), _parse_month),
        FieldName.GROSS_RECEIPTS: FieldSpec(("GROSS RECEIPTS",), _parse_decimal),
        FieldName.BUSINESS_EXPENSES: FieldSpec(
            ("BUSINESS EXPENSES",), _parse_decimal
        ),
        FieldName.NET_BUSINESS_INCOME: FieldSpec(
            ("NET BUSINESS INCOME",), _parse_decimal
        ),
    },
}

REQUIRED_FIELDS: dict[DocumentType, frozenset[FieldName]] = {
    kind: frozenset({FieldName.PERSON_NAME, *specs.keys()})
    for kind, specs in TYPE_FIELDS.items()
}

DOCUMENT_MARKERS: tuple[tuple[DocumentType, tuple[str, ...]], ...] = (
    (DocumentType.APPLICATION_SUMMARY, ("APPLICATION SUMMARY",)),
    (DocumentType.PAY_STUB, ("PAY STUB",)),
    (DocumentType.EMPLOYMENT_LETTER, ("EMPLOYMENT LETTER",)),
    (DocumentType.BENEFIT_LETTER, ("BENEFIT LETTER",)),
    (DocumentType.GIG_STATEMENT, ("GIG STATEMENT",)),
    (DocumentType.RENT_STATEMENT, ("PROPERTY RENT STATEMENT",)),
    (DocumentType.BANK_DEPOSIT_STATEMENT, ("BANK DEPOSIT STATEMENT",)),
    (
        DocumentType.SELF_EMPLOYMENT_STATEMENT,
        ("SELF-EMPLOYMENT INCOME STATEMENT",),
    ),
)

INJECTION_PATTERNS = (
    re.compile(r"\bignore\b.{0,50}\b(instructions?|system|rules?)\b", re.I),
    re.compile(r"\b(reveal|print|return)\b.{0,40}\bsystem prompt\b", re.I),
    re.compile(r"\b(mark|declare|label)\b.{0,30}\b(approved|eligible|denied)\b", re.I),
    re.compile(r"\b(call|invoke|use)\b.{0,25}\b(tool|function|api)\b", re.I),
)


def _read_source(source: bytes | bytearray | str | Path) -> bytes:
    if isinstance(source, (str, Path)):
        data = Path(source).read_bytes()
    else:
        data = bytes(source)
    if not data.startswith(b"%PDF-"):
        raise UnsupportedDocumentError("Only PDF documents are supported")
    if len(data) > MAX_DOCUMENT_BYTES:
        raise UnsupportedDocumentError(
            f"Document exceeds the {MAX_DOCUMENT_BYTES // (1024 * 1024)} MB limit"
        )
    return data


def _vector_lines(page: fitz.Page, page_number: int) -> list[SourceLine]:
    """Return horizontal lines only, excluding diagonal synthetic watermarks."""

    page_size = (float(page.rect.width), float(page.rect.height))
    result: list[SourceLine] = []
    content = page.get_text("dict", sort=True)
    for block in content.get("blocks", []):
        if block.get("type") != 0:
            continue
        for line in block.get("lines", []):
            direction = line.get("dir", (1.0, 0.0))
            if abs(direction[0] - 1.0) > 0.03 or abs(direction[1]) > 0.03:
                continue
            spans = [span for span in line.get("spans", []) if span.get("text", "").strip()]
            if not spans:
                continue
            text = _clean_text(" ".join(span["text"] for span in spans))
            x1 = min(float(span["bbox"][0]) for span in spans)
            top = min(float(span["bbox"][1]) for span in spans)
            x2 = max(float(span["bbox"][2]) for span in spans)
            bottom = max(float(span["bbox"][3]) for span in spans)
            if x2 <= 0 or bottom <= 0 or x1 >= page_size[0] or top >= page_size[1]:
                continue
            result.append(
                SourceLine(
                    page=page_number,
                    text=text,
                    bbox_top_left=(
                        max(0.0, x1),
                        max(0.0, top),
                        min(page_size[0], x2),
                        min(page_size[1], bottom),
                    ),
                    page_size=page_size,
                    engine=ExtractionEngine.PDF_TEXT,
                    confidence=0.99,
                )
            )
    return result


def _ocr_lines(page: fitz.Page, page_number: int) -> list[SourceLine]:
    """OCR one page in memory and map pixel coordinates back to PDF points."""

    try:
        import pytesseract
        from PIL import Image
        from pytesseract import Output
    except ImportError as exc:
        raise OCRUnavailableError(
            "Raster PDF detected, but pytesseract and Pillow are not installed"
        ) from exc

    configured = os.getenv("TESSERACT_CMD") or getattr(
        pytesseract.pytesseract, "tesseract_cmd", "tesseract"
    )
    if configured == "tesseract" and shutil.which("tesseract") is None:
        windows_default = Path(r"C:\Program Files\Tesseract-OCR\tesseract.exe")
        if windows_default.exists():
            configured = str(windows_default)
        else:
            raise OCRUnavailableError(
                "Raster PDF detected, but the Tesseract executable is unavailable"
            )
    pytesseract.pytesseract.tesseract_cmd = configured

    scale = 300 / 72
    pixmap = page.get_pixmap(matrix=fitz.Matrix(scale, scale), alpha=False)
    image = Image.frombytes("RGB", (pixmap.width, pixmap.height), pixmap.samples)
    data = pytesseract.image_to_data(image, output_type=Output.DICT, config="--psm 6")
    return _source_lines_from_ocr_data(
        data,
        page_number=page_number,
        image_size=(pixmap.width, pixmap.height),
        page_size=(float(page.rect.width), float(page.rect.height)),
    )


def _source_lines_from_ocr_data(
    data: dict[str, list],
    *,
    page_number: int,
    image_size: tuple[int, int],
    page_size: tuple[float, float],
) -> list[SourceLine]:
    """Turn Tesseract word data into column-aware source lines.

    Tesseract often assigns several visual columns to one OCR line. Splitting
    at horizontal gaps larger than 24 PDF points keeps labels and values in
    separate cells, which is essential for grounded label/value matching.
    """

    grouped: dict[tuple[int, int, int], list[int]] = defaultdict(list)
    for index, raw_text in enumerate(data["text"]):
        if raw_text.strip() and float(data["conf"][index]) >= 0:
            key = (
                int(data["block_num"][index]),
                int(data["par_num"][index]),
                int(data["line_num"][index]),
            )
            grouped[key].append(index)

    x_scale = page_size[0] / image_size[0]
    y_scale = page_size[1] / image_size[1]
    result: list[SourceLine] = []
    for indexes in grouped.values():
        ordered = sorted(indexes, key=lambda index: int(data["left"][index]))
        segments: list[list[int]] = []
        current: list[int] = []
        current_right = 0
        for index in ordered:
            left = int(data["left"][index])
            if current and (left - current_right) * x_scale > 24:
                segments.append(current)
                current = []
            current.append(index)
            current_right = max(
                current_right,
                left + int(data["width"][index]),
            )
        if current:
            segments.append(current)

        for segment in segments:
            text = _clean_text(" ".join(data["text"][index] for index in segment))
            left = min(int(data["left"][index]) for index in segment)
            top = min(int(data["top"][index]) for index in segment)
            right = max(
                int(data["left"][index]) + int(data["width"][index])
                for index in segment
            )
            bottom = max(
                int(data["top"][index]) + int(data["height"][index])
                for index in segment
            )
            confidence = sum(float(data["conf"][index]) for index in segment) / (
                len(segment) * 100
            )
            result.append(
                SourceLine(
                    page=page_number,
                    text=text,
                    bbox_top_left=(
                        left * x_scale,
                        top * y_scale,
                        right * x_scale,
                        bottom * y_scale,
                    ),
                    page_size=page_size,
                    engine=ExtractionEngine.OCR,
                    confidence=confidence,
                )
            )
    return sorted(result, key=lambda line: (line.bbox_top_left[1], line.bbox_top_left[0]))


def _has_meaningful_vector_text(lines: Sequence[SourceLine]) -> bool:
    useful = [
        line
        for line in lines
        if len(re.sub(r"\W", "", line.text)) >= 2
        and line.bbox_top_left[2] - line.bbox_top_left[0] > 2
    ]
    return len(useful) >= 5


def _detect_document_type(lines: Iterable[SourceLine]) -> DocumentType:
    normalized = {line.normalized for line in lines}
    for document_type, markers in DOCUMENT_MARKERS:
        if any(marker in normalized for marker in markers):
            return document_type
    return DocumentType.UNKNOWN


def _detect_document_id(lines: Iterable[SourceLine]) -> str:
    pattern = re.compile(r"\b[A-Z][A-Z0-9]{1,9}-\d{3}-D\d{2}\b", re.I)
    for line in lines:
        match = pattern.search(line.text)
        if match:
            return match.group(0).upper()
    return "UNKNOWN-DOCUMENT"


def _is_synthetic(lines: Iterable[SourceLine]) -> bool:
    text = " ".join(line.normalized for line in lines)
    explicit_notice = "SYNTHETIC" in text and any(
        marker in text for marker in ("NOT A REAL DOCUMENT", "FICTIONAL")
    )
    training_notice = "TRAINING FIXTURE" in text and any(
        marker in text for marker in ("FICTIONAL", "NO REAL PERSON")
    )
    return explicit_notice or training_notice


def _nearest_value(
    label_line: SourceLine,
    lines: Sequence[SourceLine],
    all_labels: frozenset[str],
) -> SourceLine | None:
    label_x, _, _, label_bottom = label_line.bbox_top_left
    candidates: list[tuple[float, float, SourceLine]] = []
    for line in lines:
        if line.page != label_line.page or line is label_line:
            continue
        x1, top, _, _ = line.bbox_top_left
        vertical_gap = top - label_bottom
        # Larger value fonts can overlap the label line's font bbox slightly.
        if not -6 <= vertical_gap <= 42:
            continue
        if abs(x1 - label_x) > 24:
            continue
        if line.normalized in all_labels:
            continue
        if line.normalized.startswith(("SYNTHETIC", "TRAINING FIXTURE", "FIXTURE ")):
            continue
        candidates.append((abs(vertical_gap), abs(x1 - label_x), line))
    if not candidates:
        return None
    return min(candidates, key=lambda item: (item[0], item[1]))[2]


def _security_flags(lines: Sequence[SourceLine]) -> list[SecurityFlag]:
    flags: list[SecurityFlag] = []
    for line in lines:
        if any(pattern.search(line.text) for pattern in INJECTION_PATTERNS):
            flags.append(
                SecurityFlag(
                    message=(
                        "Embedded instruction detected and ignored; document text "
                        "cannot change system behavior."
                    ),
                    evidence=line.evidence(),
                )
            )
    return flags


def _extract_fields(
    document_type: DocumentType,
    lines: Sequence[SourceLine],
) -> tuple[list[ExtractedField], list[str]]:
    specs = {**COMMON_FIELDS, **TYPE_FIELDS.get(document_type, {})}
    all_labels = frozenset(
        _normalize_label(label)
        for field_spec in specs.values()
        for label in field_spec.labels
    )
    by_label: dict[str, list[SourceLine]] = defaultdict(list)
    for line in lines:
        by_label[line.normalized].append(line)

    fields: list[ExtractedField] = []
    warnings: list[str] = []
    for field_name, spec in specs.items():
        label_line = next(
            (
                matches[0]
                for label in spec.labels
                if (matches := by_label.get(_normalize_label(label)))
            ),
            None,
        )
        if label_line is None:
            warnings.append(f"Missing label for {field_name.value}")
            continue
        value_line = _nearest_value(label_line, lines, all_labels)
        if value_line is None:
            warnings.append(f"Missing value for {field_name.value}")
            continue
        try:
            value = spec.parser(value_line.text)
        except ValueError as exc:
            warnings.append(f"Invalid {field_name.value}: {exc}")
            continue
        confidence = min(label_line.confidence, value_line.confidence)
        fields.append(
            ExtractedField(
                field=field_name,
                value=value,
                confidence=round(confidence, 4),
                evidence=value_line.evidence(),
            )
        )
    return fields, warnings


def _build_structured_data(
    document_type: DocumentType,
    fields: Sequence[ExtractedField],
) -> StructuredDocumentData | None:
    """Group evidence-linked fields into a document-specific typed record."""

    values = {item.field.value: item for item in fields}
    model_by_type = {
        DocumentType.APPLICATION_SUMMARY: ApplicationSummaryData,
        DocumentType.PAY_STUB: PayStubData,
        DocumentType.EMPLOYMENT_LETTER: EmploymentLetterData,
        DocumentType.BENEFIT_LETTER: BenefitLetterData,
        DocumentType.GIG_STATEMENT: GigStatementData,
        DocumentType.RENT_STATEMENT: RentStatementData,
        DocumentType.BANK_DEPOSIT_STATEMENT: BankDepositStatementData,
        DocumentType.SELF_EMPLOYMENT_STATEMENT: SelfEmploymentStatementData,
    }
    model = model_by_type.get(document_type)
    if model is None:
        return None
    accepted = set(model.model_fields) - {"document_type"}
    return model(**{name: item for name, item in values.items() if name in accepted})


def _financial_consistency_warnings(
    document_type: DocumentType,
    fields: Sequence[ExtractedField],
) -> list[str]:
    """Check printed financial totals deterministically without deciding eligibility."""

    if document_type is not DocumentType.SELF_EMPLOYMENT_STATEMENT:
        return []
    required = {
        FieldName.GROSS_RECEIPTS,
        FieldName.BUSINESS_EXPENSES,
        FieldName.NET_BUSINESS_INCOME,
    }
    values = {
        item.field: Decimal(str(item.value))
        for item in fields
        if item.field in required
    }
    if not required.issubset(values):
        return []
    expected = values[FieldName.GROSS_RECEIPTS] - values[FieldName.BUSINESS_EXPENSES]
    if expected != values[FieldName.NET_BUSINESS_INCOME]:
        return [
            "Printed net business income does not equal gross receipts minus "
            "business expenses"
        ]
    return []


def extract_document(
    source: bytes | bytearray | str | Path,
    *,
    enable_ocr: bool = True,
    require_synthetic: bool = True,
) -> DocumentExtraction:
    """Parse one PDF into proposed fields and evidence.

    ``source`` may be bytes or a local path. The bytes are held only for the
    duration of this call. Raster documents require Tesseract when
    ``enable_ocr`` is true; otherwise the function abstains with a typed error.
    """

    data = _read_source(source)
    try:
        document = fitz.open(stream=data, filetype="pdf")
    except Exception as exc:  # PyMuPDF exposes several parser-specific errors.
        raise UnsupportedDocumentError("The PDF could not be opened safely") from exc

    with document:
        if document.needs_pass:
            raise UnsupportedDocumentError("Encrypted PDFs are not supported")
        if not 1 <= document.page_count <= MAX_PAGES:
            raise UnsupportedDocumentError(
                f"PDF page count must be between 1 and {MAX_PAGES}"
            )

        lines: list[SourceLine] = []
        rasterized = False
        for page_index, page in enumerate(document, start=1):
            page_lines = _vector_lines(page, page_index)
            if not _has_meaningful_vector_text(page_lines):
                rasterized = True
                if not enable_ocr:
                    raise OCRUnavailableError(
                        "Raster PDF detected and OCR was explicitly disabled"
                    )
                page_lines = _ocr_lines(page, page_index)
            lines.extend(page_lines)

        if require_synthetic and not _is_synthetic(lines):
            raise NonSyntheticDocumentError(
                "Document lacks the required synthetic-training notice"
            )

        document_type = _detect_document_type(lines)
        fields, warnings = _extract_fields(document_type, lines)
        warnings.extend(_financial_consistency_warnings(document_type, fields))
        flags = _security_flags(lines)
        if document_type is DocumentType.UNKNOWN:
            warnings.append("Unsupported or unknown document type")

        found = {item.field for item in fields}
        missing_required = REQUIRED_FIELDS.get(document_type, frozenset()) - found
        warnings.extend(
            f"Required field not extracted: {field.value}"
            for field in sorted(missing_required, key=lambda item: item.value)
            if f"Missing label for {field.value}" not in warnings
        )
        status = (
            ExtractionStatus.EXTRACTED
            if document_type is not DocumentType.UNKNOWN
            and not missing_required
            and not flags
            and not warnings
            else ExtractionStatus.NEEDS_REVIEW
        )
        first_page = document[0]
        return DocumentExtraction(
            document_id=_detect_document_id(lines),
            document_type=document_type,
            synthetic=True,
            page_count=document.page_count,
            page_size_points=(
                float(first_page.rect.width),
                float(first_page.rect.height),
            ),
            rasterized=rasterized,
            status=status,
            fields=fields,
            structured_data=_build_structured_data(document_type, fields),
            security_flags=flags,
            warnings=warnings,
        )


def extract_documents(
    sources: Iterable[bytes | bytearray | str | Path],
    *,
    enable_ocr: bool = True,
) -> list[DocumentExtraction]:
    """Convenience wrapper that preserves one result per supplied document."""

    return [extract_document(source, enable_ocr=enable_ocr) for source in sources]
