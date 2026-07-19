# Services Directory

Contains the core algorithmic logic. This domain is strictly isolated into distinct engineering responsibilities.

## Files
- `extractor.py`: OCR pipeline logic, generating bounding box coordinates (source boxes), and computing calibrated confidence scores (Stage 1).
- `rules_engine.py`: Offline, checksum-pinned rule retrieval, cited questions,
  scope enforcement, and explicit abstention (Stage 2). No model or live web
  result can change the frozen rules.
- `calculator.py`: Pure, deterministic Python math functions. **NO LLM** generation or probabilistic logic is allowed for financial calculations (Stage 2).
