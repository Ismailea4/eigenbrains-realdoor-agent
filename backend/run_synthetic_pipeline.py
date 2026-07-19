"""Run RealDoor's deterministic pipeline over the generated synthetic pack.

The checked-in gold data acts as the explicit renter-confirmation step for this
offline demo only. Extracted fields remain unconfirmed in the parser response;
the separate confirmation record proves which values matched the synthetic
fixture before they are reused by rules or financial-readiness calculations.
"""

from __future__ import annotations

import hashlib
import json
import sys
from collections import Counter, defaultdict
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from typing import Any


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
FIXTURE_ROOT = REPOSITORY_ROOT / "data" / "synthetic_docs" / "saad_extended"
GOLD_PATH = FIXTURE_ROOT / "gold" / "document_gold.jsonl"
DOCUMENTS_ROOT = FIXTURE_ROOT / "documents"
OUTPUT_PATH = (
    REPOSITORY_ROOT
    / "backend"
    / "pipeline_results"
    / "synthetic_pipeline_output.json"
)

if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from backend.app.schemas.calculator import (  # noqa: E402
    ConfirmedIncomeInput,
    EvidenceReference,
    RulesEvaluationRequest,
)
from backend.app.schemas.profile import DocumentExtraction, FieldName  # noqa: E402
from backend.app.services.extractor import extract_document  # noqa: E402
from backend.app.services.rules_engine import (  # noqa: E402
    EXPECTED_AMI_PERCENTAGE,
    EXPECTED_AREA,
    EXPECTED_PROGRAM_ID,
    EXPECTED_RULE_YEAR,
    RulesEngine,
)


MONEY = Decimal("0.01")
PERIODS_PER_YEAR = {
    "weekly": Decimal("52"),
    "biweekly": Decimal("26"),
    "semimonthly": Decimal("24"),
    "monthly": Decimal("12"),
    "annual": Decimal("1"),
}


