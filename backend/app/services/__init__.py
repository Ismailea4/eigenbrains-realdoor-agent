"""Deterministic services exposed by the backend package."""

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
    "NonSyntheticDocumentError",
    "OCRUnavailableError",
    "RulesEngine",
    "UnsupportedDocumentError",
    "extract_document",
    "extract_documents",
]
