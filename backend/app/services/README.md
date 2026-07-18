# Services Directory

Contains the core algorithmic logic. This domain is strictly isolated into distinct engineering responsibilities.

## Files
- `extractor.py`: OCR pipeline logic, generating bounding box coordinates (source boxes), and computing calibrated confidence scores (Stage 1).
- `rules_engine.py`: Document/Rule corpus RAG retrieval mechanism (Stage 2).
- `calculator.py`: Pure, deterministic Python math functions. **NO LLM** generation or probabilistic logic is allowed for financial calculations (Stage 2).
    