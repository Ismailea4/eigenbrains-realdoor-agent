"""Transparent, deterministic financial-readiness indicators.

The engine calculates six evidence-linked advisory metrics. It has no model,
network, persistence, applicant ranking, aggregate score, or eligibility logic.
"""

from __future__ import annotations

import hashlib
import json
from datetime import date
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path

from pydantic import BaseModel, ConfigDict, ValidationError

from ..schemas.calculator import EvidenceReference
from ..schemas.financial_readiness import (
    AdvisoryCitation,
    FinancialMetricResult,
    FinancialReadinessRequest,
    FinancialReadinessResponse,
    FinancialValueInput,
    IncomeConfidenceScenario,
    MetricDetail,
    MetricEvidence,
    MetricId,
    MetricStatus,
    RiskPolicySummary,
    RiskReasonCode,
    RiskReviewReason,
    StressBasis,
    VerificationStatus,
)
from .calculator import format_money, money, sum_money


REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_POLICY_PATH = REPOSITORY_ROOT / "data" / "risk_management" / "advisory_policy.json"
EXPECTED_POLICY_SHA256 = "3d68e8c46541491a8007947ad2d79091d39cb4253c4256132fee4f67922aed37"
RATIO_PLACES = Decimal("0.0001")


def canonical_policy_bytes(policy_bytes: bytes) -> bytes:
    """Normalize Git-managed line endings before verifying policy integrity."""

    return policy_bytes.replace(b"\r\n", b"\n")


class RiskPolicyIntegrityError(RuntimeError):
    """The versioned financial-readiness policy is missing or changed."""


class _PolicyModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class _Citation(_PolicyModel):
    citation_id: str
    authority: str
    title: str
    url: str
    note: str


class _HousingBurdenPolicy(_PolicyModel):
    lower_burden_max: Decimal
    elevated_burden_max: Decimal
    threshold_source: str
    citation_id: str


class _IncomeStabilityPolicy(_PolicyModel):
    minimum_observed_months: int
    recent_average_months: int
    cv_review_above: Decimal
    threshold_source: str
    legal_threshold: bool


class _ReserveCoveragePolicy(_PolicyModel):
    minimum_coverage_threshold: Decimal | None
    threshold_source: str
    legal_threshold: bool


class _StressPolicy(_PolicyModel):
    default_income_shock_rate: Decimal
    coverage_review_below: Decimal
    threshold_source: str
    legal_threshold: bool


class _ReconciliationPolicy(_PolicyModel):
    relative_difference_review_above: Decimal
    threshold_source: str
    legal_threshold: bool


class _RiskPolicy(_PolicyModel):
    schema_version: str
    policy_id: str
    policy_version: str
    effective_date: date
    advisory_only: bool
    aggregate_score_enabled: bool
    program_id: str
    rule_year: int
    area: str
    housing_burden: _HousingBurdenPolicy
    income_stability: _IncomeStabilityPolicy
    reserve_coverage: _ReserveCoveragePolicy
    stress_test: _StressPolicy
    reconciliation: _ReconciliationPolicy
    citations: list[_Citation]
    decision_boundary: str


