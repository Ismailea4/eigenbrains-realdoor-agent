# ⚙️ Backend Directory (Team EigenBrains)

This folder contains the FastAPI application backend for the RealDoor Copilot. 

It is designed to be high-performance, stateless, and strictly typed. 

## Structure
- `app/`: The main application module containing the core logic, schemas, and API routes.
- `requirements.txt`: Python package dependencies.

## Runtime

The project is pinned to **Python 3.11** via the root `.python-version` file.

```powershell
C:\Users\PC\AppData\Local\Programs\Python\Python311\python.exe -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r backend\requirements.txt
```

For raster-only PDFs, install the Tesseract executable and make `tesseract`
available on `PATH`. The parser raises a typed `OCRUnavailableError` if OCR is
required but unavailable; it never guesses from an unreadable page.

Run document extraction tests from the repository root:

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s backend\tests -v
```

The extraction response includes both an auditable flat `fields` collection
and a document-specific `structured_data` object. Every structured leaf keeps
its confidence, source box, and unconfirmed/non-reusable review state.

## Rules API

Run from the repository root with Python 3.11:

```bash
python -m uvicorn backend.app.main:app --reload
```

- `GET /rules/scope` returns the single frozen program/year, all eight thresholds,
  the HUD citation, and effective date.
- `POST /rules/evaluate` annualizes only renter-confirmed, traceable synthetic inputs.
- `POST /rules/question` answers allowlisted rule questions with citations and
  refuses decision requests.

Full contracts and examples are in `docs/rules_and_math.md`.

## Financial-readiness API

- `GET /financial-readiness/policy` publishes every metric threshold and confirms
  that aggregate scoring is disabled.
- `POST /financial-readiness/evaluate` calculates six evidence-linked advisory
  metrics with `PASS`, `REVIEW`, or `ABSTAIN` at the metric level only.

The financial engine has no overall applicant outcome and never makes or predicts
a housing decision. See `docs/financial_readiness.md` for formulas, evidence
requirements, sources, and status semantics.