def _load_gold() -> list[dict[str, Any]]:
    return [
        json.loads(line)
        for line in GOLD_PATH.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _values_equal(actual: Any, expected: Any) -> bool:
    if isinstance(actual, (int, float)) and isinstance(expected, (int, float)):
        return Decimal(str(actual)) == Decimal(str(expected))
    return actual == expected


def _box_center_is_grounded(actual: tuple[float, ...], expected: list[float]) -> bool:
    center_x = (actual[0] + actual[2]) / 2
    center_y = (actual[1] + actual[3]) / 2
    return expected[0] <= center_x <= expected[2] and expected[1] <= center_y <= expected[3]


def _confirm_against_gold(
    extraction: DocumentExtraction,
    gold: dict[str, Any],
) -> dict[str, Any]:
    expected = {
        item["field"]: item
        for item in gold["fields"]
        if item["field"] != "untrusted_instruction_text"
    }
    actual = {item.field.value: item for item in extraction.fields}
    field_checks = []
    for field_name in sorted(expected):
        extracted = actual.get(field_name)
        value_match = extracted is not None and _values_equal(
            extracted.value,
            expected[field_name]["value"],
        )
        evidence_match = extracted is not None and _box_center_is_grounded(
            extracted.evidence.bbox,
            expected[field_name]["bbox"],
        )
        field_checks.append(
            {
                "field": field_name,
                "value_match": value_match,
                "evidence_box_match": evidence_match,
                "confirmed_for_demo": value_match and evidence_match,
            }
        )
    unexpected = sorted(set(actual) - set(expected))
    all_confirmed = (
        not unexpected
        and len(actual) == len(expected)
        and all(item["confirmed_for_demo"] for item in field_checks)
    )
    return {
        "method": "checked_in_synthetic_gold_value_and_evidence_match",
        "synthetic_only": True,
        "all_allowlisted_fields_confirmed_for_demo": all_confirmed,
        "unexpected_fields": unexpected,
        "field_checks": field_checks,
    }


def _evidence(
    extraction: DocumentExtraction,
    field_name: FieldName,
) -> EvidenceReference:
    field = extraction.field_map()[field_name]
    width, height = extraction.page_size_points
    return EvidenceReference(
        source_document_id=extraction.document_id,
        field_name=field_name.value,
        page=field.evidence.page,
        source_box=tuple(Decimal(str(value)) for value in field.evidence.bbox),
        page_width=Decimal(str(width)),
        page_height=Decimal(str(height)),
        synthetic=True,
        untrusted_text_detected=bool(extraction.security_flags),
    )


def _monthly_amount(amount: Any, frequency: str) -> Decimal:
    return (
        Decimal(str(amount)) * PERIODS_PER_YEAR[frequency] / Decimal("12")
    ).quantize(MONEY, rounding=ROUND_HALF_UP)


def _income_input(extraction: DocumentExtraction) -> ConfirmedIncomeInput | None:
    fields = extraction.field_map()
    amount: Any
    frequency: str
    label: str
    evidence_field: FieldName
    if extraction.document_type.value == "pay_stub":
        amount = fields[FieldName.GROSS_PAY].value
        frequency = str(fields[FieldName.PAY_FREQUENCY].value)
        label = "Current gross pay"
        evidence_field = FieldName.GROSS_PAY
    elif extraction.document_type.value == "benefit_letter":
        amount = fields[FieldName.MONTHLY_BENEFIT].value
        frequency = str(fields[FieldName.BENEFIT_FREQUENCY].value)
        label = "Monthly benefit"
        evidence_field = FieldName.MONTHLY_BENEFIT
    elif extraction.document_type.value == "employment_letter":
        amount = Decimal(str(fields[FieldName.WEEKLY_HOURS].value)) * Decimal(
            str(fields[FieldName.HOURLY_RATE].value)
        )
        frequency = "weekly"
        label = "Verified weekly employment income"
        evidence_field = FieldName.HOURLY_RATE
    elif extraction.document_type.value == "self_employment_statement":
        amount = fields[FieldName.NET_BUSINESS_INCOME].value
        frequency = "monthly"
        label = "Documented monthly net business income"
        evidence_field = FieldName.NET_BUSINESS_INCOME
    else:
        return None
    return ConfirmedIncomeInput(
        source_id=f"{extraction.document_id}:{evidence_field.value}",
        label=label,
        amount=Decimal(str(amount)).quantize(MONEY, rounding=ROUND_HALF_UP),
        frequency=frequency,
        confirmed=True,
        uncertain=False,
        evidence=_evidence(extraction, evidence_field),
    )


def _run_rules(
    household_id: str,
    documents: list[DocumentExtraction],
) -> dict[str, Any]:
    application = next(
        (item for item in documents if item.document_type.value == "application_summary"),
        None,
    )
    incomes = [item for item in (_income_input(doc) for doc in documents) if item]
    missing = []
    if application is None or FieldName.HOUSEHOLD_SIZE not in application.field_map():
        missing.append("confirmed_household_size")
    if not incomes:
        missing.append("confirmed_recurring_income")
    if missing:
        return {
            "status": "ABSTAIN",
            "reason": "Required confirmed evidence is unavailable in this synthetic packet.",
            "missing": missing,
        }
    request = RulesEvaluationRequest(
        household_id=household_id,
        program_id=EXPECTED_PROGRAM_ID,
        rule_year=EXPECTED_RULE_YEAR,
        area=EXPECTED_AREA,
        ami_percentage=EXPECTED_AMI_PERCENTAGE,
        household_size=int(
            application.field_map()[FieldName.HOUSEHOLD_SIZE].value
        ),
        income_sources=incomes,
    )
    return {
        "status": "EVALUATED",
        "request": request.model_dump(mode="json"),
        "response": RulesEngine().evaluate(request).model_dump(mode="json"),
    }


def _run_financial_readiness(
    household_id: str,
    documents: list[DocumentExtraction],
) -> dict[str, Any] | None:
    try:
        from backend.app.schemas.financial_readiness import (
            FinancialReadinessRequest,
            FinancialValueInput,
            LiquidAssetInput,
            MonthlyIncomeHistoryPoint,
            MonthlyIncomeInput,
            VerificationStatus,
        )
        from backend.app.services.financial_readiness import FinancialReadinessEngine
    except ModuleNotFoundError:
        return None

    income_sources = []
    history = []
    rent = None
    liquid_assets = []
    for document in documents:
        fields = document.field_map()
        rule_income = _income_input(document)
        if rule_income is not None:
            monthly = _monthly_amount(rule_income.amount, rule_income.frequency)
            income_sources.append(
                MonthlyIncomeInput(
                    value_id=rule_income.source_id,
                    label=rule_income.label,
                    amount=monthly,
                    verification_status=VerificationStatus.CONFIRMED,
                    evidence=rule_income.evidence,
                    source_type=document.document_type.value,
                    recurring=True,
                )
            )
            month = None
            if FieldName.PAY_DATE in fields:
                month = str(fields[FieldName.PAY_DATE].value)[:7]
            elif FieldName.DOCUMENT_DATE in fields:
                month = str(fields[FieldName.DOCUMENT_DATE].value)[:7]
            elif FieldName.STATEMENT_MONTH in fields:
                month = str(fields[FieldName.STATEMENT_MONTH].value)
            if month and not any(item.month == month for item in history):
                history.append(
                    MonthlyIncomeHistoryPoint(
                        month=month,
                        amount=monthly,
                        verification_status=VerificationStatus.CONFIRMED,
                        evidence=rule_income.evidence,
                    )
                )
        if FieldName.MONTHLY_RENT in fields:
            rent = FinancialValueInput(
                value_id=f"{document.document_id}:monthly_rent",
                label="Documented monthly rent",
                amount=Decimal(str(fields[FieldName.MONTHLY_RENT].value)),
                verification_status=VerificationStatus.CONFIRMED,
                evidence=_evidence(document, FieldName.MONTHLY_RENT),
            )
        if FieldName.ENDING_BALANCE in fields:
            liquid_assets.append(
                LiquidAssetInput(
                    value_id=f"{document.document_id}:ending_balance",
                    label="Documented bank ending balance",
                    amount=Decimal(str(fields[FieldName.ENDING_BALANCE].value)),
                    verification_status=VerificationStatus.CONFIRMED,
                    evidence=_evidence(document, FieldName.ENDING_BALANCE),
                    asset_type="bank_deposit_account",
                    accessible=True,
                )
            )

    request = FinancialReadinessRequest(
        household_id=household_id,
        program_id=EXPECTED_PROGRAM_ID,
        rule_year=EXPECTED_RULE_YEAR,
        area=EXPECTED_AREA,
        income_sources=income_sources,
        monthly_income_history=history,
        rent=rent,
        recurring_utilities=[],
        housing_costs_complete=False,
        liquid_assets=liquid_assets,
        reconciliation_facts=[],
    )
    response = FinancialReadinessEngine().evaluate(request)
    return {
        "status": "EVALUATED",
        "request": request.model_dump(mode="json"),
        "response": response.model_dump(mode="json"),
    }


def run_pipeline() -> dict[str, Any]:
    gold_rows = _load_gold()
    documents: list[dict[str, Any]] = []
    grouped: dict[str, list[DocumentExtraction]] = defaultdict(list)
    confirmation_count = 0
    for gold in sorted(gold_rows, key=lambda item: item["file_name"]):
        extraction = extract_document(DOCUMENTS_ROOT / gold["file_name"], enable_ocr=True)
        confirmation = _confirm_against_gold(extraction, gold)
        confirmation_count += int(
            confirmation["all_allowlisted_fields_confirmed_for_demo"]
        )
        grouped[gold["household_id"]].append(extraction)
        documents.append(
            {
                "file_name": gold["file_name"],
                "household_id": gold["household_id"],
                "extraction": extraction.model_dump(mode="json"),
                "synthetic_confirmation": confirmation,
            }
        )

    households = []
    risk_available = False
    for household_id in sorted(grouped):
        financial = _run_financial_readiness(household_id, grouped[household_id])
        risk_available |= financial is not None
        households.append(
            {
                "household_id": household_id,
                "document_ids": sorted(item.document_id for item in grouped[household_id]),
                "rules_and_math": _run_rules(household_id, grouped[household_id]),
                "financial_readiness": financial
                or {
                    "status": "NOT_AVAILABLE",
                    "reason": "Financial-readiness module is not present on this branch.",
                },
            }
        )

    status_counts = Counter(
        item["extraction"]["status"] for item in documents
    )
    security_flags = sum(
        len(item["extraction"]["security_flags"]) for item in documents
    )
    checksum = hashlib.sha256(
        (FIXTURE_ROOT / "checksums.sha256").read_bytes()
    ).hexdigest()
    return {
        "schema_version": "1.0",
        "pipeline_variant": (
            "rules_and_financial_readiness" if risk_available else "rules_only"
        ),
        "source_pack": "saad_extended",
        "source_pack_checksum_manifest_sha256": checksum,
        "synthetic_only": True,
        "advisory_only": True,
        "decision_boundary": (
            "This output does not approve, deny, score, rank, predict acceptance, "
            "or determine housing eligibility."
        ),
        "summary": {
            "documents_processed": len(documents),
            "households_processed": len(households),
            "documents_confirmed_against_synthetic_gold": confirmation_count,
            "extraction_status_counts": dict(sorted(status_counts.items())),
            "ignored_embedded_instruction_flags": security_flags,
            "financial_readiness_available": risk_available,
        },
        "documents": documents,
        "households": households,
    }


def main() -> None:
    payload = run_pipeline()
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with OUTPUT_PATH.open("w", encoding="utf-8", newline="\n") as handle:
        json.dump(payload, handle, indent=2, sort_keys=True)
        handle.write("\n")
    print(
        f"Processed {payload['summary']['documents_processed']} documents; "
        f"wrote {OUTPUT_PATH.relative_to(REPOSITORY_ROOT)}"
    )


if __name__ == "__main__":
    main()
