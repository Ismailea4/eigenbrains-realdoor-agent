# Services Directory

Core algorithmic logic is separated by responsibility:

## Files
- `extractor.py`: Deterministic in-memory PDF parser. PyMuPDF handles text-layer
  PDFs; optional Tesseract handles raster pages. It returns only allowlisted,
  unconfirmed fields with PDF-point source boxes and flags embedded instructions
  as ignored untrusted text. See `docs/document_extraction.md`.
- `rules_engine.py`: Offline, checksum-pinned rule retrieval, cited questions,
  scope enforcement, and explicit abstention (Stage 2). No model or live web
  result can change the frozen rules.
- `calculator.py`: Pure, deterministic Python math functions. **NO LLM** generation or probabilistic logic is allowed for financial calculations (Stage 2).
- `financial_readiness.py`: Six deterministic, evidence-linked financial indicators
  with versioned policy, confidence separation, explicit abstention, and no
  aggregate applicant score or decision.
- `extractor.py`: deterministic, in-memory PDF parsing with PyMuPDF and an
  optional Tesseract adapter. It returns only allowlisted, unconfirmed fields
  with evidence boxes and ignored embedded-instruction flags.
- `rules_engine.py`: offline, checksum-pinned rules, citations, frozen-scope
  enforcement, and explicit abstention. Runtime network or model output cannot
  change the rules.
- `calculator.py`: exact deterministic money calculations with no LLM or
  probabilistic decisioning.
- `financial_readiness.py`: six deterministic, evidence-linked financial
  indicators with versioned policy, confidence separation, explicit
  abstention, and no aggregate applicant score or decision.
