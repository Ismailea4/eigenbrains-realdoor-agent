"""Ephemeral orchestration for RealDoor's renter-controlled backend journey."""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from pathlib import Path
from threading import RLock
from time import monotonic
from uuid import uuid4

from ..schemas.calculator import (
    ConfirmedIncomeInput,
    EvidenceReference,
    RulesEvaluationRequest,
    RulesEvaluationResponse,
)
from ..schemas.financial_readiness import (
    FinancialReadinessRequest,
    FinancialValueInput,
    LiquidAssetInput,
    MonthlyIncomeHistoryPoint,
    MonthlyIncomeInput,
    VerificationStatus,
)
from ..schemas.journey import (
    ApplicationReadinessPacket,
    AuditEvent,
    ChecklistItem,
    ChecklistResult,
    ChecklistStatus,
    ConfirmationResponse,
    ConfirmedProfileField,
    ConfirmFieldsRequest,
    CreateSessionResponse,
    DeleteSessionResponse,
    EvaluateSessionRequest,
    ExportPacketRequest,
    FieldAction,
    JourneyReadinessStatus,
    RenterBudgetStage,
    RenterBudgetStageStatus,
    SessionEvaluationResponse,
    SessionStatus,
    UploadDocumentResponse,
)
from ..schemas.profile import DocumentExtraction, DocumentType, FieldName
from .calculator import annualize
from .extractor import extract_document
from .financial_readiness import FinancialReadinessEngine
from .rules_engine import (
    EXPECTED_AMI_PERCENTAGE,
    EXPECTED_AREA,
    EXPECTED_PROGRAM_ID,
    EXPECTED_RULE_YEAR,
    RulesEngine,
)


REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
CHECKLIST_PATH = (
    REPOSITORY_ROOT
    / "data"
    / "realdoor-hackathon-starter-pack"
    / "evaluation"
    / "application_checklists.json"
)
CHECKLIST_VERSION = "REALDOOR-ORGANIZER-CHECKLIST-2026.07.18"
PACKET_VERSION = "REALDOOR-RENTER-PACKET-1.0"
RECENCY_WINDOW_DAYS = 60
DEFAULT_SESSION_TTL_SECONDS = 30 * 60
MONEY = Decimal("0.01")


class SessionNotFoundError(KeyError):
    """The requested ephemeral session does not exist or was deleted."""


class JourneyConflictError(ValueError):
    """The requested state transition conflicts with the current session."""


class JourneyConsentError(PermissionError):
    """Explicit renter consent is required for this action."""


@dataclass
class _SessionState:
    session_id: str
    household_id: str
    expires_at: float
    documents: dict[str, DocumentExtraction] = field(default_factory=dict)
    confirmed: dict[tuple[str, FieldName], ConfirmedProfileField] = field(
        default_factory=dict
    )
    consent_recorded: bool = False
    audit_events: list[AuditEvent] = field(default_factory=list)


