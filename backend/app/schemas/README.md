# Schemas Directory

Contains Pydantic v2 models for strict type and validation enforcement. 

All incoming and outgoing API payloads must explicitly use these models. Raw dictionaries are not permitted.

## Files
- `profile.py`: Data models for allowlisted fields during the data extraction phase (Stage 1).
- `calculator.py`: Input/Output data models used by the deterministic math engine (Stage 2).
- `financial_readiness.py`: Strict inputs and explainable metric-level outputs for
  the optional renter budgeting sandbox.
- `journey.py`: Typed session, consent, confirmation/correction, checklist,
  evaluation, export, audit, and deletion contracts for the renter journey.
- `aggregate.py`: Strict contracts for synthetic confirmation, rules stage,
  supplemental-reference matches, renter-budget batch status, and the single
  global JSON response.
