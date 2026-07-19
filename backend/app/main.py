"""FastAPI entry point for the renter-controlled RealDoor journey."""

from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi import FastAPI, File, HTTPException, UploadFile

from .schemas.aggregate import GlobalAggregateResponse, ReferenceCatalogSummary
from .schemas.calculator import (
    ProgramScope,
    RuleQuestionRequest,
    RuleQuestionResponse,
    RulesEvaluationRequest,
    RulesEvaluationResponse,
)
from .schemas.financial_readiness import (
    FinancialReadinessRequest,
    FinancialReadinessResponse,
    RiskPolicySummary,
)
from .schemas.journey import (
    ApplicationReadinessPacket,
    ConfirmationResponse,
    ConfirmFieldsRequest,
    CreateSessionRequest,
    CreateSessionResponse,
    DeleteSessionResponse,
    EvaluateSessionRequest,
    ExportPacketRequest,
    SessionEvaluationResponse,
    UploadDocumentResponse,
)
from .services.financial_readiness import FinancialReadinessEngine
from .services.extractor import MAX_DOCUMENT_BYTES
from .services.journey import (
    ApplicationJourneyService,
    JourneyConflictError,
    JourneyConsentError,
    SessionNotFoundError,
)
from .services.rules_engine import RulesEngine
from .services.extractor import extract_document, DocumentExtractionError
from .schemas.profile import DocumentExtraction

from fastapi.middleware.cors import CORSMiddleware
from backend.references_checker import catalog_summary, load_environment


load_environment()

app = FastAPI(
    title="RealDoor Application-Readiness Copilot",
    version="0.1.0",
    description=(
        "Assistive rules and deterministic math for a frozen housing-program corpus. "
        "This API never makes eligibility or application decisions."
    ),
)
rules_engine = RulesEngine()
financial_readiness_engine = FinancialReadinessEngine()
journey_service = ApplicationJourneyService(
    rules_engine=rules_engine,
    renter_budget_engine=financial_readiness_engine,
)


def _journey_error(exc: Exception) -> HTTPException:
    if isinstance(exc, SessionNotFoundError):
        return HTTPException(status_code=404, detail="Session not found or already deleted")
    if isinstance(exc, JourneyConsentError):
        return HTTPException(status_code=403, detail=str(exc))
    if isinstance(exc, JourneyConflictError):
        return HTTPException(status_code=409, detail=str(exc))
    return HTTPException(status_code=422, detail=str(exc))

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/rules/scope", response_model=ProgramScope)
def get_rules_scope() -> ProgramScope:
    """Return the only program, year, area, thresholds, and citation in scope."""

    return rules_engine.program


@app.post("/rules/evaluate", response_model=RulesEvaluationResponse)
def evaluate_rules(request: RulesEvaluationRequest) -> RulesEvaluationResponse:
    """Calculate from confirmed evidence or return an explicit review abstention."""

    return rules_engine.evaluate(request)


@app.post("/rules/question", response_model=RuleQuestionResponse)
def answer_rules_question(request: RuleQuestionRequest) -> RuleQuestionResponse:
    """Answer allowlisted rule questions with human-readable source citations."""

    return rules_engine.answer_question(request)


@app.get("/references/catalog", response_model=ReferenceCatalogSummary)
def get_reference_catalog() -> ReferenceCatalogSummary:
    """Describe the non-executable supplemental reference catalog."""

    return catalog_summary()


@app.get("/pipeline/aggregate", response_model=GlobalAggregateResponse)
def get_global_aggregate() -> GlobalAggregateResponse:
    """Return one validated JSON object for the complete synthetic backend run."""

    from backend.run_synthetic_pipeline import run_pipeline

    return GlobalAggregateResponse.model_validate(run_pipeline())


