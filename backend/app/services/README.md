# Services Directory

Core algorithmic logic is separated by responsibility:

- `extractor.py`: deterministic, in-memory PDF parsing with PyMuPDF and an
  optional Tesseract adapter. It returns only allowlisted, unconfirmed fields
  with evidence boxes and ignored embedded-instruction flags.
- `rules_engine.py`: offline, checksum-pinned rules, citations, frozen-scope
  enforcement, and explicit abstention. Runtime network or model output cannot
  change the rules.
- `calculator.py`: exact deterministic money calculations with no LLM or
  probabilistic decisioning.
- `financial_readiness.py`: six deterministic, evidence-linked financial
  indicators for the optional renter budgeting sandbox, with versioned policy,
  confidence separation, explicit evidence gaps, and no aggregate applicant
  score or decision.
- `journey.py`: short-lived in-memory session orchestration, bounded document
  intake, consent and correction handling, recalculation, organizer-aligned
  checklist status, renter-requested export, minimal audit events, and deletion.

`backend/references_checker.py` is a reusable backend library and CLI. Its
default operation is offline and deterministic; optional external research is
isolated from executable rules and applicant values.
