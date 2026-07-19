from __future__ import annotations

import asyncio
import unittest
from datetime import date
from decimal import Decimal
from io import BytesIO
from pathlib import Path
from unittest.mock import patch

from fastapi import HTTPException, UploadFile

from backend.app.main import (
    app,
    create_session as create_session_endpoint,
    delete_session as delete_session_endpoint,
    evaluate_session as evaluate_session_endpoint,
    upload_document as upload_document_endpoint,
)
from backend.app.schemas.journey import (
    ChecklistStatus,
    ConfirmFieldsRequest,
    CreateSessionRequest,
    EvaluateSessionRequest,
    ExportPacketRequest,
    FieldAction,
    FieldDecision,
    RenterBudgetStageStatus,
)
from backend.app.schemas.profile import FieldName
from backend.app.services.journey import (
    ApplicationJourneyService,
    JourneyConsentError,
    REQUIRED_CONFIRMATIONS,
    SessionNotFoundError,
)
from backend.app.services.extractor import MAX_DOCUMENT_BYTES
from backend.run_synthetic_pipeline import run_pipeline


ROOT = Path(__file__).resolve().parents[2]
SAAD_DOCUMENTS = ROOT / "data" / "synthetic_docs" / "saad_extended" / "documents"
ORGANIZER_DOCUMENTS = (
    ROOT
    / "data"
    / "realdoor-hackathon-starter-pack"
    / "synthetic_documents"
    / "documents"
)


