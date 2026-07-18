# Schemas Directory

Contains Pydantic v2 models for strict type and validation enforcement. 

All incoming and outgoing API payloads must explicitly use these models. Raw dictionaries are not permitted.

## Files
- `profile.py`: Data models for allowlisted fields during the data extraction phase (Stage 1).
- `calculator.py`: Input/Output data models used by the deterministic math engine (Stage 2).
