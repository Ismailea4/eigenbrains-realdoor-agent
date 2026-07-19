# Backend Directory (Team EigenBrains)

This folder contains the stateless, strictly typed FastAPI backend for the
RealDoor Copilot. The project targets Python 3.11.

It is designed to be high-performance, stateless, and strictly typed. 

## Structure
- `app/`: The main application module containing the core logic, schemas, and API routes.
- `requirements.txt`: Python package dependencies.

## Runtime

The project is pinned to **Python 3.11** via the root `.python-version` file.
## Setup

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r backend\requirements.txt
```

Raster-only PDFs additionally require a Tesseract executable. When it is not
available, the parser raises `OCRUnavailableError` instead of guessing.

Copy `backend/.env.example` to `backend/.env` for optional API-backed reference
research and feature flags. The real `.env` is ignored by Git and must never be
committed. The default aggregate pipeline performs no OpenAI or Tavily calls.

## Document extraction

The deterministic parser returns allowlisted fields, source boxes, calibrated
confidence, document-specific structured data, and ignored prompt-injection
flags. Extracted values remain unconfirmed and non-reusable until the renter
confirms or corrects them. See `docs/document_extraction.md`.

The extraction response includes both an auditable flat `fields` collection
and a document-specific `structured_data` object. Every structured leaf keeps
its confidence, source box, and unconfirmed/non-reusable review state.

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

Full contracts and examples are in `docs/rules_and_math.md`.

## Supplemental references

The supplied file now lives at `backend/references/rules.json`, and the corrected
checker name is `backend/references_checker.py`. Default matching is deterministic
and uses only the allowlisted document type—never applicant names, addresses,
amounts, evidence text, or embedded instructions.

- `GET /references/catalog` publishes the checksum, version, rule count, and the
  fact that this catalog cannot override executable rules.
- Optional Tavily/OpenAI research requires both
  `REALDOOR_EXTERNAL_REFERENCE_RESEARCH_ENABLED=true` and explicit caller
  consent.

See `docs/references_and_aggregate.md` for the trust boundary and CLI usage.

## Aggregated global JSON

- `GET /pipeline/aggregate` returns one Pydantic-validated synthetic result.
- It contains extraction and evidence, synthetic confirmation, deterministic
  rules/math, supplemental-reference matches, security flags, and the
  renter-budget stage.
- On this branch, the checked-in synthetic batch contains six transparent
  renter-budget metrics per household. The live renter-budget routes remain
  disabled unless explicitly enabled by the renter-controlled demo.

## Renter-controlled journey API

The end-to-end API creates a short-lived session, extracts PDFs without keeping
their raw bytes, requires explicit consent plus field-level confirmation or
correction, recalculates rules and the application checklist, exports an editable
JSON packet only on renter request, and supports immediate deletion:

- `POST /sessions`
- `POST /sessions/{session_id}/documents`
- `POST /sessions/{session_id}/confirm`
- `POST /sessions/{session_id}/evaluate`
- `POST /sessions/{session_id}/export`
- `DELETE /sessions/{session_id}`

Sessions expire after 30 minutes of inactivity. Upload reads are bounded by the
extractor's maximum document size. See `docs/backend_journey.md` for contracts
and the expected request sequence.

## Optional renter-budget API

The risk branch makes the budgeting sandbox available, but every renter session
starts with it unrequested. The frontend toggle controls
`include_renter_budget`; set `REALDOOR_RENTER_BUDGET_ENABLED=false` for an
administrator kill switch.

- `GET /renter-budget/policy` publishes every metric threshold and confirms that
  aggregate scoring is disabled.
- `POST /renter-budget/evaluate` calculates six evidence-linked descriptive
  metrics with `CALCULATED`, `NEEDS_REVIEW`, or `INSUFFICIENT_EVIDENCE` status.

These routes return `404` when the administrator kill switch is active. The engine has no
overall applicant outcome, is prohibited for provider screening, and never makes
or predicts a housing decision. See `docs/financial_readiness.md` for formulas,
evidence requirements, sources, and status semantics.

## Tests

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s backend\tests -v
```

## Synthetic end-to-end artifact

Run the generated Saad fixture pack through extraction, synthetic-gold
confirmation, and rules/math:

```powershell
.\.venv\Scripts\python.exe backend\run_synthetic_pipeline.py
```

The command writes the same global API contract to
`backend/pipeline_results/synthetic_pipeline_output.json`, with
`pipeline_variant: rules_and_renter_budget`, 9 supplemental-reference reviews,
and 42 budgeting metrics across the 7 synthetic households. This batch artifact
is synthetic test evidence; each live session still leaves renter budgeting off
until the renter explicitly enables the toggle.