@app.get(
    "/financial-readiness/policy",
    response_model=RiskPolicySummary,
    include_in_schema=False,
)
@app.get("/renter-budget/policy", response_model=RiskPolicySummary)
def get_renter_budget_policy() -> RiskPolicySummary:
    """Expose the optional renter-only budgeting policy when enabled."""

    if not journey_service.renter_budget_enabled:
        raise HTTPException(status_code=404, detail="Optional renter budgeting is disabled")
    return financial_readiness_engine.policy


@app.post(
    "/financial-readiness/evaluate",
    response_model=FinancialReadinessResponse,
    include_in_schema=False,
)
@app.post("/renter-budget/evaluate", response_model=FinancialReadinessResponse)
def evaluate_renter_budget(
    request: FinancialReadinessRequest,
) -> FinancialReadinessResponse:
    """Return renter-requested descriptive calculations without an applicant outcome."""

    if not journey_service.renter_budget_enabled:
        raise HTTPException(status_code=404, detail="Optional renter budgeting is disabled")
    return financial_readiness_engine.evaluate(request)


@app.post(
    "/documents/extract",
    response_model=DocumentExtraction,
    include_in_schema=False,
)
@app.post("/upload/extract", response_model=DocumentExtraction)
async def upload_extract(file: UploadFile = File(...)) -> DocumentExtraction:
    """Extract structured data and evidence from a synthetic PDF."""
    try:
        content = await file.read()
        return extract_document(content)
    except DocumentExtractionError as e:
        raise HTTPException(status_code=400, detail=str(e))
@app.post("/sessions", response_model=CreateSessionResponse, status_code=201)
def create_session(request: CreateSessionRequest) -> CreateSessionResponse:
    """Create an ephemeral renter-controlled application session."""

    return journey_service.create_session(request.household_id)


@app.post(
    "/sessions/{session_id}/documents",
    response_model=UploadDocumentResponse,
    status_code=201,
)
async def upload_document(
    session_id: str,
    file: UploadFile = File(...),
) -> UploadDocumentResponse:
    """Extract one synthetic PDF in memory without retaining its bytes."""

    try:
        payload = await file.read(MAX_DOCUMENT_BYTES + 1)
        return journey_service.upload_document(session_id, payload)
    except (SessionNotFoundError, JourneyConflictError, JourneyConsentError, ValueError) as exc:
        raise _journey_error(exc) from exc


@app.post(
    "/sessions/{session_id}/confirm",
    response_model=ConfirmationResponse,
)
def confirm_or_correct_fields(
    session_id: str,
    request: ConfirmFieldsRequest,
) -> ConfirmationResponse:
    """Record renter confirmation or correction before downstream reuse."""

    try:
        return journey_service.confirm_fields(session_id, request)
    except (SessionNotFoundError, JourneyConflictError, JourneyConsentError) as exc:
        raise _journey_error(exc) from exc


@app.post(
    "/sessions/{session_id}/evaluate",
    response_model=SessionEvaluationResponse,
)
def evaluate_session(
    session_id: str,
    request: EvaluateSessionRequest,
) -> SessionEvaluationResponse:
    """Recompute rules, checklist, and optional renter-only budgeting."""

    try:
        return journey_service.evaluate(session_id, request)
    except (SessionNotFoundError, JourneyConflictError, JourneyConsentError) as exc:
        raise _journey_error(exc) from exc


@app.post(
    "/sessions/{session_id}/export",
    response_model=ApplicationReadinessPacket,
)
def export_packet(
    session_id: str,
    request: ExportPacketRequest,
) -> ApplicationReadinessPacket:
    """Create an editable packet only after an explicit renter export request."""

    try:
        return journey_service.export_packet(session_id, request)
    except (SessionNotFoundError, JourneyConflictError, JourneyConsentError) as exc:
        raise _journey_error(exc) from exc


@app.delete(
    "/sessions/{session_id}",
    response_model=DeleteSessionResponse,
)
def delete_session(session_id: str) -> DeleteSessionResponse:
    """Delete all ephemeral state for a session."""

    try:
        return journey_service.delete_session(session_id)
    except SessionNotFoundError as exc:
        raise _journey_error(exc) from exc
