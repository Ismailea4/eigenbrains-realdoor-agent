# Renter-controlled backend journey

The journey API joins extraction, confirmation, deterministic rules, checklist
preparation, optional renter budgeting, export, and deletion without making an
application decision. It accepts only synthetic challenge documents.

## Sequence

1. `POST /sessions` creates an ephemeral session for a household.
2. `POST /sessions/{session_id}/documents` accepts one PDF at a time. The server
   bounds the read, extracts in memory, and does not retain raw document bytes.
3. `POST /sessions/{session_id}/confirm` requires
   `consent_to_reuse_confirmed_values: true` and a `CONFIRM` or `CORRECT` action
   for each selected field. Unconfirmed fields cannot enter downstream math.
4. `POST /sessions/{session_id}/evaluate` recalculates exact rules math and the
   organizer-aligned checklist. Corrections immediately propagate.
5. `POST /sessions/{session_id}/export` requires
   `renter_requested_export: true` and returns an editable JSON packet with
   automatic sending disabled.
6. `DELETE /sessions/{session_id}` removes extracted and confirmed session state.
   Later access returns `404`.

Sessions also expire after 30 minutes of inactivity. Each accepted session
operation refreshes that inactivity window.

## Evaluation behavior

- Rules use the checksum-pinned FY 2026 MTSP Boston-area corpus and exact
  `Decimal` arithmetic.
- The checklist reports `PRESENT`, `MISSING`, `EXPIRED`, or
  `NEEDS_CONFIRMATION`; the recency convention is 60 days.
- Missing or uncertain evidence causes review/abstention, never a guessed value.
- The optional renter budget reports `NOT_REQUESTED`, `DISABLED`, or `EVALUATED`.
  The risk branch makes the module available unless an administrator sets
  `REALDOOR_RENTER_BUDGET_ENABLED=false`; calculation still occurs only when the
  renter passes `include_renter_budget: true`.

## Safety and audit boundary

The API never approves, denies, scores, ranks, predicts acceptance, or determines
eligibility. Budget output is renter-controlled and prohibited for provider
screening. Audit events contain only action sequence, document/field identifiers,
and rule or policy versions; they do not retain document text. The exported
packet includes source document identifiers and evidence-linked confirmed fields,
but no raw PDF bytes and no automatic submission behavior.

## Verification

From the repository root with Python 3.11:

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s backend\tests -v
.\.venv\Scripts\python.exe -m unittest discover -s data\realdoor-hackathon-starter-pack\starter\tests -v
.\.venv\Scripts\python.exe backend\run_synthetic_pipeline.py
```

The final command writes
`backend/pipeline_results/synthetic_pipeline_output.json` for auditable synthetic
demo evidence. It does not enable the live renter-budget endpoints.
