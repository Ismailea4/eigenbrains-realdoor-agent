"""Public service exports."""

from .extractor import (
    DocumentExtractionError,
    NonSyntheticDocumentError,
    OCRUnavailableError,
    UnsupportedDocumentError,
    extract_document,
    extract_documents,
)

__all__ = [
    "DocumentExtractionError",
    "NonSyntheticDocumentError",
    "OCRUnavailableError",
    "UnsupportedDocumentError",
    "extract_document",
    "extract_documents",
]
