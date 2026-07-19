"""Typed inputs and explainable outputs for advisory financial-readiness metrics."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from enum import Enum

from pydantic import Field, model_validator

from .calculator import EvidenceReference, StrictModel


class VerificationStatus(str, Enum):
    CONFIRMED = "CONFIRMED"
    PROVISIONAL = "PROVISIONAL"
    UNVERIFIED = "UNVERIFIED"


class MetricStatus(str, Enum):
    """Metric-level status only; never an applicant or eligibility outcome."""

    PASS = "PASS"
    REVIEW = "REVIEW"
    ABSTAIN = "ABSTAIN"


class MetricId(str, Enum):
    VERIFIED_MONTHLY_INCOME = "RULE_VERIFIED_MONTHLY_INCOME"
    HOUSING_COST_BURDEN = "RULE_HOUSING_COST_BURDEN"
    INCOME_STABILITY = "RULE_INCOME_STABILITY"
    LIQUID_RESERVE_COVERAGE = "RULE_LIQUID_RESERVE_COVERAGE"
    DOWNSIDE_AFFORDABILITY = "RULE_DOWNSIDE_AFFORDABILITY"
    CROSS_DOCUMENT_RECONCILIATION = "RULE_CROSS_DOCUMENT_RECONCILIATION"


class RiskReasonCode(str, Enum):
    SCOPE_NOT_SUPPORTED = "SCOPE_NOT_SUPPORTED"
    NO_CONFIRMED_INCOME = "NO_CONFIRMED_INCOME"
    PROVISIONAL_INPUT_REQUIRES_CONFIRMATION = "PROVISIONAL_INPUT_REQUIRES_CONFIRMATION"
    UNVERIFIED_INPUT_EXCLUDED = "UNVERIFIED_INPUT_EXCLUDED"
    MISSING_OR_INVALID_EVIDENCE = "MISSING_OR_INVALID_EVIDENCE"
    HOUSING_COSTS_INCOMPLETE = "HOUSING_COSTS_INCOMPLETE"
    ZERO_HOUSING_COST = "ZERO_HOUSING_COST"
    INSUFFICIENT_INCOME_HISTORY = "INSUFFICIENT_INCOME_HISTORY"
    ZERO_MEAN_INCOME = "ZERO_MEAN_INCOME"
    NO_CONFIRMED_ACCESSIBLE_RESERVES = "NO_CONFIRMED_ACCESSIBLE_RESERVES"
    INSUFFICIENT_RECONCILIATION_EVIDENCE = "INSUFFICIENT_RECONCILIATION_EVIDENCE"


class StressBasis(str, Enum):
    POLICY_DEFAULT = "policy_default"
    RENTER_SELECTED_SCENARIO = "renter_selected_scenario"
    HISTORICAL_OBSERVATION = "historical_observation"


class FinancialValueInput(StrictModel):
    value_id: str = Field(min_length=1)
    label: str = Field(min_length=1)
    amount: Decimal = Field(ge=0, decimal_places=2)
    verification_status: VerificationStatus
    evidence: EvidenceReference | None = None


class MonthlyIncomeInput(FinancialValueInput):
    source_type: str = Field(min_length=1)
    recurring: bool = True


class MonthlyIncomeHistoryPoint(StrictModel):
    month: str = Field(pattern=r"^\d{4}-(0[1-9]|1[0-2])$")
    amount: Decimal = Field(ge=0, decimal_places=2)
    verification_status: VerificationStatus
    evidence: EvidenceReference | None = None


class LiquidAssetInput(FinancialValueInput):
    asset_type: str = Field(min_length=1)
    accessible: bool


class ReconciliationObservation(FinancialValueInput):
    document_role: str = Field(min_length=1)


class ReconciliationFactInput(StrictModel):
    fact_id: str = Field(min_length=1)
    label: str = Field(min_length=1)
    observations: list[ReconciliationObservation]

    @model_validator(mode="after")
    def observation_ids_are_unique(self) -> ReconciliationFactInput:
        ids = [observation.value_id for observation in self.observations]
        if len(ids) != len(set(ids)):
            raise ValueError("reconciliation observation value_id values must be unique")
        return self


class StressScenario(StrictModel):
    shock_rate: Decimal | None = Field(default=None, ge=0, lt=1, decimal_places=4)
    basis: StressBasis = StressBasis.POLICY_DEFAULT
    description: str | None = Field(default=None, max_length=500)

    @model_validator(mode="after")
    def validate_custom_scenario(self) -> StressScenario:
        if self.basis == StressBasis.POLICY_DEFAULT and self.shock_rate is not None:
            raise ValueError("policy_default must use the policy shock rate")
        if self.basis != StressBasis.POLICY_DEFAULT:
            if self.shock_rate is None:
                raise ValueError("a non-default stress scenario requires shock_rate")
            if not self.description:
                raise ValueError("a non-default stress scenario requires a description")
        return self


class FinancialReadinessRequest(StrictModel):
    household_id: str = Field(min_length=1)
    program_id: str = Field(min_length=1)
    rule_year: int
    area: str = Field(min_length=1)
    income_sources: list[MonthlyIncomeInput]
    monthly_income_history: list[MonthlyIncomeHistoryPoint]
    rent: FinancialValueInput | None = None
    recurring_utilities: list[FinancialValueInput]
    housing_costs_complete: bool
    liquid_assets: list[LiquidAssetInput]
    reconciliation_facts: list[ReconciliationFactInput]
    stress_scenario: StressScenario = Field(default_factory=StressScenario)

    @model_validator(mode="after")
    def identifiers_and_months_are_unique(self) -> FinancialReadinessRequest:
        income_ids = [item.value_id for item in self.income_sources]
        if len(income_ids) != len(set(income_ids)):
            raise ValueError("income source value_id values must be unique")
        history_months = [item.month for item in self.monthly_income_history]
        if len(history_months) != len(set(history_months)):
            raise ValueError("monthly income history months must be unique")
        fact_ids = [fact.fact_id for fact in self.reconciliation_facts]
        if len(fact_ids) != len(set(fact_ids)):
            raise ValueError("reconciliation fact_id values must be unique")
        return self


class AdvisoryCitation(StrictModel):
    citation_id: str
    authority: str
    title: str
    url: str
    note: str


class RiskPolicySummary(StrictModel):
    policy_id: str
    policy_version: str
    effective_date: date
    advisory_only: bool
    aggregate_score_enabled: bool
    program_id: str
    rule_year: int
    area: str
    housing_lower_burden_max: Decimal
    housing_elevated_burden_max: Decimal
    income_cv_review_above: Decimal
    minimum_income_history_months: int
    default_stress_shock_rate: Decimal
    stress_coverage_review_below: Decimal
    reconciliation_review_above: Decimal


class RiskReviewReason(StrictModel):
    code: RiskReasonCode
    message: str
    input_id: str | None = None


class MetricEvidence(StrictModel):
    input_id: str
    evidence: EvidenceReference


class MetricDetail(StrictModel):
    key: str
    label: str
    value: Decimal | None = None
    text: str | None = None
    unit: str | None = None

    @model_validator(mode="after")
    def require_one_detail_value(self) -> MetricDetail:
        if (self.value is None) == (self.text is None):
            raise ValueError("metric detail must contain exactly one of value or text")
        return self


class FinancialMetricResult(StrictModel):
    rule_id: MetricId
    status: MetricStatus
    value: Decimal | None
    unit: str | None
    interpretation: str
    formula: str | None
    threshold: Decimal | None
    threshold_source: str
    requires_human_confirmation: bool
    details: list[MetricDetail]
    evidence: list[MetricEvidence]
    citations: list[AdvisoryCitation]
    review_reasons: list[RiskReviewReason]


class IncomeConfidenceScenario(StrictModel):
    confirmed_monthly_income: Decimal
    potential_verified_monthly_income: Decimal
    provisional_amount_excluded_from_confirmed: Decimal


class FinancialReadinessResponse(StrictModel):
    household_id: str
    scope_valid: bool
    policy: RiskPolicySummary
    income_scenarios: IncomeConfidenceScenario
    metrics: list[FinancialMetricResult]
    governance_citations: list[AdvisoryCitation]
    untrusted_document_text_ignored: bool
    decision_boundary: str
    review_reasons: list[RiskReviewReason]
