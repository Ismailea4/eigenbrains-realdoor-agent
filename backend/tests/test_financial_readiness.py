from __future__ import annotations

import json
import tempfile
import unittest
from decimal import Decimal
from pathlib import Path

from fastapi import HTTPException
from pydantic import ValidationError

from backend.app.main import (
    app,
    evaluate_renter_budget,
    get_renter_budget_policy,
    journey_service,
)
from backend.app.schemas.calculator import EvidenceReference
from backend.app.schemas.financial_readiness import (
    FinancialReadinessRequest,
    FinancialValueInput,
    LiquidAssetInput,
    MetricId,
    MetricStatus,
    MonthlyIncomeHistoryPoint,
    MonthlyIncomeInput,
    ReconciliationFactInput,
    ReconciliationObservation,
    RiskReasonCode,
    StressBasis,
    StressScenario,
    VerificationStatus,
)
from backend.app.services.financial_readiness import (
    EXPECTED_POLICY_SHA256,
    FinancialReadinessEngine,
    RiskPolicyIntegrityError,
)


ROOT = Path(__file__).resolve().parents[2]
POLICY_PATH = ROOT / "data" / "risk_management" / "advisory_policy.json"


class FinancialReadinessTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.engine = FinancialReadinessEngine()

    @staticmethod
    def evidence(
        document_id: str,
        field_name: str = "amount",
        *,
        synthetic: bool = True,
        untrusted_text_detected: bool = False,
    ) -> EvidenceReference:
        return EvidenceReference(
            source_document_id=document_id,
            field_name=field_name,
            page=1,
            source_box=(40, 400, 160, 420),
            page_width=612,
            page_height=792,
            synthetic=synthetic,
            untrusted_text_detected=untrusted_text_detected,
        )

    @classmethod
    def income(
        cls,
        value_id: str,
        amount: str,
        status: VerificationStatus = VerificationStatus.CONFIRMED,
        **overrides: object,
    ) -> MonthlyIncomeInput:
        values: dict[str, object] = {
            "value_id": value_id,
            "label": value_id,
            "amount": Decimal(amount),
            "verification_status": status,
            "evidence": cls.evidence(f"{value_id}-DOC", "monthly_income"),
            "source_type": "wages",
            "recurring": True,
        }
        values.update(overrides)
        return MonthlyIncomeInput(**values)

    @classmethod
    def financial_value(
        cls,
        value_id: str,
        amount: str,
        status: VerificationStatus = VerificationStatus.CONFIRMED,
        **overrides: object,
    ) -> FinancialValueInput:
        values: dict[str, object] = {
            "value_id": value_id,
            "label": value_id,
            "amount": Decimal(amount),
            "verification_status": status,
            "evidence": cls.evidence(f"{value_id}-DOC"),
        }
        values.update(overrides)
        return FinancialValueInput(**values)

    @classmethod
    def history(
        cls,
        month: str,
        amount: str,
        status: VerificationStatus = VerificationStatus.CONFIRMED,
    ) -> MonthlyIncomeHistoryPoint:
        return MonthlyIncomeHistoryPoint(
            month=month,
            amount=Decimal(amount),
            verification_status=status,
            evidence=cls.evidence(f"HISTORY-{month}"),
        )

    @classmethod
    def request(cls, **overrides: object) -> FinancialReadinessRequest:
        values: dict[str, object] = {
            "household_id": "HH-RISK-001",
            "program_id": "LIHTC_MTSP_60",
            "rule_year": 2026,
            "area": "Boston-Cambridge-Quincy, MA-NH HMFA",
            "income_sources": [cls.income("WAGES", "4100.00")],
            "monthly_income_history": [
                cls.history("2026-01", "3800.00"),
                cls.history("2026-02", "4100.00"),
                cls.history("2026-03", "4400.00"),
            ],
            "rent": cls.financial_value("RENT", "1200.00"),
            "recurring_utilities": [cls.financial_value("UTILITIES", "150.00")],
            "housing_costs_complete": True,
            "liquid_assets": [
                LiquidAssetInput(
                    **cls.financial_value("CHECKING", "5670.00").model_dump(),
                    asset_type="checking",
                    accessible=True,
                )
            ],
            "reconciliation_facts": [
                ReconciliationFactInput(
                    fact_id="MONTHLY_INCOME",
                    label="Monthly income",
                    observations=[
                        ReconciliationObservation(
                            **cls.financial_value("DECLARED", "4200.00").model_dump(),
                            document_role="application",
                        ),
                        ReconciliationObservation(
                            **cls.financial_value("PAY_STUB", "4165.00").model_dump(),
                            document_role="pay_stub",
                        ),
                    ],
                )
            ],
            "stress_scenario": StressScenario(),
        }
        values.update(overrides)
        return FinancialReadinessRequest(**values)

    @staticmethod
    def metrics_by_id(response: object) -> dict[MetricId, object]:
        return {metric.rule_id: metric for metric in response.metrics}

    def test_policy_is_versioned_advisory_only_and_scoring_disabled(self) -> None:
        policy = self.engine.policy
        self.assertEqual(policy.policy_version, "2026.07.19-v1")
        self.assertTrue(policy.advisory_only)
        self.assertFalse(policy.aggregate_score_enabled)
        self.assertEqual(policy.housing_lower_burden_max, Decimal("0.30"))
        self.assertEqual(policy.housing_elevated_burden_max, Decimal("0.50"))

    def test_six_mvp_metrics_are_exact_and_evidence_linked(self) -> None:
        response = self.engine.evaluate(self.request())
        metrics = self.metrics_by_id(response)
        self.assertEqual(set(metrics), set(MetricId))
        self.assertTrue(response.scope_valid)

        income = metrics[MetricId.VERIFIED_MONTHLY_INCOME]
        self.assertEqual(income.status, MetricStatus.CALCULATED)
        self.assertEqual(income.value, Decimal("4100.00"))

        burden = metrics[MetricId.HOUSING_COST_BURDEN]
        self.assertEqual(burden.status, MetricStatus.NEEDS_REVIEW)
        self.assertEqual(burden.value, Decimal("0.3293"))
        self.assertEqual(burden.citations[0].citation_id, "HUD-CHAS-COST-BURDEN")

        stability = metrics[MetricId.INCOME_STABILITY]
        self.assertEqual(stability.status, MetricStatus.CALCULATED)
        self.assertEqual(stability.value, Decimal("0.0597"))

        reserves = metrics[MetricId.LIQUID_RESERVE_COVERAGE]
        self.assertEqual(reserves.status, MetricStatus.CALCULATED)
        self.assertEqual(reserves.value, Decimal("4.2000"))

        stress = metrics[MetricId.DOWNSIDE_AFFORDABILITY]
        self.assertEqual(stress.status, MetricStatus.CALCULATED)
        self.assertEqual(stress.value, Decimal("2.5815"))

        reconciliation = metrics[MetricId.CROSS_DOCUMENT_RECONCILIATION]
        self.assertEqual(reconciliation.status, MetricStatus.CALCULATED)
        self.assertEqual(reconciliation.value, Decimal("0.0083"))
        self.assertTrue(all(metric.evidence for metric in metrics.values()))

    def test_confidence_aware_income_scenarios_do_not_multiply_by_ocr_confidence(self) -> None:
        request = self.request(
            income_sources=[
                self.income("CONFIRMED", "4000.00"),
                self.income("PROVISIONAL", "500.00", VerificationStatus.PROVISIONAL),
                self.income("UNVERIFIED", "900.00", VerificationStatus.UNVERIFIED, evidence=None),
            ]
        )
        response = self.engine.evaluate(request)
        income_metric = self.metrics_by_id(response)[MetricId.VERIFIED_MONTHLY_INCOME]
        self.assertEqual(response.income_scenarios.confirmed_monthly_income, Decimal("4000.00"))
        self.assertEqual(
            response.income_scenarios.potential_verified_monthly_income,
            Decimal("4500.00"),
        )
        self.assertEqual(income_metric.status, MetricStatus.NEEDS_REVIEW)
        self.assertNotEqual(response.income_scenarios.confirmed_monthly_income, Decimal("3200"))

    def test_missing_or_non_synthetic_income_evidence_causes_abstention(self) -> None:
        for evidence in (None, self.evidence("REAL", synthetic=False)):
            with self.subTest(evidence=evidence):
                source = self.income("WAGES", "4100.00", evidence=evidence)
                response = self.engine.evaluate(self.request(income_sources=[source]))
                metrics = self.metrics_by_id(response)
                self.assertEqual(
                    metrics[MetricId.VERIFIED_MONTHLY_INCOME].status,
                    MetricStatus.INSUFFICIENT_EVIDENCE,
                )
                self.assertEqual(
                    metrics[MetricId.HOUSING_COST_BURDEN].status,
                    MetricStatus.INSUFFICIENT_EVIDENCE,
                )
                self.assertEqual(
                    metrics[MetricId.DOWNSIDE_AFFORDABILITY].status,
                    MetricStatus.INSUFFICIENT_EVIDENCE,
                )

    def test_income_stability_abstains_on_short_history_and_reviews_volatility(self) -> None:
        short = self.engine.evaluate(
            self.request(
                monthly_income_history=[
                    self.history("2026-01", "4000"),
                    self.history("2026-02", "4100"),
                ]
            )
        )
        self.assertEqual(
            self.metrics_by_id(short)[MetricId.INCOME_STABILITY].status,
            MetricStatus.INSUFFICIENT_EVIDENCE,
        )

        volatile = self.engine.evaluate(
            self.request(
                monthly_income_history=[
                    self.history("2026-01", "1000"),
                    self.history("2026-02", "5000"),
                    self.history("2026-03", "1000"),
                ]
            )
        )
        metric = self.metrics_by_id(volatile)[MetricId.INCOME_STABILITY]
        self.assertEqual(metric.status, MetricStatus.NEEDS_REVIEW)
        self.assertGreater(metric.value, Decimal("0.30"))
        self.assertIn("not law", metric.interpretation)

    def test_reserves_include_only_confirmed_accessible_funds(self) -> None:
        inaccessible = LiquidAssetInput(
            **self.financial_value("RETIREMENT", "100000").model_dump(),
            asset_type="retirement",
            accessible=False,
        )
        confirmed = LiquidAssetInput(
            **self.financial_value("CHECKING", "5670").model_dump(),
            asset_type="checking",
            accessible=True,
        )
        response = self.engine.evaluate(
            self.request(liquid_assets=[inaccessible, confirmed])
        )
        metric = self.metrics_by_id(response)[MetricId.LIQUID_RESERVE_COVERAGE]
        self.assertEqual(metric.value, Decimal("4.2000"))

        no_accessible = self.engine.evaluate(self.request(liquid_assets=[inaccessible]))
        no_accessible_metric = self.metrics_by_id(no_accessible)[
            MetricId.LIQUID_RESERVE_COVERAGE
        ]
        self.assertEqual(
            no_accessible_metric.status,
            MetricStatus.INSUFFICIENT_EVIDENCE,
        )

    def test_custom_stress_scenario_is_visible_and_can_trigger_review(self) -> None:
        scenario = StressScenario(
            shock_rate=Decimal("0.80"),
            basis=StressBasis.RENTER_SELECTED_SCENARIO,
            description="Renter-selected severe downside scenario",
        )
        response = self.engine.evaluate(self.request(stress_scenario=scenario))
        metric = self.metrics_by_id(response)[MetricId.DOWNSIDE_AFFORDABILITY]
        self.assertEqual(metric.status, MetricStatus.NEEDS_REVIEW)
        self.assertEqual(metric.value, Decimal("0.6074"))
        self.assertIn("renter_selected_scenario", metric.threshold_source)
        self.assertIn("0.80", metric.formula)

    def test_reconciliation_reviews_conflicts_and_abstains_without_two_sources(self) -> None:
        conflicting_fact = ReconciliationFactInput(
            fact_id="INCOME",
            label="Monthly income",
            observations=[
                ReconciliationObservation(
                    **self.financial_value("A", "4200").model_dump(),
                    document_role="application",
                ),
                ReconciliationObservation(
                    **self.financial_value("B", "3000").model_dump(),
                    document_role="pay_stub",
                ),
            ],
        )
        conflicting = self.engine.evaluate(
            self.request(reconciliation_facts=[conflicting_fact])
        )
        metric = self.metrics_by_id(conflicting)[MetricId.CROSS_DOCUMENT_RECONCILIATION]
        self.assertEqual(metric.status, MetricStatus.NEEDS_REVIEW)
        self.assertEqual(metric.value, Decimal("0.2857"))

        single_fact = conflicting_fact.model_copy(
            update={"observations": [conflicting_fact.observations[0]]}
        )
        insufficient = self.engine.evaluate(
            self.request(reconciliation_facts=[single_fact])
        )
        insufficient_metric = self.metrics_by_id(insufficient)[
            MetricId.CROSS_DOCUMENT_RECONCILIATION
        ]
        self.assertEqual(
            insufficient_metric.status,
            MetricStatus.INSUFFICIENT_EVIDENCE,
        )

    def test_wrong_scope_abstains_all_metrics_without_calculating(self) -> None:
        response = self.engine.evaluate(self.request(rule_year=2025))
        self.assertFalse(response.scope_valid)
        self.assertTrue(
            all(
                metric.status == MetricStatus.INSUFFICIENT_EVIDENCE
                for metric in response.metrics
            )
        )
        self.assertTrue(all(metric.value is None for metric in response.metrics))
        self.assertIn(
            RiskReasonCode.SCOPE_NOT_SUPPORTED,
            {reason.code for reason in response.review_reasons},
        )

    def test_prompt_injection_flag_is_ignored_and_math_is_unchanged(self) -> None:
        injected_income = self.income(
            "WAGES",
            "4100",
            evidence=self.evidence("INJECTED", untrusted_text_detected=True),
        )
        response = self.engine.evaluate(self.request(income_sources=[injected_income]))
        self.assertTrue(response.untrusted_document_text_ignored)
        self.assertEqual(
            self.metrics_by_id(response)[MetricId.VERIFIED_MONTHLY_INCOME].value,
            Decimal("4100.00"),
        )

    def test_correction_propagates_to_burden_and_stress(self) -> None:
        original = self.engine.evaluate(self.request())
        corrected = self.engine.evaluate(
            self.request(income_sources=[self.income("WAGES", "4500")])
        )
        original_metrics = self.metrics_by_id(original)
        corrected_metrics = self.metrics_by_id(corrected)
        self.assertEqual(
            original_metrics[MetricId.HOUSING_COST_BURDEN].value,
            Decimal("0.3293"),
        )
        self.assertEqual(
            corrected_metrics[MetricId.HOUSING_COST_BURDEN].value,
            Decimal("0.3000"),
        )
        self.assertNotEqual(
            original_metrics[MetricId.DOWNSIDE_AFFORDABILITY].value,
            corrected_metrics[MetricId.DOWNSIDE_AFFORDABILITY].value,
        )

    def test_response_has_no_aggregate_score_or_decision_field(self) -> None:
        payload = self.engine.evaluate(self.request()).model_dump(mode="json")

        def collect_keys(value: object) -> set[str]:
            if isinstance(value, dict):
                return set(value) | set().union(*(collect_keys(item) for item in value.values()))
            if isinstance(value, list):
                return set().union(*(collect_keys(item) for item in value)) if value else set()
            return set()

        keys = collect_keys(payload)
        self.assertFalse(
            {"aggregate_score", "eligibility", "approved", "denied", "ranking"} & keys
        )
        self.assertFalse(payload["policy"]["aggregate_score_enabled"])

    def test_policy_checksum_is_pinned_and_tampering_fails_closed(self) -> None:
        import hashlib

        self.assertEqual(
            hashlib.sha256(POLICY_PATH.read_bytes()).hexdigest(),
            EXPECTED_POLICY_SHA256,
        )
        with tempfile.TemporaryDirectory(dir=ROOT) as temporary_directory:
            tampered = Path(temporary_directory) / "advisory_policy.json"
            raw = json.loads(POLICY_PATH.read_text(encoding="utf-8"))
            raw["stress_test"]["default_income_shock_rate"] = "0.99"
            tampered.write_text(json.dumps(raw), encoding="utf-8")
            with self.assertRaises(RiskPolicyIntegrityError):
                FinancialReadinessEngine(tampered)

    def test_api_routes_expose_typed_policy_and_evaluation(self) -> None:
        route_paths = {route.path for route in app.routes}
        self.assertTrue(
            {"/renter-budget/policy", "/renter-budget/evaluate"}
            <= route_paths
        )
        original = journey_service.renter_budget_enabled
        try:
            journey_service.renter_budget_enabled = False
            with self.assertRaises(HTTPException) as disabled:
                get_renter_budget_policy()
            self.assertEqual(disabled.exception.status_code, 404)

            journey_service.renter_budget_enabled = True
            self.assertFalse(get_renter_budget_policy().aggregate_score_enabled)
            response = evaluate_renter_budget(self.request())
            self.assertEqual(len(response.metrics), 6)
        finally:
            journey_service.renter_budget_enabled = original

    def test_duplicate_months_fail_schema_validation(self) -> None:
        duplicate = self.history("2026-01", "4000")
        with self.assertRaises(ValidationError):
            self.request(monthly_income_history=[duplicate, duplicate.model_copy()])


if __name__ == "__main__":
    unittest.main()
