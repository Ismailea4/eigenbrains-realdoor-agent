# Backend Directory (Team EigenBrains)

This folder contains the stateless, strictly typed FastAPI backend for the
RealDoor Copilot. The project targets Python 3.11.

## Setup

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r backend\requirements.txt
```

Raster-only PDFs additionally require a Tesseract executable. When it is not
available, the parser raises `OCRUnavailableError` instead of guessing.

## Document extraction

The deterministic parser returns allowlisted fields, source boxes, calibrated
confidence, document-specific structured data, and ignored prompt-injection
flags. Extracted values remain unconfirmed and non-reusable until the renter
confirms or corrects them. See `docs/document_extraction.md`.

## Rules API

Run from the repository root:

```powershell
.\.venv\Scripts\python.exe -m uvicorn backend.app.main:app --reload
```

- `GET /rules/scope` returns the frozen program, year, thresholds, citation,
  and effective date.
- `POST /rules/evaluate` annualizes only confirmed, traceable synthetic inputs.
- `POST /rules/question` answers allowlisted questions with citations and
  refuses decision requests.

See `docs/rules_and_math.md` for contracts and examples.

## Tests

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s backend\tests -v
```