REQUIRED_CONFIRMATIONS: dict[DocumentType, frozenset[FieldName]] = {
    DocumentType.APPLICATION_SUMMARY: frozenset(
        {FieldName.PERSON_NAME, FieldName.HOUSEHOLD_SIZE, FieldName.APPLICATION_DATE}
    ),
    DocumentType.PAY_STUB: frozenset(
        {
            FieldName.PERSON_NAME,
            FieldName.PAY_DATE,
            FieldName.PAY_FREQUENCY,
            FieldName.GROSS_PAY,
        }
    ),
    DocumentType.EMPLOYMENT_LETTER: frozenset(
        {
            FieldName.PERSON_NAME,
            FieldName.DOCUMENT_DATE,
            FieldName.WEEKLY_HOURS,
            FieldName.HOURLY_RATE,
        }
    ),
    DocumentType.BENEFIT_LETTER: frozenset(
        {
            FieldName.PERSON_NAME,
            FieldName.DOCUMENT_DATE,
            FieldName.MONTHLY_BENEFIT,
            FieldName.BENEFIT_FREQUENCY,
        }
    ),
    DocumentType.GIG_STATEMENT: frozenset(
        {
            FieldName.PERSON_NAME,
            FieldName.STATEMENT_MONTH,
            FieldName.GROSS_RECEIPTS,
            FieldName.PLATFORM_FEES,
        }
    ),
    DocumentType.RENT_STATEMENT: frozenset(
        {FieldName.PERSON_NAME, FieldName.STATEMENT_DATE, FieldName.MONTHLY_RENT}
    ),
    DocumentType.BANK_DEPOSIT_STATEMENT: frozenset(
        {
            FieldName.PERSON_NAME,
            FieldName.STATEMENT_PERIOD_END,
            FieldName.ENDING_BALANCE,
        }
    ),
    DocumentType.SELF_EMPLOYMENT_STATEMENT: frozenset(
        {
            FieldName.PERSON_NAME,
            FieldName.STATEMENT_MONTH,
            FieldName.NET_BUSINESS_INCOME,
        }
    ),
    DocumentType.GOVERNMENT_ID: frozenset(
        {FieldName.PERSON_NAME, FieldName.EXPIRATION_DATE}
    ),
}

DATE_FIELD_BY_TYPE: dict[DocumentType, FieldName] = {
    DocumentType.PAY_STUB: FieldName.PAY_DATE,
    DocumentType.EMPLOYMENT_LETTER: FieldName.DOCUMENT_DATE,
    DocumentType.BENEFIT_LETTER: FieldName.DOCUMENT_DATE,
    DocumentType.RENT_STATEMENT: FieldName.STATEMENT_DATE,
    DocumentType.BANK_DEPOSIT_STATEMENT: FieldName.STATEMENT_PERIOD_END,
}

NUMERIC_FIELDS = {
    FieldName.REGULAR_HOURS,
    FieldName.HOURLY_RATE,
    FieldName.GROSS_PAY,
    FieldName.NET_PAY,
    FieldName.YTD_GROSS_PAY,
    FieldName.WEEKLY_HOURS,
    FieldName.MONTHLY_BENEFIT,
    FieldName.GROSS_RECEIPTS,
    FieldName.PLATFORM_FEES,
    FieldName.MONTHLY_RENT,
    FieldName.CURRENT_BALANCE,
    FieldName.TOTAL_DEPOSITS,
    FieldName.BUSINESS_EXPENSES,
    FieldName.NET_BUSINESS_INCOME,
    FieldName.ENDING_BALANCE,
}
DATE_FIELDS = {
    FieldName.APPLICATION_DATE,
    FieldName.PAY_DATE,
    FieldName.PAY_PERIOD_START,
    FieldName.PAY_PERIOD_END,
    FieldName.DOCUMENT_DATE,
    FieldName.STATEMENT_DATE,
    FieldName.LEASE_START_DATE,
    FieldName.LEASE_END_DATE,
    FieldName.STATEMENT_PERIOD_START,
    FieldName.STATEMENT_PERIOD_END,
    FieldName.DATE_OF_BIRTH,
    FieldName.EXPIRATION_DATE,
}


