# Services Directory

Contains the core algorithmic logic. This domain is strictly isolated into distinct engineering responsibilities.

## Files
- `extractor.py`: Deterministic in-memory PDF parser. PyMuPDF handles text-layer
  PDFs; optional Tesseract handles raster pages. It returns only allowlisted,
  unconfirmed fields with PDF-point source boxes and flags embedded instructions
  as ignored untrusted text. See `docs/document_extraction.md`.
- `rules_engine.py`: Document/Rule corpus RAG retrieval mechanism (Stage 2).
- `calculator.py`: Pure, deterministic Python math functions. **NO LLM** generation or probabilistic logic is allowed for financial calculations (Stage 2).
