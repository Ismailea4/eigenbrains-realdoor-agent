"""Typed contracts for the synthetic global pipeline and reference review."""

from __future__ import annotations

from enum import Enum

from pydantic import Field, JsonValue, model_validator

from .calculator import RulesEvaluationRequest, RulesEvaluationResponse, StrictModel
from .profile import DocumentExtraction


AGGREGATE_DECISION_BOUNDARY = (
    "This aggregate supports renter preparation and qualified human review only. "
    "It does not approve, deny, score, rank, predict acceptance, or determine "
    "housing eligibility."
)


class RulesStageStatus(str, Enum):
    EVALUATED = "EVALUATED"
    ABSTAIN = "ABSTAIN"


class RenterBudgetBatchStatus(str, Enum):
    EVALUATED = "EVALUATED"
    NOT_AVAILABLE = "NOT_AVAILABLE"


class ReferenceReviewStatus(str, Enum):
    MATCHES_FOUND = "MATCHES_FOUND"
    NO_DOCUMENT_SPECIFIC_MATCHES = "NO_DOCUMENT_SPECIFIC_MATCHES"


class SyntheticFieldCheck(StrictModel):
    field: str
    value_match: bool
    evidence_box_match: bool
    confirmed_for_demo: bool


class SyntheticConfirmation(StrictModel):
    method: str
    synthetic_only: bool
    all_allowlisted_fields_confirmed_for_demo: bool
    unexpected_fields: list[str]
    field_checks: list[SyntheticFieldCheck]


class AggregateDocument(StrictModel):
    file_name: str
    household_id: str
    extraction: DocumentExtraction
    synthetic_confirmation: SyntheticConfirmation


class RulesStage(StrictModel):
    status: RulesStageStatus
    reason: str | None = None
    missing: list[str] = Field(default_factory=list)
    request: RulesEvaluationRequest | None = None
    response: RulesEvaluationResponse | None = None

    @model_validator(mode="after")
    def validate_stage_shape(self) -> RulesStage:
        if self.status is RulesStageStatus.EVALUATED:
            if self.request is None or self.response is None:
                raise ValueError("EVALUATED rules stage requires request and response")
        elif not self.reason:
            raise ValueError("ABSTAIN rules stage requires a reason")
        return self


class RenterBudgetBatchStage(StrictModel):
    status: RenterBudgetBatchStatus
    reason: str | None = None
    request: dict[str, JsonValue] | None = None
    response: dict[str, JsonValue] | None = None

    @model_validator(mode="after")
    def validate_stage_shape(self) -> RenterBudgetBatchStage:
        if self.status is RenterBudgetBatchStatus.EVALUATED:
            if self.request is None or self.response is None:
                raise ValueError("EVALUATED renter-budget stage requires request and response")
        elif not self.reason:
            raise ValueError("NOT_AVAILABLE renter-budget stage requires a reason")
        return self


class AggregateHousehold(StrictModel):
    household_id: str
    document_ids: list[str]
    rules_and_math: RulesStage
    renter_budget: RenterBudgetBatchStage


class ReferenceRule(StrictModel):
    rule_id: str
    title: str
    rule: str
    page: int = Field(ge=1)


class ReferenceCatalogSummary(StrictModel):
    catalog_version: str
    catalog_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    rules_loaded: int = Field(ge=1)
    authoritative_for_calculation: bool
    runtime_rule_override_enabled: bool
    source_note: str


class ReferenceMatch(StrictModel):
    rule_id: str
    title: str
    rule: str
    page: int = Field(ge=1)
    match_basis: str


class ExternalReferenceCitation(StrictModel):
    source: int = Field(ge=1)
    title: str
    url: str
    snippet: str
    relevance_score: float | None = Field(default=None, ge=0, le=1)


class ExternalReferenceNarrative(StrictModel):
    summary: str
    limitations: list[str]
    cited_urls: list[str]


class DocumentReferenceReview(StrictModel):
    document_id: str
    document_type: str
    status: ReferenceReviewStatus
    matched_rules: list[ReferenceMatch]
    external_research_used: bool
    external_sources: list[ExternalReferenceCitation]
    external_narrative: ExternalReferenceNarrative | None = None
    extracted_values_sent_externally: bool
    untrusted_document_text_ignored: bool
    message: str


class AggregateReferenceReview(StrictModel):
    catalog: ReferenceCatalogSummary
    documents_reviewed: int = Field(ge=0)
    external_research_enabled: bool
    explicit_external_processing_consent: bool
    reviews: list[DocumentReferenceReview]
    decision_boundary: str = AGGREGATE_DECISION_BOUNDARY


class AggregateSummary(StrictModel):
    documents_processed: int = Field(ge=0)
    households_processed: int = Field(ge=0)
    documents_confirmed_against_synthetic_gold: int = Field(ge=0)
    extraction_status_counts: dict[str, int]
    ignored_embedded_instruction_flags: int = Field(ge=0)
    renter_budget_available: bool
    reference_documents_reviewed: int = Field(ge=0)
    supplemental_reference_rules_loaded: int = Field(ge=0)


class GlobalAggregateResponse(StrictModel):
    schema_version: str
    pipeline_variant: str
    source_pack: str
    source_pack_checksum_manifest_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    synthetic_only: bool
    advisory_only: bool
    decision_boundary: str = AGGREGATE_DECISION_BOUNDARY
    summary: AggregateSummary
    documents: list[AggregateDocument]
    households: list[AggregateHousehold]
    reference_review: AggregateReferenceReview

