"""Typed contracts for the renter-controlled application-readiness journey."""

from __future__ import annotations

from datetime import date
from enum import Enum

from pydantic import Field, model_validator

from .calculator import RulesEvaluationResponse, StrictModel
from .financial_readiness import FinancialReadinessResponse
from .profile import DocumentExtraction, EvidenceRef, FieldName


DECISION_BOUNDARY = (
    "This packet supports renter preparation and qualified human review only. "
    "It does not approve, deny, score, rank, predict acceptance, or determine eligibility."
)


class SessionStatus(str, Enum):
    ACTIVE = "ACTIVE"


class FieldAction(str, Enum):
    CONFIRM = "CONFIRM"
    CORRECT = "CORRECT"


class ChecklistStatus(str, Enum):
    PRESENT = "PRESENT"
    MISSING = "MISSING"
    EXPIRED = "EXPIRED"
    NEEDS_CONFIRMATION = "NEEDS_CONFIRMATION"


class JourneyReadinessStatus(str, Enum):
    READY_TO_REVIEW = "READY_TO_REVIEW"
    NEEDS_REVIEW = "NEEDS_REVIEW"


class RenterBudgetStageStatus(str, Enum):
    NOT_REQUESTED = "NOT_REQUESTED"
    DISABLED = "DISABLED"
    EVALUATED = "EVALUATED"


class CreateSessionRequest(StrictModel):
    household_id: str = Field(min_length=1, max_length=100)


class CreateSessionResponse(StrictModel):
    session_id: str
    household_id: str
    status: SessionStatus
    raw_document_bytes_retained: bool
    decision_boundary: str = DECISION_BOUNDARY


class UploadDocumentResponse(StrictModel):
    session_id: str
    extraction: DocumentExtraction
    confirmation_required: bool
    raw_document_bytes_retained: bool
    data_use: str


class FieldDecision(StrictModel):
    document_id: str = Field(min_length=1)
    field_name: FieldName
    action: FieldAction
    corrected_value: str | int | float | None = None

    @model_validator(mode="after")
    def validate_correction(self) -> FieldDecision:
        if self.action is FieldAction.CORRECT and self.corrected_value is None:
            raise ValueError("CORRECT requires corrected_value")
        if self.action is FieldAction.CONFIRM and self.corrected_value is not None:
            raise ValueError("CONFIRM cannot include corrected_value")
        return self


class ConfirmFieldsRequest(StrictModel):
    consent_to_reuse_confirmed_values: bool
    decisions: list[FieldDecision] = Field(min_length=1)


class ConfirmedProfileField(StrictModel):
    document_id: str
    field_name: FieldName
    proposed_value: str | int | float
    confirmed_value: str | int | float
    corrected_by_renter: bool
    evidence: EvidenceRef
    sensitive: bool
    reusable: bool


class AuditEvent(StrictModel):
    sequence: int = Field(ge=1)
    action: str
    document_id: str | None = None
    field_name: FieldName | None = None
    rule_corpus_version: str | None = None
    renter_budget_policy_version: str | None = None


class ConfirmationResponse(StrictModel):
    session_id: str
    consent_recorded: bool
    confirmed_fields: list[ConfirmedProfileField]
    recalculation_required: bool
    audit_events: list[AuditEvent]


class EvaluateSessionRequest(StrictModel):
    as_of_date: date
    include_renter_budget: bool = False


class ChecklistItem(StrictModel):
    document_type: str
    status: ChecklistStatus
    document_ids: list[str]
    message: str
    observed_date: date | None = None
    age_days: int | None = Field(default=None, ge=0)


class ChecklistResult(StrictModel):
    checklist_version: str
    source: str
    as_of_date: date
    recency_window_days: int
    status: JourneyReadinessStatus
    items: list[ChecklistItem]


class RenterBudgetStage(StrictModel):
    status: RenterBudgetStageStatus
    renter_controlled: bool
    provider_use_prohibited: bool
    message: str
    result: FinancialReadinessResponse | None = None


class SessionEvaluationResponse(StrictModel):
    session_id: str
    household_id: str
    rules_and_math: RulesEvaluationResponse
    checklist: ChecklistResult
    renter_budget: RenterBudgetStage
    audit_events: list[AuditEvent]
    decision_boundary: str = DECISION_BOUNDARY


class ExportPacketRequest(StrictModel):
    renter_requested_export: bool
    as_of_date: date
    include_renter_budget: bool = False


class ApplicationReadinessPacket(StrictModel):
    packet_version: str
    editable: bool
    renter_controlled: bool
    auto_send_disabled: bool
    household_id: str
    confirmed_profile: list[ConfirmedProfileField]
    checklist: ChecklistResult
    rules_and_math: RulesEvaluationResponse
    renter_budget: RenterBudgetStage
    source_document_ids: list[str]
    decision_boundary: str = DECISION_BOUNDARY


class DeleteSessionResponse(StrictModel):
    session_id: str
    deleted: bool
    raw_document_bytes_retained: bool
    extracted_state_retained: bool
    message: str