class JourneyTests(unittest.TestCase):
    @staticmethod
    def confirmation_decisions(extraction: object) -> list[FieldDecision]:
        required = REQUIRED_CONFIRMATIONS[extraction.document_type]
        available = extraction.field_map()
        return [
            FieldDecision(
                document_id=extraction.document_id,
                field_name=field_name,
                action=FieldAction.CONFIRM,
            )
            for field_name in sorted(required & available.keys(), key=lambda item: item.value)
        ]

    def test_complete_ephemeral_journey_corrects_exports_and_deletes(self) -> None:
        service = ApplicationJourneyService(renter_budget_enabled=False)
        created = service.create_session("SAAD-101")
        application = service.upload_document(
            created.session_id,
            (SAAD_DOCUMENTS / "saad-101_d01_application_summary.pdf").read_bytes(),
        )
        pay_stub = service.upload_document(
            created.session_id,
            (SAAD_DOCUMENTS / "saad-101_d02_pay_stub.pdf").read_bytes(),
        )
        self.assertFalse(application.raw_document_bytes_retained)
        self.assertFalse(pay_stub.raw_document_bytes_retained)

        decisions = [
            *self.confirmation_decisions(application.extraction),
            *self.confirmation_decisions(pay_stub.extraction),
        ]
        confirmed = service.confirm_fields(
            created.session_id,
            ConfirmFieldsRequest(
                consent_to_reuse_confirmed_values=True,
                decisions=decisions,
            ),
        )
        self.assertTrue(confirmed.consent_recorded)

        original = service.evaluate(
            created.session_id,
            EvaluateSessionRequest(
                as_of_date=date(2026, 7, 19),
                include_renter_budget=True,
            ),
        )
        self.assertEqual(
            original.rules_and_math.annualized_income,
            Decimal("53657.76"),
        )
        self.assertEqual(
            original.renter_budget.status,
            RenterBudgetStageStatus.DISABLED,
        )
        self.assertIn(
            ChecklistStatus.MISSING,
            {item.status for item in original.checklist.items},
        )

        corrected = service.confirm_fields(
            created.session_id,
            ConfirmFieldsRequest(
                consent_to_reuse_confirmed_values=True,
                decisions=[
                    FieldDecision(
                        document_id=pay_stub.extraction.document_id,
                        field_name=FieldName.GROSS_PAY,
                        action=FieldAction.CORRECT,
                        corrected_value=1000,
                    )
                ],
            ),
        )
        corrected_field = next(
            item
            for item in corrected.confirmed_fields
            if item.document_id == pay_stub.extraction.document_id
            and item.field_name is FieldName.GROSS_PAY
        )
        self.assertTrue(corrected_field.corrected_by_renter)

        recomputed = service.evaluate(
            created.session_id,
            EvaluateSessionRequest(as_of_date=date(2026, 7, 19)),
        )
        self.assertEqual(recomputed.rules_and_math.annualized_income, Decimal("52000.00"))
        self.assertNotEqual(
            original.rules_and_math.annualized_income,
            recomputed.rules_and_math.annualized_income,
        )

        packet = service.export_packet(
            created.session_id,
            ExportPacketRequest(
                renter_requested_export=True,
                as_of_date=date(2026, 7, 19),
            ),
        )
        self.assertTrue(packet.editable)
        self.assertTrue(packet.renter_controlled)
        self.assertTrue(packet.auto_send_disabled)
        self.assertTrue(all(not item.sensitive for item in packet.confirmed_profile))

        deleted = service.delete_session(created.session_id)
        self.assertTrue(deleted.deleted)
        self.assertFalse(deleted.raw_document_bytes_retained)
        self.assertFalse(deleted.extracted_state_retained)
        with self.assertRaises(SessionNotFoundError):
            service.evaluate(
                created.session_id,
                EvaluateSessionRequest(as_of_date=date(2026, 7, 19)),
            )

    def test_consent_is_required_before_reuse_or_export(self) -> None:
        service = ApplicationJourneyService()
        session = service.create_session("SAAD-101")
        upload = service.upload_document(
            session.session_id,
            (SAAD_DOCUMENTS / "saad-101_d01_application_summary.pdf").read_bytes(),
        )
        with self.assertRaises(JourneyConsentError):
            service.confirm_fields(
                session.session_id,
                ConfirmFieldsRequest(
                    consent_to_reuse_confirmed_values=False,
                    decisions=self.confirmation_decisions(upload.extraction),
                ),
            )
        with self.assertRaises(JourneyConsentError):
            service.export_packet(
                session.session_id,
                ExportPacketRequest(
                    renter_requested_export=False,
                    as_of_date=date(2026, 7, 19),
                ),
            )

    def test_organizer_expired_letter_is_flagged(self) -> None:
        service = ApplicationJourneyService()
        session = service.create_session("HH-005")
        decisions = []
        for file_name in (
            "hh-005_d01_application_summary.pdf",
            "hh-005_d02_pay_stub.pdf",
            "hh-005_d03_pay_stub.pdf",
            "hh-005_d04_employment_letter.pdf",
        ):
            upload = service.upload_document(
                session.session_id,
                (ORGANIZER_DOCUMENTS / file_name).read_bytes(),
            )
            decisions.extend(self.confirmation_decisions(upload.extraction))
        service.confirm_fields(
            session.session_id,
            ConfirmFieldsRequest(
                consent_to_reuse_confirmed_values=True,
                decisions=decisions,
            ),
        )
        result = service.evaluate(
            session.session_id,
            EvaluateSessionRequest(as_of_date=date(2026, 7, 19)),
        )
        employment = next(
            item
            for item in result.checklist.items
            if item.document_type == "employment_letter"
        )
        self.assertEqual(employment.status, ChecklistStatus.EXPIRED)
        self.assertGreater(employment.age_days, 60)

    def test_confirmed_employment_letter_is_used_when_pay_stub_is_unconfirmed(self) -> None:
        service = ApplicationJourneyService()
        session = service.create_session("HH-001")
        application = service.upload_document(
            session.session_id,
            (ORGANIZER_DOCUMENTS / "hh-001_d01_application_summary.pdf").read_bytes(),
        )
        service.upload_document(
            session.session_id,
            (ORGANIZER_DOCUMENTS / "hh-001_d02_pay_stub.pdf").read_bytes(),
        )
        employment = service.upload_document(
            session.session_id,
            (ORGANIZER_DOCUMENTS / "hh-001_d04_employment_letter.pdf").read_bytes(),
        )
        service.confirm_fields(
            session.session_id,
            ConfirmFieldsRequest(
                consent_to_reuse_confirmed_values=True,
                decisions=[
                    *self.confirmation_decisions(application.extraction),
                    *self.confirmation_decisions(employment.extraction),
                ],
            ),
        )
        result = service.evaluate(
            session.session_id,
            EvaluateSessionRequest(as_of_date=date(2026, 7, 19)),
        )
        self.assertIsNotNone(result.rules_and_math.annualized_income)
        self.assertEqual(len(result.rules_and_math.input_traces), 1)
        self.assertIn(
            employment.extraction.document_id,
            result.rules_and_math.input_traces[0].source_id,
        )

    def test_inconsistent_gig_values_abstain_instead_of_crashing(self) -> None:
        service = ApplicationJourneyService()
        session = service.create_session("HH-004")
        application = service.upload_document(
            session.session_id,
            (ORGANIZER_DOCUMENTS / "hh-004_d01_application_summary.pdf").read_bytes(),
        )
        gig = service.upload_document(
            session.session_id,
            (ORGANIZER_DOCUMENTS / "hh-004_d04_gig_statement.pdf").read_bytes(),
        )
        gig_decisions = self.confirmation_decisions(gig.extraction)
        gig_decisions = [
            decision.model_copy(
                update={"action": FieldAction.CORRECT, "corrected_value": 999999}
            )
            if decision.field_name is FieldName.PLATFORM_FEES
            else decision
            for decision in gig_decisions
        ]
        service.confirm_fields(
            session.session_id,
            ConfirmFieldsRequest(
                consent_to_reuse_confirmed_values=True,
                decisions=[
                    *self.confirmation_decisions(application.extraction),
                    *gig_decisions,
                ],
            ),
        )
        result = service.evaluate(
            session.session_id,
            EvaluateSessionRequest(as_of_date=date(2026, 7, 19)),
        )
        self.assertIsNone(result.rules_and_math.annualized_income)
        self.assertIn(
            "UNCERTAIN_INPUT",
            {reason.code.value for reason in result.rules_and_math.review_reasons},
        )

    def test_http_upload_and_deletion_contract(self) -> None:
        expected_routes = {
            "/sessions",
            "/sessions/{session_id}/documents",
            "/sessions/{session_id}/confirm",
            "/sessions/{session_id}/evaluate",
            "/sessions/{session_id}/export",
            "/sessions/{session_id}",
        }
        self.assertTrue(expected_routes <= {route.path for route in app.routes})
        created = create_session_endpoint(CreateSessionRequest(household_id="SAAD-HTTP"))
        session_id = created.session_id
        payload = (SAAD_DOCUMENTS / "saad-101_d01_application_summary.pdf").read_bytes()
        uploaded = asyncio.run(
            upload_document_endpoint(
                session_id,
                UploadFile(filename="application.pdf", file=BytesIO(payload)),
            )
        )
        self.assertFalse(uploaded.raw_document_bytes_retained)
        deleted = delete_session_endpoint(session_id)
        self.assertTrue(deleted.deleted)
        with self.assertRaises(HTTPException) as raised:
            evaluate_session_endpoint(
                session_id,
                EvaluateSessionRequest(as_of_date=date(2026, 7, 19)),
            )
        self.assertEqual(raised.exception.status_code, 404)

    def test_http_upload_read_is_bounded(self) -> None:
        class ObservedUpload:
            def __init__(self, payload: bytes) -> None:
                self.payload = payload
                self.requested_size: int | None = None

            async def read(self, size: int) -> bytes:
                self.requested_size = size
                return self.payload

        created = create_session_endpoint(CreateSessionRequest(household_id="SAAD-BOUND"))
        upload = ObservedUpload(
            (SAAD_DOCUMENTS / "saad-101_d01_application_summary.pdf").read_bytes()
        )
        asyncio.run(upload_document_endpoint(created.session_id, upload))  # type: ignore[arg-type]
        self.assertEqual(upload.requested_size, MAX_DOCUMENT_BYTES + 1)
        delete_session_endpoint(created.session_id)

    def test_inactive_session_expires_and_is_purged(self) -> None:
        with patch("backend.app.services.journey.monotonic", return_value=100.0):
            service = ApplicationJourneyService(session_ttl_seconds=30)
            created = service.create_session("SAAD-TTL")
        with patch("backend.app.services.journey.monotonic", return_value=131.0):
            with self.assertRaises(SessionNotFoundError):
                service.evaluate(
                    created.session_id,
                    EvaluateSessionRequest(as_of_date=date(2026, 7, 19)),
                )
        self.assertNotIn(created.session_id, service._sessions)

    def test_pipeline_regression_has_42_non_decisioning_budget_metrics(self) -> None:
        payload = run_pipeline()
        self.assertEqual(payload["summary"]["documents_processed"], 9)
        self.assertEqual(payload["summary"]["households_processed"], 7)
        self.assertEqual(
            payload["summary"]["documents_confirmed_against_synthetic_gold"],
            9,
        )
        self.assertEqual(payload["summary"]["ignored_embedded_instruction_flags"], 1)
        self.assertTrue(payload["summary"]["renter_budget_available"])
        metrics = [
            metric
            for household in payload["households"]
            for metric in household["renter_budget"]["response"]["metrics"]
        ]
        self.assertEqual(len(metrics), 42)
        self.assertTrue(
            all(
                metric["status"]
                in {"CALCULATED", "NEEDS_REVIEW", "INSUFFICIENT_EVIDENCE"}
                for metric in metrics
            )
        )

        def keys(value: object) -> set[str]:
            if isinstance(value, dict):
                return set(value) | set().union(*(keys(item) for item in value.values()))
            if isinstance(value, list):
                return set().union(*(keys(item) for item in value)) if value else set()
            return set()

        self.assertFalse(
            {"aggregate_score", "eligibility", "approved", "denied", "ranking"}
            & keys(payload)
        )


if __name__ == "__main__":
    unittest.main()
