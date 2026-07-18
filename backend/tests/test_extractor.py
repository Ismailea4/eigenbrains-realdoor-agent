from __future__ import annotations

import hashlib
import json
import shutil
import sys
import unittest
from pathlib import Path

import fitz


REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "backend"))

from app.schemas.profile import FieldName  # noqa: E402
from app.services.extractor import (  # noqa: E402
    NonSyntheticDocumentError,
    OCRUnavailableError,
    UnsupportedDocumentError,
    _financial_consistency_warnings,
    _source_lines_from_ocr_data,
    extract_document,
)


ORGANIZER_ROOT = (
    REPO_ROOT
    / "data"
    / "realdoor-hackathon-starter-pack"
    / "synthetic_documents"
)
EXTENDED_ROOT = REPO_ROOT / "data" / "synthetic_docs" / "saad_extended"
TESSERACT_AVAILABLE = bool(
    shutil.which("tesseract")
    or Path(r"C:\Program Files\Tesseract-OCR\tesseract.exe").exists()
)


def load_jsonl(path: Path) -> list[dict]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def center(box: list[float] | tuple[float, ...]) -> tuple[float, float]:
    return ((box[0] + box[2]) / 2, (box[1] + box[3]) / 2)


class ExtractorTests(unittest.TestCase):
    def test_project_runtime_is_python_311(self) -> None:
        self.assertEqual(sys.version_info[:2], (3, 11))

    def test_all_vector_organizer_fields_match_gold(self) -> None:
        rows = load_jsonl(ORGANIZER_ROOT / "gold" / "document_gold.jsonl")
        tested = 0
        for row in rows:
            if row["rasterized"]:
                continue
            result = extract_document(
                ORGANIZER_ROOT / "documents" / row["file_name"],
                enable_ocr=False,
            )
            actual = {item.field.value: item for item in result.fields}
            expected = {
                item["field"]: item
                for item in row["fields"]
                if item["field"] != "untrusted_instruction_text"
            }
            self.assertEqual(
                {key: item.value for key, item in actual.items()},
                {key: item["value"] for key, item in expected.items()},
                row["document_id"],
            )
            for key, expected_field in expected.items():
                x, y = center(actual[key].evidence.bbox)
                x1, y1, x2, y2 = expected_field["bbox"]
                self.assertTrue(x1 <= x <= x2 and y1 <= y <= y2, (row["document_id"], key))
            tested += 1
        self.assertEqual(tested, 16)

    def test_injection_is_flagged_and_never_reusable(self) -> None:
        result = extract_document(
            ORGANIZER_ROOT / "documents" / "hh-004_d04_gig_statement.pdf",
            enable_ocr=False,
        )
        self.assertEqual(len(result.security_flags), 1)
        self.assertNotIn(
            "untrusted_instruction_text",
            {item.field.value for item in result.fields},
        )
        self.assertTrue(all(not item.reusable for item in result.fields))

    @unittest.skipUnless(TESSERACT_AVAILABLE, "Tesseract runtime is not installed")
    def test_all_raster_organizer_fields_match_gold(self) -> None:
        rows = load_jsonl(ORGANIZER_ROOT / "gold" / "document_gold.jsonl")
        raster_rows = [row for row in rows if row["rasterized"]]
        self.assertEqual(len(raster_rows), 8)
        for row in raster_rows:
            result = extract_document(ORGANIZER_ROOT / "documents" / row["file_name"])
            actual = {item.field.value: item for item in result.fields}
            expected = {
                item["field"]: item
                for item in row["fields"]
                if item["field"] != "untrusted_instruction_text"
            }
            self.assertEqual(
                {key: item.value for key, item in actual.items()},
                {key: item["value"] for key, item in expected.items()},
                row["document_id"],
            )
            for key, expected_field in expected.items():
                x, y = center(actual[key].evidence.bbox)
                x1, y1, x2, y2 = expected_field["bbox"]
                self.assertTrue(
                    x1 <= x <= x2 and y1 <= y <= y2,
                    (row["document_id"], key),
                )

    def test_raster_document_abstains_when_ocr_is_disabled(self) -> None:
        with self.assertRaises(OCRUnavailableError):
            extract_document(
                ORGANIZER_ROOT / "documents" / "hh-001_d02_pay_stub.pdf",
                enable_ocr=False,
            )

    def test_ocr_rows_are_split_into_visual_columns(self) -> None:
        data = {
            "text": ["EMPLOYEE", "PAY", "DATE", "Nadia", "Quill", "2026-07-11"],
            "conf": ["95"] * 6,
            "block_num": [1] * 6,
            "par_num": [1] * 6,
            "line_num": [1, 1, 1, 2, 2, 2],
            "left": [40, 330, 365, 40, 88, 330],
            "top": [100, 100, 100, 125, 125, 125],
            "width": [75, 28, 38, 42, 38, 90],
            "height": [12] * 6,
        }
        lines = _source_lines_from_ocr_data(
            data,
            page_number=1,
            image_size=(612, 792),
            page_size=(612.0, 792.0),
        )
        self.assertEqual(
            [line.text for line in lines],
            ["EMPLOYEE", "PAY DATE", "Nadia Quill", "2026-07-11"],
        )

    def test_rejects_non_pdf_bytes(self) -> None:
        with self.assertRaises(UnsupportedDocumentError):
            extract_document(b"not a pdf")

    def test_rejects_document_without_synthetic_notice(self) -> None:
        document = fitz.open()
        page = document.new_page(width=612, height=792)
        for index, text in enumerate(
            ("Pay Stub", "EMPLOYEE", "Example Name", "PAY DATE", "2026-07-01")
        ):
            page.insert_text((40, 80 + index * 24), text)
        payload = document.tobytes()
        document.close()
        with self.assertRaises(NonSyntheticDocumentError):
            extract_document(payload, enable_ocr=False)

    def test_extended_vector_fixtures_match_gold(self) -> None:
        rows = load_jsonl(EXTENDED_ROOT / "gold" / "document_gold.jsonl")
        vector_rows = [row for row in rows if not row["rasterized"]]
        self.assertEqual(len(rows), 8)
        self.assertEqual(len(vector_rows), 7)
        for row in vector_rows:
            result = extract_document(
                EXTENDED_ROOT / "documents" / row["file_name"],
                enable_ocr=False,
            )
            actual = {item.field.value: item for item in result.fields}
            expected = {item["field"]: item for item in row["fields"]}
            self.assertEqual(
                {key: item.value for key, item in actual.items()},
                {key: item["value"] for key, item in expected.items()},
                row["document_id"],
            )
            for key, expected_field in expected.items():
                x, y = center(actual[key].evidence.bbox)
                x1, y1, x2, y2 = expected_field["bbox"]
                self.assertTrue(
                    x1 <= x <= x2 and y1 <= y <= y2,
                    (row["document_id"], key),
                )
            self.assertIsNotNone(result.structured_data, row["document_id"])

    def test_detailed_statements_return_nested_structured_data(self) -> None:
        bank = extract_document(
            EXTENDED_ROOT
            / "documents"
            / "saad-106_d01_bank_deposit_statement.pdf",
            enable_ocr=False,
        )
        payload = bank.model_dump(mode="json")
        self.assertEqual(bank.page_count, 2)
        self.assertEqual(payload["document_type"], "bank_deposit_statement")
        self.assertEqual(
            payload["structured_data"]["total_deposits"]["value"],
            4915.75,
        )
        self.assertEqual(
            payload["structured_data"]["total_deposits"]["evidence"]["page"],
            1,
        )
        self.assertFalse(payload["structured_data"]["total_deposits"]["confirmed"])
        self.assertFalse(payload["structured_data"]["total_deposits"]["reusable"])
        self.assertNotIn("transactions", payload["structured_data"])

        rent = extract_document(
            EXTENDED_ROOT
            / "documents"
            / "saad-105_d01_property_rent_statement.pdf",
            enable_ocr=False,
        )
        self.assertEqual(rent.structured_data.monthly_rent.value, 1850)
        self.assertEqual(rent.structured_data.current_balance.value, 0)

    def test_self_employment_math_mismatch_requires_warning(self) -> None:
        result = extract_document(
            EXTENDED_ROOT
            / "documents"
            / "saad-106_d02_self_employment_statement.pdf",
            enable_ocr=False,
        )
        self.assertEqual(result.warnings, [])
        changed = [
            item.model_copy(update={"value": 4900})
            if item.field is FieldName.NET_BUSINESS_INCOME
            else item
            for item in result.fields
        ]
        self.assertEqual(
            _financial_consistency_warnings(result.document_type, changed),
            [
                "Printed net business income does not equal gross receipts minus "
                "business expenses"
            ],
        )

    @unittest.skipUnless(TESSERACT_AVAILABLE, "Tesseract runtime is not installed")
    def test_extended_raster_fixture_is_exact_and_flags_injection(self) -> None:
        row = next(
            row
            for row in load_jsonl(EXTENDED_ROOT / "gold" / "document_gold.jsonl")
            if row["rasterized"]
        )
        result = extract_document(EXTENDED_ROOT / "documents" / row["file_name"])
        actual = {item.field.value: item.value for item in result.fields}
        expected = {
            item["field"]: item["value"]
            for item in row["fields"]
            if item["field"] != "untrusted_instruction_text"
        }
        self.assertEqual(actual, expected)
        self.assertEqual(len(result.security_flags), 1)

    def test_extended_fixture_checksums(self) -> None:
        for line in (EXTENDED_ROOT / "checksums.sha256").read_text().splitlines():
            expected, relative = line.split("  ", 1)
            actual = hashlib.sha256((EXTENDED_ROOT / relative).read_bytes()).hexdigest()
            self.assertEqual(actual, expected, relative)

    def test_extended_fixtures_record_layout_references(self) -> None:
        rows = load_jsonl(EXTENDED_ROOT / "gold" / "document_gold.jsonl")
        self.assertEqual(len(rows), 8)
        for row in rows:
            self.assertTrue(row["design_reference"], row["document_id"])


if __name__ == "__main__":
    unittest.main()
