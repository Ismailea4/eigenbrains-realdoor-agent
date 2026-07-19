from __future__ import annotations

import json
import unittest
from pathlib import Path

from backend.app.main import app, get_global_aggregate, get_reference_catalog
from backend.app.schemas.aggregate import (
    GlobalAggregateResponse,
    ReferenceReviewStatus,
    RenterBudgetBatchStatus,
)
from backend.app.services.extractor import extract_document
from backend.references_checker import (
    RULES_PATH,
    catalog_summary,
    load_rules,
    review_document,
)
from backend.run_synthetic_pipeline import OUTPUT_PATH, run_pipeline


ROOT = Path(__file__).resolve().parents[2]
DOCUMENTS = ROOT / "data" / "synthetic_docs" / "saad_extended" / "documents"


class ReferencesAndAggregateTests(unittest.TestCase):
    def test_supplied_catalog_is_validated_and_non_executable(self) -> None:
        rules = load_rules()
        summary = catalog_summary()
        self.assertEqual(len(rules), 25)
        self.assertEqual(summary.rules_loaded, 25)
        self.assertFalse(summary.authoritative_for_calculation)
        self.assertFalse(summary.runtime_rule_override_enabled)
        self.assertTrue(RULES_PATH.is_file())
        self.assertEqual(get_reference_catalog(), summary)

    def test_reference_matching_ignores_values_and_injection_text(self) -> None:
        extraction = extract_document(
            DOCUMENTS / "saad-104_d01_pay_stub_raster.pdf",
            enable_ocr=True,
        )
        review = review_document(extraction)
        self.assertEqual(review.status, ReferenceReviewStatus.MATCHES_FOUND)
        self.assertTrue(review.untrusted_document_text_ignored)
        self.assertFalse(review.external_research_used)
        self.assertFalse(review.extracted_values_sent_externally)

    def test_external_research_requires_configuration_and_explicit_consent(self) -> None:
        extraction = extract_document(
            DOCUMENTS / "saad-101_d01_application_summary.pdf",
            enable_ocr=True,
        )
        with self.assertRaises(PermissionError):
            review_document(
                extraction,
                use_external_research=True,
                consent_to_external_processing=False,
            )

    def test_global_endpoint_returns_one_validated_renter_budget_json(self) -> None:
        expected_routes = {"/references/catalog", "/pipeline/aggregate"}
        self.assertTrue(expected_routes <= {route.path for route in app.routes})
        payload = run_pipeline()
        aggregate = GlobalAggregateResponse.model_validate(payload)
        endpoint_result = get_global_aggregate()
        self.assertEqual(endpoint_result.summary.documents_processed, 9)
        self.assertEqual(aggregate.summary.households_processed, 7)
        self.assertEqual(aggregate.summary.reference_documents_reviewed, 9)
        self.assertEqual(aggregate.summary.supplemental_reference_rules_loaded, 25)
        self.assertTrue(aggregate.summary.renter_budget_available)
        self.assertEqual(aggregate.pipeline_variant, "rules_and_renter_budget")
        self.assertTrue(
            all(
                household.renter_budget.status
                is RenterBudgetBatchStatus.EVALUATED
                for household in aggregate.households
            )
        )
        self.assertNotIn("financial_readiness", json.dumps(payload))

    def test_checked_in_aggregate_artifact_matches_typed_contract(self) -> None:
        payload = json.loads(OUTPUT_PATH.read_text(encoding="utf-8"))
        aggregate = GlobalAggregateResponse.model_validate(payload)
        self.assertEqual(len(aggregate.documents), 9)
        self.assertEqual(len(aggregate.reference_review.reviews), 9)


if __name__ == "__main__":
    unittest.main()