class ApplicationJourneyService:
    """Coordinate one stateless-calculation journey with ephemeral session state."""

    def __init__(
        self,
        *,
        renter_budget_enabled: bool | None = None,
        session_ttl_seconds: int = DEFAULT_SESSION_TTL_SECONDS,
        rules_engine: RulesEngine | None = None,
        renter_budget_engine: FinancialReadinessEngine | None = None,
    ) -> None:
        self.rules_engine = rules_engine or RulesEngine()
        self.renter_budget_engine = renter_budget_engine or FinancialReadinessEngine()
        self.renter_budget_enabled = (
            os.getenv("REALDOOR_RENTER_BUDGET_ENABLED", "true").casefold() == "true"
            if renter_budget_enabled is None
            else renter_budget_enabled
        )
        if session_ttl_seconds <= 0:
            raise ValueError("session_ttl_seconds must be positive")
        self.session_ttl_seconds = session_ttl_seconds
        self._sessions: dict[str, _SessionState] = {}
        self._lock = RLock()
        self._checklists = self._load_checklists()

    @staticmethod
    def _load_checklists() -> dict[str, dict[str, object]]:
        rows = json.loads(CHECKLIST_PATH.read_text(encoding="utf-8"))
        if not isinstance(rows, list):
            raise RuntimeError("Organizer checklist must be a JSON list")
        return {str(row["household_id"]): row for row in rows}

    def _state(self, session_id: str) -> _SessionState:
        try:
            state = self._sessions[session_id]
        except KeyError as exc:
            raise SessionNotFoundError(session_id) from exc
        if state.expires_at <= monotonic():
            del self._sessions[session_id]
            raise SessionNotFoundError(session_id)
        state.expires_at = monotonic() + self.session_ttl_seconds
        return state

    def _purge_expired(self) -> None:
        now = monotonic()
        expired = [
            session_id
            for session_id, state in self._sessions.items()
            if state.expires_at <= now
        ]
        for session_id in expired:
            del self._sessions[session_id]

    @staticmethod
    def _record(
        state: _SessionState,
        action: str,
        *,
        document_id: str | None = None,
        field_name: FieldName | None = None,
        rule_version: str | None = None,
        budget_version: str | None = None,
    ) -> None:
        state.audit_events.append(
            AuditEvent(
                sequence=len(state.audit_events) + 1,
                action=action,
                document_id=document_id,
                field_name=field_name,
                rule_corpus_version=rule_version,
                renter_budget_policy_version=budget_version,
            )
        )

    def create_session(self, household_id: str) -> CreateSessionResponse:
        session_id = str(uuid4())
        with self._lock:
            self._purge_expired()
            state = _SessionState(
                session_id=session_id,
                household_id=household_id,
                expires_at=monotonic() + self.session_ttl_seconds,
            )
            self._record(state, "SESSION_CREATED")
            self._sessions[session_id] = state
        return CreateSessionResponse(
            session_id=session_id,
            household_id=household_id,
            status=SessionStatus.ACTIVE,
            raw_document_bytes_retained=False,
        )

    def upload_document(self, session_id: str, payload: bytes) -> UploadDocumentResponse:
        extraction = extract_document(payload, enable_ocr=True)
        with self._lock:
            state = self._state(session_id)
            if extraction.document_id in state.documents:
                raise JourneyConflictError(
                    f"Document {extraction.document_id} is already in this session"
                )
            state.documents[extraction.document_id] = extraction
            self._record(state, "DOCUMENT_EXTRACTED", document_id=extraction.document_id)
        return UploadDocumentResponse(
            session_id=session_id,
            extraction=extraction,
            confirmation_required=True,
            raw_document_bytes_retained=False,
            data_use=(
                "The PDF bytes were processed in memory and discarded. Proposed fields "
                "cannot be reused until the renter confirms or corrects them."
            ),
        )

    @staticmethod
    def _normalize_value(field_name: FieldName, value: object) -> str | int | float:
        if field_name is FieldName.HOUSEHOLD_SIZE:
            try:
                normalized = int(str(value))
            except ValueError as exc:
                raise JourneyConflictError("household_size must be an integer") from exc
            if not 1 <= normalized <= 20:
                raise JourneyConflictError("household_size must be between 1 and 20")
            return normalized
        if field_name in NUMERIC_FIELDS:
            try:
                normalized_decimal = Decimal(str(value))
            except (InvalidOperation, ValueError) as exc:
                raise JourneyConflictError(f"{field_name.value} must be numeric") from exc
            if not normalized_decimal.is_finite() or normalized_decimal < 0:
                raise JourneyConflictError(
                    f"{field_name.value} must be finite and non-negative"
                )
            rounded = normalized_decimal.quantize(MONEY, rounding=ROUND_HALF_UP)
            return int(rounded) if rounded == rounded.to_integral_value() else float(rounded)
        if field_name in DATE_FIELDS:
            try:
                return date.fromisoformat(str(value)).isoformat()
            except ValueError as exc:
                raise JourneyConflictError(
                    f"{field_name.value} must use YYYY-MM-DD"
                ) from exc
        if field_name is FieldName.STATEMENT_MONTH:
            normalized_month = str(value)
            if not re.fullmatch(r"\d{4}-(0[1-9]|1[0-2])", normalized_month):
                raise JourneyConflictError("statement_month must use YYYY-MM")
            return normalized_month
        if field_name in {FieldName.PAY_FREQUENCY, FieldName.BENEFIT_FREQUENCY}:
            normalized_frequency = re.sub(r"[^a-z]", "", str(value).casefold())
            if normalized_frequency not in {
                "weekly",
                "biweekly",
                "semimonthly",
                "monthly",
                "annual",
            }:
                raise JourneyConflictError("Unsupported payment frequency")
            return normalized_frequency
        normalized_text = str(value).strip()
        if not normalized_text:
            raise JourneyConflictError(f"{field_name.value} cannot be empty")
        return normalized_text

    def confirm_fields(
        self,
        session_id: str,
        request: ConfirmFieldsRequest,
    ) -> ConfirmationResponse:
        if not request.consent_to_reuse_confirmed_values:
            raise JourneyConsentError("Explicit consent is required before field reuse")
        with self._lock:
            state = self._state(session_id)
            pending: list[ConfirmedProfileField] = []
            seen: set[tuple[str, FieldName]] = set()
            for decision in request.decisions:
                key = (decision.document_id, decision.field_name)
                if key in seen:
                    raise JourneyConflictError(
                        "Each document field may be decided once per request"
                    )
                seen.add(key)
                document = state.documents.get(decision.document_id)
                if document is None:
                    raise JourneyConflictError(f"Unknown document {decision.document_id}")
                proposed = document.field_map().get(decision.field_name)
                if proposed is None:
                    raise JourneyConflictError(
                        f"{decision.field_name.value} was not extracted from "
                        f"{decision.document_id}"
                    )
                value = (
                    proposed.value
                    if decision.action is FieldAction.CONFIRM
                    else decision.corrected_value
                )
                normalized = self._normalize_value(decision.field_name, value)
                pending.append(
                    ConfirmedProfileField(
                        document_id=decision.document_id,
                        field_name=decision.field_name,
                        proposed_value=proposed.value,
                        confirmed_value=normalized,
                        corrected_by_renter=decision.action is FieldAction.CORRECT,
                        evidence=proposed.evidence,
                        sensitive=proposed.sensitive,
                        reusable=not proposed.sensitive,
                    )
                )
            if not state.consent_recorded:
                state.consent_recorded = True
                self._record(state, "CONSENT_RECORDED")
            for item in pending:
                state.confirmed[(item.document_id, item.field_name)] = item
                self._record(
                    state,
                    "FIELD_CORRECTED" if item.corrected_by_renter else "FIELD_CONFIRMED",
                    document_id=item.document_id,
                    field_name=item.field_name,
                )
            return ConfirmationResponse(
                session_id=session_id,
                consent_recorded=state.consent_recorded,
                confirmed_fields=sorted(
                    state.confirmed.values(),
                    key=lambda item: (item.document_id, item.field_name.value),
                ),
                recalculation_required=True,
                audit_events=list(state.audit_events),
            )

    @staticmethod
    def _confirmed(
        state: _SessionState,
        document_id: str,
        field_name: FieldName,
    ) -> ConfirmedProfileField | None:
        return state.confirmed.get((document_id, field_name))

    @staticmethod
    def _evidence(
        document: DocumentExtraction,
        field: ConfirmedProfileField,
    ) -> EvidenceReference:
        width, height = document.page_size_points
        return EvidenceReference(
            source_document_id=document.document_id,
            field_name=field.field_name.value,
            page=field.evidence.page,
            source_box=tuple(Decimal(str(value)) for value in field.evidence.bbox),
            page_width=Decimal(str(width)),
            page_height=Decimal(str(height)),
            synthetic=True,
            untrusted_text_detected=bool(document.security_flags),
        )

    def _rules_request(self, state: _SessionState) -> RulesEvaluationRequest:
        household_size = 0
        income_sources: list[ConfirmedIncomeInput] = []
        pay_stubs: list[DocumentExtraction] = []
        usable_pay_stub_selected = False
        for document in state.documents.values():
            if document.document_type is DocumentType.APPLICATION_SUMMARY:
                value = self._confirmed(state, document.document_id, FieldName.HOUSEHOLD_SIZE)
                if value is not None:
                    household_size = int(value.confirmed_value)
            if document.document_type is DocumentType.PAY_STUB:
                pay_stubs.append(document)

        if pay_stubs:
            usable = []
            for document in pay_stubs:
                gross = self._confirmed(state, document.document_id, FieldName.GROSS_PAY)
                frequency = self._confirmed(
                    state, document.document_id, FieldName.PAY_FREQUENCY
                )
                pay_date = self._confirmed(state, document.document_id, FieldName.PAY_DATE)
                if gross and frequency:
                    usable.append(
                        (
                            str(pay_date.confirmed_value) if pay_date else "",
                            document,
                            gross,
                            frequency,
                        )
                    )
            if usable:
                _, document, gross, frequency = max(usable, key=lambda item: item[0])
                income_sources.append(
                    ConfirmedIncomeInput(
                        source_id=f"{document.document_id}:gross_pay",
                        label="Latest confirmed recurring gross pay",
                        amount=Decimal(str(gross.confirmed_value)),
                        frequency=str(frequency.confirmed_value),
                        confirmed=True,
                        evidence=self._evidence(document, gross),
                    )
                )
                usable_pay_stub_selected = True

        for document in state.documents.values():
            if document.document_type is DocumentType.BENEFIT_LETTER:
                amount = self._confirmed(
                    state, document.document_id, FieldName.MONTHLY_BENEFIT
                )
                frequency = self._confirmed(
                    state, document.document_id, FieldName.BENEFIT_FREQUENCY
                )
                if amount and frequency:
                    income_sources.append(
                        ConfirmedIncomeInput(
                            source_id=f"{document.document_id}:monthly_benefit",
                            label="Confirmed recurring benefit",
                            amount=Decimal(str(amount.confirmed_value)),
                            frequency=str(frequency.confirmed_value),
                            confirmed=True,
                            evidence=self._evidence(document, amount),
                        )
                    )
            elif document.document_type is DocumentType.SELF_EMPLOYMENT_STATEMENT:
                amount = self._confirmed(
                    state, document.document_id, FieldName.NET_BUSINESS_INCOME
                )
                if amount:
                    income_sources.append(
                        ConfirmedIncomeInput(
                            source_id=f"{document.document_id}:net_business_income",
                            label="Confirmed monthly net business income",
                            amount=Decimal(str(amount.confirmed_value)),
                            frequency="monthly",
                            confirmed=True,
                            evidence=self._evidence(document, amount),
                        )
                    )
            elif document.document_type is DocumentType.GIG_STATEMENT:
                gross = self._confirmed(
                    state, document.document_id, FieldName.GROSS_RECEIPTS
                )
                fees = self._confirmed(
                    state, document.document_id, FieldName.PLATFORM_FEES
                )
                if gross and fees:
                    amount = Decimal(str(gross.confirmed_value)) - Decimal(
                        str(fees.confirmed_value)
                    )
                    inconsistent = amount < 0
                    income_sources.append(
                        ConfirmedIncomeInput(
                            source_id=f"{document.document_id}:net_gig_receipts",
                            label="Confirmed monthly gig receipts after platform fees",
                            amount=max(amount, Decimal("0.00")).quantize(MONEY),
                            frequency="monthly",
                            confirmed=True,
                            uncertain=inconsistent,
                            uncertainty_reason=(
                                "Confirmed platform fees exceed confirmed gross receipts; "
                                "the source values require renter review."
                                if inconsistent
                                else None
                            ),
                            evidence=self._evidence(document, gross),
                        )
                    )
            elif (
                document.document_type is DocumentType.EMPLOYMENT_LETTER
                and not usable_pay_stub_selected
            ):
                hours = self._confirmed(
                    state, document.document_id, FieldName.WEEKLY_HOURS
                )
                rate = self._confirmed(state, document.document_id, FieldName.HOURLY_RATE)
                if hours and rate:
                    amount = Decimal(str(hours.confirmed_value)) * Decimal(
                        str(rate.confirmed_value)
                    )
                    income_sources.append(
                        ConfirmedIncomeInput(
                            source_id=f"{document.document_id}:weekly_employment_income",
                            label="Confirmed weekly employment income",
                            amount=amount.quantize(MONEY),
                            frequency="weekly",
                            confirmed=True,
                            evidence=self._evidence(document, rate),
                        )
                    )

        return RulesEvaluationRequest(
            household_id=state.household_id,
            program_id=EXPECTED_PROGRAM_ID,
            rule_year=EXPECTED_RULE_YEAR,
            area=EXPECTED_AREA,
            ami_percentage=EXPECTED_AMI_PERCENTAGE,
            household_size=household_size,
            income_sources=income_sources,
        )

    def _required_document_types(self, state: _SessionState) -> list[str]:
        organizer = self._checklists.get(state.household_id)
        if organizer:
            return [str(item) for item in organizer["required_document_types"]]
        observed = {document.document_type for document in state.documents.values()}
        required = ["application_summary", "pay_stub", "employment_letter"]
        if DocumentType.BENEFIT_LETTER in observed:
            required.append("benefit_letter")
        if DocumentType.GIG_STATEMENT in observed:
            required.append("gig_income_corroboration")
        return required

    def _checklist(self, state: _SessionState, as_of_date: date) -> ChecklistResult:
        items: list[ChecklistItem] = []
        for required_type in self._required_document_types(state):
            if required_type == "gig_income_corroboration":
                matching = [
                    document
                    for document in state.documents.values()
                    if document.document_type
                    in {
                        DocumentType.BANK_DEPOSIT_STATEMENT,
                        DocumentType.SELF_EMPLOYMENT_STATEMENT,
                    }
                ]
            else:
                matching = [
                    document
                    for document in state.documents.values()
                    if document.document_type.value == required_type
                ]
            if not matching:
                items.append(
                    ChecklistItem(
                        document_type=required_type,
                        status=ChecklistStatus.MISSING,
                        document_ids=[],
                        message=f"Required item is missing: {required_type}.",
                    )
                )
                continue

            required_fields = set().union(
                *(
                    REQUIRED_CONFIRMATIONS.get(document.document_type, frozenset())
                    for document in matching
                )
            )
            confirmed_fields = {
                field_name
                for document in matching
                for document_id, field_name in state.confirmed
                if document_id == document.document_id
            }
            if not required_fields.issubset(confirmed_fields):
                items.append(
                    ChecklistItem(
                        document_type=required_type,
                        status=ChecklistStatus.NEEDS_CONFIRMATION,
                        document_ids=sorted(document.document_id for document in matching),
                        message=(
                            "The document is present, but required extracted values need "
                            "renter confirmation."
                        ),
                    )
                )
                continue

            observed_dates = []
            for document in matching:
                date_field = DATE_FIELD_BY_TYPE.get(document.document_type)
                confirmed_date = (
                    self._confirmed(state, document.document_id, date_field)
                    if date_field
                    else None
                )
                if confirmed_date:
                    observed_dates.append(date.fromisoformat(str(confirmed_date.confirmed_value)))
            latest = max(observed_dates) if observed_dates else None
            age = max(0, (as_of_date - latest).days) if latest else None
            if age is not None and age > RECENCY_WINDOW_DAYS:
                status = ChecklistStatus.EXPIRED
                message = (
                    f"The most recent confirmed document is {age} days old; the frozen "
                    f"hackathon recency convention is {RECENCY_WINDOW_DAYS} days."
                )
            else:
                status = ChecklistStatus.PRESENT
                message = "The required document is present and its key values are confirmed."
            items.append(
                ChecklistItem(
                    document_type=required_type,
                    status=status,
                    document_ids=sorted(document.document_id for document in matching),
                    message=message,
                    observed_date=latest,
                    age_days=age,
                )
            )
        overall = (
            JourneyReadinessStatus.READY_TO_REVIEW
            if all(item.status is ChecklistStatus.PRESENT for item in items)
            else JourneyReadinessStatus.NEEDS_REVIEW
        )
        return ChecklistResult(
            checklist_version=CHECKLIST_VERSION,
            source=(
                "Organizer application_checklists.json plus frozen 60-day "
                "simulation convention"
            ),
            as_of_date=as_of_date,
            recency_window_days=RECENCY_WINDOW_DAYS,
            status=overall,
            items=items,
        )

    def _budget_request(
        self,
        state: _SessionState,
        rules_request: RulesEvaluationRequest,
    ) -> FinancialReadinessRequest:
        incomes: list[MonthlyIncomeInput] = []
        history: list[MonthlyIncomeHistoryPoint] = []
        used_months: set[str] = set()
        for source in rules_request.income_sources:
            annualized, _ = annualize(source.amount, source.frequency)
            monthly = (annualized / Decimal("12")).quantize(MONEY, rounding=ROUND_HALF_UP)
            incomes.append(
                MonthlyIncomeInput(
                    value_id=source.source_id,
                    label=source.label,
                    amount=monthly,
                    verification_status=VerificationStatus.CONFIRMED,
                    evidence=source.evidence,
                    source_type="confirmed_document_income",
                    recurring=True,
                )
            )
            document_id = source.source_id.split(":", 1)[0]
            document = state.documents[document_id]
            month_field = None
            for candidate in (
                FieldName.PAY_DATE,
                FieldName.DOCUMENT_DATE,
                FieldName.STATEMENT_MONTH,
            ):
                value = self._confirmed(state, document_id, candidate)
                if value:
                    month_field = str(value.confirmed_value)[:7]
                    break
            if month_field and month_field not in used_months:
                used_months.add(month_field)
                history.append(
                    MonthlyIncomeHistoryPoint(
                        month=month_field,
                        amount=monthly,
                        verification_status=VerificationStatus.CONFIRMED,
                        evidence=source.evidence,
                    )
                )

        rent = None
        assets = []
        for document in state.documents.values():
            rent_field = self._confirmed(state, document.document_id, FieldName.MONTHLY_RENT)
            if rent_field:
                rent = FinancialValueInput(
                    value_id=f"{document.document_id}:monthly_rent",
                    label="Renter-confirmed monthly rent",
                    amount=Decimal(str(rent_field.confirmed_value)),
                    verification_status=VerificationStatus.CONFIRMED,
                    evidence=self._evidence(document, rent_field),
                )
            balance = self._confirmed(state, document.document_id, FieldName.ENDING_BALANCE)
            if balance:
                assets.append(
                    LiquidAssetInput(
                        value_id=f"{document.document_id}:ending_balance",
                        label="Renter-confirmed accessible bank balance",
                        amount=Decimal(str(balance.confirmed_value)),
                        verification_status=VerificationStatus.CONFIRMED,
                        evidence=self._evidence(document, balance),
                        asset_type="bank_deposit_account",
                        accessible=True,
                    )
                )
        return FinancialReadinessRequest(
            household_id=state.household_id,
            program_id=EXPECTED_PROGRAM_ID,
            rule_year=EXPECTED_RULE_YEAR,
            area=EXPECTED_AREA,
            income_sources=incomes,
            monthly_income_history=history,
            rent=rent,
            recurring_utilities=[],
            housing_costs_complete=False,
            liquid_assets=assets,
            reconciliation_facts=[],
        )

    def _renter_budget(
        self,
        state: _SessionState,
        requested: bool,
        rules_request: RulesEvaluationRequest,
    ) -> RenterBudgetStage:
        if not requested:
            return RenterBudgetStage(
                status=RenterBudgetStageStatus.NOT_REQUESTED,
                renter_controlled=True,
                provider_use_prohibited=True,
                message="The optional renter budgeting sandbox was not requested.",
            )
        if not self.renter_budget_enabled:
            return RenterBudgetStage(
                status=RenterBudgetStageStatus.DISABLED,
                renter_controlled=True,
                provider_use_prohibited=True,
                message="The optional renter budgeting sandbox is disabled by configuration.",
            )
        request = self._budget_request(state, rules_request)
        return RenterBudgetStage(
            status=RenterBudgetStageStatus.EVALUATED,
            renter_controlled=True,
            provider_use_prohibited=True,
            message=(
                "Descriptive renter-selected calculations only; results cannot be used "
                "for provider screening or a housing decision."
            ),
            result=self.renter_budget_engine.evaluate(request),
        )

    def evaluate(
        self,
        session_id: str,
        request: EvaluateSessionRequest,
    ) -> SessionEvaluationResponse:
        with self._lock:
            state = self._state(session_id)
            if not state.consent_recorded:
                raise JourneyConsentError("Confirm at least one field before evaluation")
            rules_request = self._rules_request(state)
            rules_result = self.rules_engine.evaluate(rules_request)
            checklist = self._checklist(state, request.as_of_date)
            budget = self._renter_budget(
                state, request.include_renter_budget, rules_request
            )
            self._record(
                state,
                "JOURNEY_EVALUATED",
                rule_version=self.rules_engine.program.corpus_version,
                budget_version=(
                    self.renter_budget_engine.policy.policy_version
                    if budget.status is RenterBudgetStageStatus.EVALUATED
                    else None
                ),
            )
            return SessionEvaluationResponse(
                session_id=session_id,
                household_id=state.household_id,
                rules_and_math=rules_result,
                checklist=checklist,
                renter_budget=budget,
                audit_events=list(state.audit_events),
            )

    def export_packet(
        self,
        session_id: str,
        request: ExportPacketRequest,
    ) -> ApplicationReadinessPacket:
        if not request.renter_requested_export:
            raise JourneyConsentError("Packet export requires an explicit renter request")
        evaluation = self.evaluate(
            session_id,
            EvaluateSessionRequest(
                as_of_date=request.as_of_date,
                include_renter_budget=request.include_renter_budget,
            ),
        )
        with self._lock:
            state = self._state(session_id)
            self._record(state, "PACKET_EXPORTED")
            profile = sorted(
                (
                    item
                    for item in state.confirmed.values()
                    if item.reusable and not item.sensitive
                ),
                key=lambda item: (item.document_id, item.field_name.value),
            )
            return ApplicationReadinessPacket(
                packet_version=PACKET_VERSION,
                editable=True,
                renter_controlled=True,
                auto_send_disabled=True,
                household_id=state.household_id,
                confirmed_profile=profile,
                checklist=evaluation.checklist,
                rules_and_math=evaluation.rules_and_math,
                renter_budget=evaluation.renter_budget,
                source_document_ids=sorted(state.documents),
            )

    def delete_session(self, session_id: str) -> DeleteSessionResponse:
        with self._lock:
            if session_id not in self._sessions:
                raise SessionNotFoundError(session_id)
            del self._sessions[session_id]
        return DeleteSessionResponse(
            session_id=session_id,
            deleted=True,
            raw_document_bytes_retained=False,
            extracted_state_retained=False,
            message="The ephemeral session and all extracted state were deleted.",
        )
