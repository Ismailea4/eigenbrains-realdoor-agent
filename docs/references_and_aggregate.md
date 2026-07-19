# Supplemental references and global aggregate JSON

## Purpose

RealDoor combines the synthetic backend run into one strict JSON contract. The
aggregate is available through `GET /pipeline/aggregate` and as the checked-in
demo artifact `backend/pipeline_results/synthetic_pipeline_output.json`.

The object contains:

- each structured document extraction and source evidence;
- the checked-in synthetic-gold confirmation record;
- deterministic household rules and exact math;
- per-document supplemental-reference matches;
- ignored prompt-injection flags and pipeline totals; and
- an explicit branch-extension stage named `renter_budget`.

The risk-management branch returns
`pipeline_variant: rules_and_renter_budget`, sets
`renter_budget_available: true`, and includes six transparent metrics for every
synthetic household. The baseline `yazid-the-tech-lead` branch uses the same
shared contract but returns `NOT_AVAILABLE` for that stage and imports no
renter-budget engine.

## Two rule sources with different authority

The backend intentionally keeps two sources separate:

1. The checksum-pinned organizer/HUD corpus under
   `data/realdoor-hackathon-starter-pack/rule_corpus/` is executable. It controls
   program selection, year, threshold, citation, effective date, and math.
2. `backend/references/rules.json` is the user-supplied supplemental catalog. It
   supports human research and document organization only. It cannot override
   the frozen corpus or change a calculation.

The supplied page numbers are preserved, but the catalog is marked
`authoritative_for_calculation: false` until a human maps every locator to a
named source edition. This prevents a plausible-looking excerpt from silently
becoming law or program policy.

## Safe reference checker

The typo in the original file name is fixed:

```text
backend/references_checker.py
```

By default, matching is deterministic and offline. It uses only the allowlisted
document type; it does not use names, addresses, balances, income amounts,
evidence text, or embedded instructions. A document instruction is represented
only by `untrusted_document_text_ignored: true`.

Optional external research is a separate demonstration path. It requires:

1. `REALDOOR_EXTERNAL_REFERENCE_RESEARCH_ENABLED=true` in `backend/.env`; and
2. the explicit `--consent-to-external-processing` CLI flag.

Queries contain only the document type and supplemental rule titles. Tavily is
restricted to official HUD, HUD User, IRS, and CFPB domains. If OpenAI is used,
the Responses API returns a Pydantic-validated narrative. Web content is treated
as untrusted, the model receives no applicant values and no tools, and its output
cannot change executable rules or produce severity, scoring, or an applicant
decision.

## Configuration

Create the local configuration file without committing it:

```powershell
Copy-Item backend\.env.example backend\.env
```

`backend/.env` is covered by the repository's `.env` ignore rule. Only the
placeholder `backend/.env.example` belongs in Git.

## Commands

Generate the global artifact:

```powershell
.\.venv\Scripts\python.exe backend\run_synthetic_pipeline.py
```

Create a separate offline reference-review file from that artifact:

```powershell
.\.venv\Scripts\python.exe backend\references_checker.py
```

Explicitly run the optional external research path:

```powershell
.\.venv\Scripts\python.exe backend\references_checker.py `
  --external-research `
  --consent-to-external-processing
```

The external command can incur API usage. It is never called by the default
pipeline or `GET /pipeline/aggregate`.

## Verification

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s backend\tests -v
.\.venv\Scripts\python.exe -m unittest discover `
  -s data\realdoor-hackathon-starter-pack\starter\tests -v
```

Tests validate the catalog checksum, non-executable boundary, consent gate,
prompt-injection isolation, typed aggregate schema, risk-branch marker, all 42
synthetic budgeting metrics, and the checked-in global artifact.
