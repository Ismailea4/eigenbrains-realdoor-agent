"""FastAPI entry point for the RealDoor rules-and-math stage."""

from fastapi import FastAPI

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
from .services.financial_readiness import FinancialReadinessEngine
from .services.rules_engine import RulesEngine


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


@app.get("/financial-readiness/policy", response_model=RiskPolicySummary)
def get_financial_readiness_policy() -> RiskPolicySummary:
    """Expose every advisory threshold and its version before calculation."""

    return financial_readiness_engine.policy


@app.post("/financial-readiness/evaluate", response_model=FinancialReadinessResponse)
def evaluate_financial_readiness(
    request: FinancialReadinessRequest,
) -> FinancialReadinessResponse:
    """Return six evidence-linked metrics without an aggregate applicant outcome."""

    return financial_readiness_engine.evaluate(request)
