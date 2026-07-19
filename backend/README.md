# ⚙️ Backend Directory (Team EigenBrains)

This folder contains the FastAPI application backend for the RealDoor Copilot. 

It is designed to be high-performance, stateless, and strictly typed. 

## Structure
- `app/`: The main application module containing the core logic, schemas, and API routes.
- `requirements.txt`: Python package dependencies.

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
