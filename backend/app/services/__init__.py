"""Deterministic services exposed by the backend package."""

from .financial_readiness import FinancialReadinessEngine, RiskPolicyIntegrityError
from .extractor import (
    DocumentExtractionError,
    NonSyntheticDocumentError,
    OCRUnavailableError,
    UnsupportedDocumentError,
    extract_document,
    extract_documents,
)
from .rules_engine import CorpusIntegrityError, RulesEngine

__all__ = [
    "CorpusIntegrityError",
    "DocumentExtractionError",
    "FinancialReadinessEngine",
    "NonSyntheticDocumentError",
    "OCRUnavailableError",
    "RiskPolicyIntegrityError",
    "RulesEngine",
    "UnsupportedDocumentError",
    "extract_document",
    "extract_documents",
]