class FinancialReadinessEngine:
    """Evaluate advisory metrics without producing an overall applicant outcome."""

    def __init__(self, policy_path: str | Path = DEFAULT_POLICY_PATH) -> None:
        self.policy_path = Path(policy_path).resolve()
        self._policy = self._load_policy()
        self._citations = {
            citation.citation_id: AdvisoryCitation.model_validate(citation.model_dump())
            for citation in self._policy.citations
        }
        self._validate_policy()
        self._policy_summary = self._build_policy_summary()

    @property
    def policy(self) -> RiskPolicySummary:
        return self._policy_summary.model_copy(deep=True)

    def _load_policy(self) -> _RiskPolicy:
        if not self.policy_path.is_relative_to(REPOSITORY_ROOT):
            raise RiskPolicyIntegrityError("Risk policy path escapes the repository")
        try:
            policy_bytes = self.policy_path.read_bytes()
        except OSError as exc:
            raise RiskPolicyIntegrityError("Risk policy is unavailable") from exc
        if (
            hashlib.sha256(canonical_policy_bytes(policy_bytes)).hexdigest()
            != EXPECTED_POLICY_SHA256
        ):
            raise RiskPolicyIntegrityError("Risk policy checksum mismatch")
        try:
            return _RiskPolicy.model_validate(json.loads(policy_bytes.decode("utf-8")))
        except (UnicodeDecodeError, json.JSONDecodeError, ValidationError) as exc:
            raise RiskPolicyIntegrityError("Risk policy is invalid") from exc

    def _validate_policy(self) -> None:
        if not self._policy.advisory_only or self._policy.aggregate_score_enabled:
            raise RiskPolicyIntegrityError("Policy must be advisory-only with scoring disabled")
        if not (
            Decimal("0") < self._policy.housing_burden.lower_burden_max
            < self._policy.housing_burden.elevated_burden_max
            < Decimal("1")
        ):
            raise RiskPolicyIntegrityError("Housing-burden bands are invalid")
        if self._policy.income_stability.minimum_observed_months < 3:
            raise RiskPolicyIntegrityError("Income stability requires at least three months")
        if not Decimal("0") <= self._policy.stress_test.default_income_shock_rate < Decimal("1"):
            raise RiskPolicyIntegrityError("Stress shock rate is invalid")
        if self._policy.stress_test.legal_threshold:
            raise RiskPolicyIntegrityError("Stress scenario cannot be labeled a legal threshold")
        if self._policy.income_stability.legal_threshold:
            raise RiskPolicyIntegrityError("CV threshold cannot be labeled a legal threshold")
        if self._policy.reconciliation.legal_threshold:
            raise RiskPolicyIntegrityError("Reconciliation tolerance cannot be a legal threshold")
        required_citations = {
            "HUD-CHAS-COST-BURDEN",
            "HUD-AI-TENANT-SCREENING",
            "CFPB-TENANT-SCREENING-RIGHTS",
        }
        if not required_citations <= self._citations.keys():
            raise RiskPolicyIntegrityError("Risk policy is missing governance citations")

    def _build_policy_summary(self) -> RiskPolicySummary:
        return RiskPolicySummary(
            policy_id=self._policy.policy_id,
            policy_version=self._policy.policy_version,
            effective_date=self._policy.effective_date,
            advisory_only=self._policy.advisory_only,
            aggregate_score_enabled=self._policy.aggregate_score_enabled,
            program_id=self._policy.program_id,
            rule_year=self._policy.rule_year,
            area=self._policy.area,
            housing_lower_burden_max=self._policy.housing_burden.lower_burden_max,
            housing_elevated_burden_max=self._policy.housing_burden.elevated_burden_max,
            income_cv_review_above=self._policy.income_stability.cv_review_above,
            minimum_income_history_months=self._policy.income_stability.minimum_observed_months,
            default_stress_shock_rate=self._policy.stress_test.default_income_shock_rate,
            stress_coverage_review_below=self._policy.stress_test.coverage_review_below,
            reconciliation_review_above=(
                self._policy.reconciliation.relative_difference_review_above
            ),
        )

    @staticmethod
    def _ratio(numerator: Decimal, denominator: Decimal) -> Decimal:
        return (numerator / denominator).quantize(RATIO_PLACES, rounding=ROUND_HALF_UP)

    @staticmethod
    def _average(values: list[Decimal]) -> Decimal:
        return (sum_money(values) / Decimal(len(values))).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP
        )

    @staticmethod
    def _valid_evidence(evidence: EvidenceReference | None) -> bool:
        return evidence is not None and evidence.synthetic

    def _usable(
        self,
        item: FinancialValueInput,
        verification_status: VerificationStatus,
    ) -> bool:
        return (
            item.verification_status == verification_status
            and self._valid_evidence(item.evidence)
        )

    @staticmethod
    def _metric_evidence(input_id: str, evidence: EvidenceReference) -> MetricEvidence:
        return MetricEvidence(input_id=input_id, evidence=evidence)

    def _scope_reasons(self, request: FinancialReadinessRequest) -> list[RiskReviewReason]:
        mismatches: list[str] = []
        if request.program_id != self._policy.program_id:
            mismatches.append(f"program must be {self._policy.program_id}")
        if request.rule_year != self._policy.rule_year:
            mismatches.append(f"rule year must be {self._policy.rule_year}")
        if request.area != self._policy.area:
            mismatches.append(f"area must be {self._policy.area}")
        if not mismatches:
            return []
        return [
            RiskReviewReason(
                code=RiskReasonCode.SCOPE_NOT_SUPPORTED,
                message="; ".join(mismatches) + ".",
            )
        ]

    def _income_scenarios(
        self, request: FinancialReadinessRequest
    ) -> tuple[IncomeConfidenceScenario, list[MetricEvidence], list[RiskReviewReason]]:
        confirmed: list[Decimal] = []
        provisional: list[Decimal] = []
        evidence: list[MetricEvidence] = []
        reasons: list[RiskReviewReason] = []

        for source in request.income_sources:
            if not source.recurring:
                continue
            if self._usable(source, VerificationStatus.CONFIRMED):
                confirmed.append(money(source.amount))
                assert source.evidence is not None
                evidence.append(self._metric_evidence(source.value_id, source.evidence))
            elif self._usable(source, VerificationStatus.PROVISIONAL):
                provisional.append(money(source.amount))
                assert source.evidence is not None
                evidence.append(self._metric_evidence(source.value_id, source.evidence))
                reasons.append(
                    RiskReviewReason(
                        code=RiskReasonCode.PROVISIONAL_INPUT_REQUIRES_CONFIRMATION,
                        message="Provisional income is shown only in the potential scenario.",
                        input_id=source.value_id,
                    )
                )
            elif source.verification_status == VerificationStatus.UNVERIFIED:
                reasons.append(
                    RiskReviewReason(
                        code=RiskReasonCode.UNVERIFIED_INPUT_EXCLUDED,
                        message="Unverified income is excluded from all calculations.",
                        input_id=source.value_id,
                    )
                )
            else:
                reasons.append(
                    RiskReviewReason(
                        code=RiskReasonCode.MISSING_OR_INVALID_EVIDENCE,
                        message="Confirmed or provisional income requires synthetic source evidence.",
                        input_id=source.value_id,
                    )
                )

        confirmed_total = sum_money(confirmed)
        provisional_total = sum_money(provisional)
        return (
            IncomeConfidenceScenario(
                confirmed_monthly_income=confirmed_total,
                potential_verified_monthly_income=sum_money(
                    [confirmed_total, provisional_total]
                ),
                provisional_amount_excluded_from_confirmed=provisional_total,
            ),
            evidence,
            reasons,
        )

    def _verified_income_metric(
        self,
        scenarios: IncomeConfidenceScenario,
        evidence: list[MetricEvidence],
        reasons: list[RiskReviewReason],
    ) -> FinancialMetricResult:
        no_confirmed_income = scenarios.confirmed_monthly_income <= 0
        if no_confirmed_income:
            reasons = [
                *reasons,
                RiskReviewReason(
                    code=RiskReasonCode.NO_CONFIRMED_INCOME,
                    message="No positive recurring monthly income is confirmed and traceable.",
                ),
            ]
            status = MetricStatus.INSUFFICIENT_EVIDENCE
            interpretation = "Verified monthly income cannot be calculated from current evidence."
            value: Decimal | None = None
        elif reasons:
            status = MetricStatus.NEEDS_REVIEW
            interpretation = (
                "Confirmed income is calculated separately from additional income that still "
                "requires renter confirmation."
            )
            value = scenarios.confirmed_monthly_income
        else:
            status = MetricStatus.CALCULATED
            interpretation = (
                "Recurring monthly income is confirmed, traceable, and calculated. "
                "This describes the metric only, not an applicant outcome."
            )
            value = scenarios.confirmed_monthly_income

        return FinancialMetricResult(
            rule_id=MetricId.VERIFIED_MONTHLY_INCOME,
            status=status,
            value=value,
            unit="USD/month",
            interpretation=interpretation,
            formula="sum(confirmed recurring monthly income sources)",
            threshold=None,
            threshold_source="evidence_status_only_no_acceptance_threshold",
            requires_human_confirmation=status != MetricStatus.CALCULATED,
            details=[
                MetricDetail(
                    key="confirmed_monthly_income",
                    label="Confirmed monthly income",
                    value=scenarios.confirmed_monthly_income,
                    unit="USD/month",
                ),
                MetricDetail(
                    key="potential_verified_monthly_income",
                    label="Potential verified monthly income",
                    value=scenarios.potential_verified_monthly_income,
                    unit="USD/month",
                ),
            ],
            evidence=evidence,
            citations=[],
            review_reasons=reasons,
        )

    def _housing_costs(
        self, request: FinancialReadinessRequest
    ) -> tuple[Decimal | None, list[MetricEvidence], list[RiskReviewReason]]:
        reasons: list[RiskReviewReason] = []
        evidence: list[MetricEvidence] = []
        amounts: list[Decimal] = []

        if not request.housing_costs_complete:
            reasons.append(
                RiskReviewReason(
                    code=RiskReasonCode.HOUSING_COSTS_INCOMPLETE,
                    message="Rent and recurring utility inputs are not confirmed complete.",
                )
            )
        if request.rent is None or not self._usable(
            request.rent, VerificationStatus.CONFIRMED
        ):
            reasons.append(
                RiskReviewReason(
                    code=RiskReasonCode.MISSING_OR_INVALID_EVIDENCE,
                    message="Confirmed rent with synthetic source evidence is required.",
                    input_id=request.rent.value_id if request.rent else None,
                )
            )
        else:
            amounts.append(money(request.rent.amount))
            assert request.rent.evidence is not None
            evidence.append(self._metric_evidence(request.rent.value_id, request.rent.evidence))

        for utility in request.recurring_utilities:
            if self._usable(utility, VerificationStatus.CONFIRMED):
                amounts.append(money(utility.amount))
                assert utility.evidence is not None
                evidence.append(self._metric_evidence(utility.value_id, utility.evidence))
            else:
                reasons.append(
                    RiskReviewReason(
                        code=RiskReasonCode.MISSING_OR_INVALID_EVIDENCE,
                        message="Recurring utilities must be confirmed and traceable.",
                        input_id=utility.value_id,
                    )
                )

        total = sum_money(amounts) if not reasons else None
        if total is not None and total <= 0:
            reasons.append(
                RiskReviewReason(
                    code=RiskReasonCode.ZERO_HOUSING_COST,
                    message="Housing-cost ratios require positive monthly housing cost.",
                )
            )
            total = None
        return total, evidence, reasons

    def _housing_burden_metric(
        self,
        confirmed_income: Decimal,
        income_evidence: list[MetricEvidence],
        housing_costs: Decimal | None,
        housing_evidence: list[MetricEvidence],
        housing_reasons: list[RiskReviewReason],
    ) -> FinancialMetricResult:
        reasons = list(housing_reasons)
        if confirmed_income <= 0:
            reasons.append(
                RiskReviewReason(
                    code=RiskReasonCode.NO_CONFIRMED_INCOME,
                    message="Housing burden requires positive confirmed monthly income.",
                )
            )
        if reasons or housing_costs is None:
            return self._abstained_metric(
                MetricId.HOUSING_COST_BURDEN,
                "Housing-cost burden cannot be calculated from complete confirmed inputs.",
                "(rent + recurring utilities) / confirmed gross monthly income",
                self._policy.housing_burden.threshold_source,
                reasons,
                [*income_evidence, *housing_evidence],
                [self._citations[self._policy.housing_burden.citation_id]],
            )

        ratio = self._ratio(housing_costs, confirmed_income)
        if ratio <= self._policy.housing_burden.lower_burden_max:
            band = "lower_burden"
            status = MetricStatus.CALCULATED
        elif ratio <= self._policy.housing_burden.elevated_burden_max:
            band = "elevated_burden"
            status = MetricStatus.NEEDS_REVIEW
        else:
            band = "severe_burden"
            status = MetricStatus.NEEDS_REVIEW

        return FinancialMetricResult(
            rule_id=MetricId.HOUSING_COST_BURDEN,
            status=status,
            value=ratio,
            unit="ratio",
            interpretation=(
                f"HUD's descriptive housing-cost category is {band.replace('_', ' ')}. "
                "This is not a rental acceptance rule."
            ),
            formula=(
                f"{format_money(housing_costs)} / {format_money(confirmed_income)} "
                f"= {ratio}"
            ),
            threshold=self._policy.housing_burden.lower_burden_max,
            threshold_source=self._policy.housing_burden.threshold_source,
            requires_human_confirmation=status == MetricStatus.NEEDS_REVIEW,
            details=[
                MetricDetail(
                    key="housing_burden_band",
                    label="HUD descriptive burden band",
                    text=band,
                ),
                MetricDetail(
                    key="monthly_housing_costs",
                    label="Confirmed rent plus recurring utilities",
                    value=housing_costs,
                    unit="USD/month",
                ),
                MetricDetail(
                    key="severe_burden_boundary",
                    label="HUD descriptive severe-burden boundary",
                    value=self._policy.housing_burden.elevated_burden_max,
                    unit="ratio",
                ),
            ],
            evidence=[*income_evidence, *housing_evidence],
            citations=[self._citations[self._policy.housing_burden.citation_id]],
            review_reasons=reasons,
        )

    def _income_stability_metric(
        self, request: FinancialReadinessRequest
    ) -> FinancialMetricResult:
        usable = [
            point
            for point in request.monthly_income_history
            if point.verification_status == VerificationStatus.CONFIRMED
            and self._valid_evidence(point.evidence)
        ]
        usable.sort(key=lambda point: point.month)
        evidence = [
            self._metric_evidence(point.month, point.evidence)
            for point in usable
            if point.evidence is not None
        ]
        minimum = self._policy.income_stability.minimum_observed_months
        if len(usable) < minimum:
            reason = RiskReviewReason(
                code=RiskReasonCode.INSUFFICIENT_INCOME_HISTORY,
                message=f"At least {minimum} confirmed monthly observations are required.",
            )
            return self._abstained_metric(
                MetricId.INCOME_STABILITY,
                "Income stability is not inferred from insufficient history.",
                "population standard deviation / mean monthly income",
                self._policy.income_stability.threshold_source,
                [reason],
                evidence,
                [],
            )

        amounts = [money(point.amount) for point in usable]
        mean = self._average(amounts)
        if mean <= 0:
            reason = RiskReviewReason(
                code=RiskReasonCode.ZERO_MEAN_INCOME,
                message="Coefficient of variation requires positive mean income.",
            )
            return self._abstained_metric(
                MetricId.INCOME_STABILITY,
                "Income stability cannot be calculated with zero mean income.",
                "population standard deviation / mean monthly income",
                self._policy.income_stability.threshold_source,
                [reason],
                evidence,
                [],
            )

        variance = sum((amount - mean) ** 2 for amount in amounts) / Decimal(len(amounts))
        standard_deviation = variance.sqrt().quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        cv = self._ratio(standard_deviation, mean)
        ordered = sorted(amounts)
        middle = len(ordered) // 2
        median = (
            ordered[middle]
            if len(ordered) % 2
            else self._average([ordered[middle - 1], ordered[middle]])
        )
        recent_count = min(self._policy.income_stability.recent_average_months, len(amounts))
        recent_average = self._average(amounts[-recent_count:])
        decreases = [
            max(previous - current, Decimal("0.00"))
            for previous, current in zip(amounts, amounts[1:])
        ]
        largest_decrease = max(decreases, default=Decimal("0.00"))
        x_values = [Decimal(index) for index in range(len(amounts))]
        x_mean = sum(x_values) / Decimal(len(x_values))
        numerator = sum(
            (x_value - x_mean) * (amount - mean)
            for x_value, amount in zip(x_values, amounts)
        )
        denominator = sum((x_value - x_mean) ** 2 for x_value in x_values)
        monthly_trend = (
            (numerator / denominator).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
            if denominator
            else Decimal("0.00")
        )
        status = (
            MetricStatus.NEEDS_REVIEW
            if cv > self._policy.income_stability.cv_review_above
            else MetricStatus.CALCULATED
        )
        interpretation = (
            "Income varies above the configured advisory CV threshold and should be reviewed."
            if status == MetricStatus.NEEDS_REVIEW
            else "Observed income variation is within the configured advisory CV range."
        )
        return FinancialMetricResult(
            rule_id=MetricId.INCOME_STABILITY,
            status=status,
            value=cv,
            unit="coefficient_of_variation",
            interpretation=interpretation + " This threshold is internal policy, not law.",
            formula=f"{standard_deviation} / {mean} = {cv}",
            threshold=self._policy.income_stability.cv_review_above,
            threshold_source=self._policy.income_stability.threshold_source,
            requires_human_confirmation=status == MetricStatus.NEEDS_REVIEW,
            details=[
                MetricDetail(key="observed_months", label="Observed months", value=Decimal(len(amounts)), unit="months"),
                MetricDetail(key="mean_monthly_income", label="Mean monthly income", value=mean, unit="USD/month"),
                MetricDetail(key="median_monthly_income", label="Median monthly income", value=median, unit="USD/month"),
                MetricDetail(key="lowest_observed_month", label="Lowest observed month", value=min(amounts), unit="USD/month"),
                MetricDetail(key="recent_average", label=f"Recent {recent_count}-month average", value=recent_average, unit="USD/month"),
                MetricDetail(key="largest_monthly_decrease", label="Largest month-to-month decrease", value=largest_decrease, unit="USD"),
                MetricDetail(key="monthly_trend_slope", label="Linear monthly trend", value=monthly_trend, unit="USD/month"),
            ],
            evidence=evidence,
            citations=[],
            review_reasons=[],
        )

    def _reserve_metric(
        self,
        request: FinancialReadinessRequest,
        housing_costs: Decimal | None,
        housing_evidence: list[MetricEvidence],
        housing_reasons: list[RiskReviewReason],
    ) -> FinancialMetricResult:
        confirmed: list[Decimal] = []
        provisional: list[Decimal] = []
        evidence = list(housing_evidence)
        reasons = list(housing_reasons)
        confirmed_entries = 0
        for asset in request.liquid_assets:
            if not asset.accessible:
                continue
            if self._usable(asset, VerificationStatus.CONFIRMED):
                confirmed_entries += 1
                confirmed.append(money(asset.amount))
                assert asset.evidence is not None
                evidence.append(self._metric_evidence(asset.value_id, asset.evidence))
            elif self._usable(asset, VerificationStatus.PROVISIONAL):
                provisional.append(money(asset.amount))
                assert asset.evidence is not None
                evidence.append(self._metric_evidence(asset.value_id, asset.evidence))
                reasons.append(
                    RiskReviewReason(
                        code=RiskReasonCode.PROVISIONAL_INPUT_REQUIRES_CONFIRMATION,
                        message="Provisional liquid funds are excluded from confirmed coverage.",
                        input_id=asset.value_id,
                    )
                )

        if confirmed_entries == 0:
            reasons.append(
                RiskReviewReason(
                    code=RiskReasonCode.NO_CONFIRMED_ACCESSIBLE_RESERVES,
                    message="No accessible liquid-fund entry is confirmed and traceable.",
                )
            )
        if housing_reasons or housing_costs is None or confirmed_entries == 0:
            return self._abstained_metric(
                MetricId.LIQUID_RESERVE_COVERAGE,
                "Liquid-reserve coverage cannot be calculated from confirmed accessible funds.",
                "confirmed accessible liquid funds / monthly housing costs",
                self._policy.reserve_coverage.threshold_source,
                reasons,
                evidence,
                [],
            )

        confirmed_total = sum_money(confirmed)
        provisional_total = sum_money(provisional)
        coverage = self._ratio(confirmed_total, housing_costs)
        status = (
            MetricStatus.NEEDS_REVIEW
            if provisional_total > 0
            else MetricStatus.CALCULATED
        )
        return FinancialMetricResult(
            rule_id=MetricId.LIQUID_RESERVE_COVERAGE,
            status=status,
            value=coverage,
            unit="months_of_housing_cost",
            interpretation=(
                f"Confirmed accessible funds cover approximately {coverage} months of housing "
                "costs. No acceptance threshold is applied."
            ),
            formula=f"{format_money(confirmed_total)} / {format_money(housing_costs)} = {coverage}",
            threshold=None,
            threshold_source=self._policy.reserve_coverage.threshold_source,
            requires_human_confirmation=status == MetricStatus.NEEDS_REVIEW,
            details=[
                MetricDetail(key="confirmed_accessible_funds", label="Confirmed accessible liquid funds", value=confirmed_total, unit="USD"),
                MetricDetail(key="provisional_accessible_funds", label="Provisional accessible funds excluded", value=provisional_total, unit="USD"),
            ],
            evidence=evidence,
            citations=[],
            review_reasons=reasons,
        )

    def _stress_metric(
        self,
        request: FinancialReadinessRequest,
        confirmed_income: Decimal,
        income_evidence: list[MetricEvidence],
        housing_costs: Decimal | None,
        housing_evidence: list[MetricEvidence],
        housing_reasons: list[RiskReviewReason],
    ) -> FinancialMetricResult:
        reasons = list(housing_reasons)
        if confirmed_income <= 0:
            reasons.append(
                RiskReviewReason(
                    code=RiskReasonCode.NO_CONFIRMED_INCOME,
                    message="The stress test requires positive confirmed monthly income.",
                )
            )
        if reasons or housing_costs is None:
            return self._abstained_metric(
                MetricId.DOWNSIDE_AFFORDABILITY,
                "The downside scenario cannot be calculated from complete confirmed inputs.",
                "confirmed income x (1 - shock rate) / monthly housing costs",
                self._policy.stress_test.threshold_source,
                reasons,
                [*income_evidence, *housing_evidence],
                [],
            )

        scenario = request.stress_scenario
        shock_rate = (
            self._policy.stress_test.default_income_shock_rate
            if scenario.basis == StressBasis.POLICY_DEFAULT
            else scenario.shock_rate
        )
        assert shock_rate is not None
        stressed_income = money(confirmed_income * (Decimal("1") - shock_rate))
        coverage = self._ratio(stressed_income, housing_costs)
        status = (
            MetricStatus.NEEDS_REVIEW
            if coverage < self._policy.stress_test.coverage_review_below
            else MetricStatus.CALCULATED
        )
        return FinancialMetricResult(
            rule_id=MetricId.DOWNSIDE_AFFORDABILITY,
            status=status,
            value=coverage,
            unit="stress_coverage_multiple",
            interpretation=(
                "Configured downside coverage is below 1.0 and depends on optimistic income assumptions."
                if status == MetricStatus.NEEDS_REVIEW
                else "Confirmed income covers configured housing costs under the stated downside scenario."
            ) + " This is an advisory scenario, not an eligibility rule.",
            formula=(
                f"{format_money(confirmed_income)} x (1 - {shock_rate}) = "
                f"{format_money(stressed_income)}; {format_money(stressed_income)} / "
                f"{format_money(housing_costs)} = {coverage}"
            ),
            threshold=self._policy.stress_test.coverage_review_below,
            threshold_source=f"{self._policy.stress_test.threshold_source}:{scenario.basis.value}",
            requires_human_confirmation=status == MetricStatus.NEEDS_REVIEW,
            details=[
                MetricDetail(key="shock_rate", label="Configured income shock", value=shock_rate, unit="rate"),
                MetricDetail(key="stress_basis", label="Stress scenario basis", text=scenario.basis.value),
                MetricDetail(key="stressed_monthly_income", label="Stressed monthly income", value=stressed_income, unit="USD/month"),
            ],
            evidence=[*income_evidence, *housing_evidence],
            citations=[],
            review_reasons=[],
        )

    def _reconciliation_metric(
        self, request: FinancialReadinessRequest
    ) -> FinancialMetricResult:
        tolerance = self._policy.reconciliation.relative_difference_review_above
        comparable_differences: list[Decimal] = []
        details: list[MetricDetail] = []
        evidence: list[MetricEvidence] = []
        reasons: list[RiskReviewReason] = []
        any_review = False

        for fact in request.reconciliation_facts:
            observations = [
                observation
                for observation in fact.observations
                if self._usable(observation, VerificationStatus.CONFIRMED)
            ]
            for observation in observations:
                assert observation.evidence is not None
                evidence.append(self._metric_evidence(observation.value_id, observation.evidence))
            if len(observations) < 2:
                reasons.append(
                    RiskReviewReason(
                        code=RiskReasonCode.INSUFFICIENT_RECONCILIATION_EVIDENCE,
                        message=f"{fact.label} needs at least two confirmed document observations.",
                        input_id=fact.fact_id,
                    )
                )
                details.append(
                    MetricDetail(
                        key=f"{fact.fact_id}.status",
                        label=f"{fact.label} reconciliation status",
                        text="INSUFFICIENT_EVIDENCE",
                    )
                )
                continue
            amounts = [money(observation.amount) for observation in observations]
            largest = max(amounts)
            smallest = min(amounts)
            difference = (
                Decimal("0.0000")
                if largest == 0
                else self._ratio(largest - smallest, abs(largest))
            )
            comparable_differences.append(difference)
            fact_review = difference > tolerance
            any_review |= fact_review
            details.extend(
                [
                    MetricDetail(
                        key=f"{fact.fact_id}.relative_difference",
                        label=f"{fact.label} relative difference",
                        value=difference,
                        unit="ratio",
                    ),
                    MetricDetail(
                        key=f"{fact.fact_id}.status",
                        label=f"{fact.label} reconciliation status",
                        text="CONFLICTING_EVIDENCE" if fact_review else "CONSISTENT",
                    ),
                ]
            )

        if not comparable_differences:
            return self._abstained_metric(
                MetricId.CROSS_DOCUMENT_RECONCILIATION,
                "No financial fact has two confirmed document observations to compare.",
                "abs(max value - min value) / max(abs(values))",
                self._policy.reconciliation.threshold_source,
                reasons
                or [
                    RiskReviewReason(
                        code=RiskReasonCode.INSUFFICIENT_RECONCILIATION_EVIDENCE,
                        message="At least one comparable financial fact is required.",
                    )
                ],
                evidence,
                [],
                details=details,
            )

        maximum_difference = max(comparable_differences)
        status = (
            MetricStatus.NEEDS_REVIEW
            if any_review or reasons
            else MetricStatus.CALCULATED
        )
        return FinancialMetricResult(
            rule_id=MetricId.CROSS_DOCUMENT_RECONCILIATION,
            status=status,
            value=maximum_difference,
            unit="maximum_relative_difference",
            interpretation=(
                "One or more financial facts require source-level review."
                if status == MetricStatus.NEEDS_REVIEW
                else "Compared financial facts are within the configured reconciliation tolerance."
            ) + " Missing information is not treated as financial weakness.",
            formula="abs(max value - min value) / max(abs(values))",
            threshold=tolerance,
            threshold_source=self._policy.reconciliation.threshold_source,
            requires_human_confirmation=status == MetricStatus.NEEDS_REVIEW,
            details=details,
            evidence=evidence,
            citations=[],
            review_reasons=reasons,
        )

    def _abstained_metric(
        self,
        metric_id: MetricId,
        interpretation: str,
        formula: str | None,
        threshold_source: str,
        reasons: list[RiskReviewReason],
        evidence: list[MetricEvidence],
        citations: list[AdvisoryCitation],
        *,
        details: list[MetricDetail] | None = None,
    ) -> FinancialMetricResult:
        return FinancialMetricResult(
            rule_id=metric_id,
            status=MetricStatus.INSUFFICIENT_EVIDENCE,
            value=None,
            unit=None,
            interpretation=interpretation,
            formula=formula,
            threshold=None,
            threshold_source=threshold_source,
            requires_human_confirmation=True,
            details=details or [],
            evidence=evidence,
            citations=citations,
            review_reasons=reasons,
        )

    def _scope_abstentions(
        self, reasons: list[RiskReviewReason]
    ) -> list[FinancialMetricResult]:
        return [
            self._abstained_metric(
                metric_id,
                "Metric not calculated because the request is outside the frozen program scope.",
                None,
                "frozen_program_scope",
                reasons,
                [],
                [],
            )
            for metric_id in MetricId
        ]

    @staticmethod
    def _all_evidence(request: FinancialReadinessRequest) -> list[EvidenceReference]:
        evidence: list[EvidenceReference] = []
        values: list[FinancialValueInput] = [*request.income_sources]
        if request.rent is not None:
            values.append(request.rent)
        values.extend(request.recurring_utilities)
        values.extend(request.liquid_assets)
        for fact in request.reconciliation_facts:
            values.extend(fact.observations)
        evidence.extend(value.evidence for value in values if value.evidence is not None)
        evidence.extend(
            point.evidence
            for point in request.monthly_income_history
            if point.evidence is not None
        )
        return evidence

    def evaluate(self, request: FinancialReadinessRequest) -> FinancialReadinessResponse:
        scope_reasons = self._scope_reasons(request)
        untrusted_ignored = any(
            evidence.untrusted_text_detected for evidence in self._all_evidence(request)
        )
        if scope_reasons:
            return FinancialReadinessResponse(
                household_id=request.household_id,
                scope_valid=False,
                policy=self.policy,
                income_scenarios=IncomeConfidenceScenario(
                    confirmed_monthly_income=Decimal("0.00"),
                    potential_verified_monthly_income=Decimal("0.00"),
                    provisional_amount_excluded_from_confirmed=Decimal("0.00"),
                ),
                metrics=self._scope_abstentions(scope_reasons),
                governance_citations=list(self._citations.values()),
                untrusted_document_text_ignored=untrusted_ignored,
                decision_boundary=self._policy.decision_boundary,
                review_reasons=scope_reasons,
            )

        scenarios, income_evidence, income_reasons = self._income_scenarios(request)
        housing_costs, housing_evidence, housing_reasons = self._housing_costs(request)
        metrics = [
            self._verified_income_metric(
                scenarios, list(income_evidence), list(income_reasons)
            ),
            self._housing_burden_metric(
                scenarios.confirmed_monthly_income,
                income_evidence,
                housing_costs,
                housing_evidence,
                housing_reasons,
            ),
            self._income_stability_metric(request),
            self._reserve_metric(
                request, housing_costs, housing_evidence, housing_reasons
            ),
            self._stress_metric(
                request,
                scenarios.confirmed_monthly_income,
                income_evidence,
                housing_costs,
                housing_evidence,
                housing_reasons,
            ),
            self._reconciliation_metric(request),
        ]
        return FinancialReadinessResponse(
            household_id=request.household_id,
            scope_valid=True,
            policy=self.policy,
            income_scenarios=scenarios,
            metrics=metrics,
            governance_citations=list(self._citations.values()),
            untrusted_document_text_ignored=untrusted_ignored,
            decision_boundary=self._policy.decision_boundary,
            review_reasons=[],
        )
