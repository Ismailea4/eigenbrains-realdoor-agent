"""Typed contracts for RealDoor's frozen rules and deterministic math stage."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field, model_validator


class StrictModel(BaseModel):
    """Reject undeclared fields so rules inputs cannot silently change meaning."""

    model_config = ConfigDict(extra="forbid")


class Comparison(str, Enum):
    BELOW_OR_EQUAL = "below_or_equal"
    ABOVE = "above"
    NO_FROZEN_THRESHOLD = "no_frozen_threshold"
    NOT_CALCULATED = "not_calculated"


class ReviewStatus(str, Enum):
    READY_TO_REVIEW = "READY_TO_REVIEW"
    NEEDS_REVIEW = "NEEDS_REVIEW"


class ReviewReasonCode(str, Enum):
    PROGRAM_NOT_FROZEN = "PROGRAM_NOT_FROZEN"
    RULE_YEAR_NOT_FROZEN = "RULE_YEAR_NOT_FROZEN"
    AREA_NOT_FROZEN = "AREA_NOT_FROZEN"
    AMI_PERCENTAGE_NOT_FROZEN = "AMI_PERCENTAGE_NOT_FROZEN"
    HOUSEHOLD_SIZE_OUTSIDE_TABLE = "HOUSEHOLD_SIZE_OUTSIDE_TABLE"
    NO_INCOME_SOURCES = "NO_INCOME_SOURCES"
    UNCONFIRMED_INPUT = "UNCONFIRMED_INPUT"
    UNCERTAIN_INPUT = "UNCERTAIN_INPUT"
    MISSING_SOURCE_EVIDENCE = "MISSING_SOURCE_EVIDENCE"
    NON_SYNTHETIC_DOCUMENT = "NON_SYNTHETIC_DOCUMENT"
    UNSUPPORTED_FREQUENCY = "UNSUPPORTED_FREQUENCY"
    DECISION_REQUEST_REFUSED = "DECISION_REQUEST_REFUSED"
    QUESTION_NOT_SUPPORTED = "QUESTION_NOT_SUPPORTED"


class RuleQuestionIntent(str, Enum):
    THRESHOLD = "threshold"
    EFFECTIVE_DATE = "effective_date"
    PROGRAM_SCOPE = "program_scope"
    DECISION_BOUNDARY = "decision_boundary"
    DATASET_LIMITATION = "dataset_limitation"
    GEOCODE_PRECISION = "geocode_precision"
    DOCUMENT_SAFETY = "document_safety"
    DOCUMENT_CURRENCY = "document_currency"
    FEDERAL_ANCHOR = "federal_anchor"
    COMPLIANCE_MONITORING = "compliance_monitoring"
    UNSUPPORTED = "unsupported"


class Citation(StrictModel):
    rule_id: str
    authority: str
    text: str
    source_url: str
    source_locator: str
    effective_date: date | None = None


class ThresholdRow(StrictModel):
    household_size: int = Field(ge=1, le=8)
    amount: Decimal = Field(ge=0, decimal_places=2)


class ProgramScope(StrictModel):
    corpus_version: str
    frozen_at: date
    runtime_network_access: bool
    program_id: str
    program_name: str
    rule_year: int
    area: str
    ami_percentage: int
    effective_date: date
    thresholds: list[ThresholdRow]
    citation: Citation
    decision_boundary: str


class EvidenceReference(StrictModel):
    """Trace a confirmed value to a synthetic document source box."""

    source_document_id: str = Field(min_length=1)
    field_name: str = Field(min_length=1)
    page: int = Field(ge=1)
    source_box: tuple[Decimal, Decimal, Decimal, Decimal]
    page_width: Decimal = Field(default=Decimal("612"), gt=0)
    page_height: Decimal = Field(default=Decimal("792"), gt=0)
    synthetic: bool
    untrusted_text_detected: bool = False

    @model_validator(mode="after")
    def validate_source_box(self) -> EvidenceReference:
        x1, y1, x2, y2 = self.source_box
        if not (
            Decimal("0") <= x1 < x2 <= self.page_width
            and Decimal("0") <= y1 < y2 <= self.page_height
        ):
            raise ValueError("source_box must be inside the declared page dimensions")
        return self


class ConfirmedIncomeInput(StrictModel):
    source_id: str = Field(min_length=1)
    label: str = Field(min_length=1)
    amount: Decimal = Field(ge=0, decimal_places=2)
    frequency: str = Field(min_length=1)
    confirmed: bool
    uncertain: bool = False
    uncertainty_reason: str | None = None
    evidence: EvidenceReference | None = None

    @model_validator(mode="after")
    def require_uncertainty_reason(self) -> ConfirmedIncomeInput:
        if self.uncertain and not self.uncertainty_reason:
            raise ValueError("uncertainty_reason is required when uncertain is true")
        return self


class RulesEvaluationRequest(StrictModel):
    household_id: str = Field(min_length=1)
    program_id: str = Field(min_length=1)
    rule_year: int
    area: str = Field(min_length=1)
    ami_percentage: int
    household_size: int
    income_sources: list[ConfirmedIncomeInput]


class InputCalculationTrace(StrictModel):
    source_id: str
    label: str
    confirmed_value: Decimal
    frequency: str
    periods_per_year: int
    formula: str
    annualized_value: Decimal
    evidence: EvidenceReference


class ReviewReason(StrictModel):
    code: ReviewReasonCode
    message: str
    source_id: str | None = None


class RulesEvaluationResponse(StrictModel):
    household_id: str
    status: ReviewStatus
    abstained: bool
    program: ProgramScope
    household_size: int
    input_traces: list[InputCalculationTrace]
    annualized_income: Decimal | None
    threshold: Decimal | None
    comparison: Comparison
    formula: str | None
    effective_date: date
    citations: list[Citation]
    review_reasons: list[ReviewReason]
    untrusted_document_text_ignored: bool
    decision_boundary: str


class RuleQuestionRequest(StrictModel):
    question: str = Field(min_length=1, max_length=1000)
    program_id: str = Field(min_length=1)
    rule_year: int
    area: str = Field(min_length=1)
    ami_percentage: int
    household_size: int | None = None


class RuleQuestionResponse(StrictModel):
    intent: RuleQuestionIntent
    answer: str
    abstained: bool
    citations: list[Citation]
    effective_date: date
    review_reasons: list[ReviewReason]
    decision_boundary: str
