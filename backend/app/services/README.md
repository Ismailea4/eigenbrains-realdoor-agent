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
