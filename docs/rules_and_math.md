# Rules and deterministic math

## Challenge compliance

The rules stage implements one frozen scope and does not behave as a generic
eligibility engine.

| Challenge requirement | Implementation |
| --- | --- |
| Right program and year | Only `LIHTC_MTSP_60`, FY 2026 is accepted. Other selections abstain. |
| One metro | Only Boston-Cambridge-Quincy, MA-NH HMFA is accepted. |
| Authoritative citation | Thresholds cite HUD rule `HUD-MTSP-002`, FY 2026 report page 130. |
| Effective date | Every scope, calculation, and question response includes `2026-05-01`. |
| Exact calculation | Python `Decimal` math with explicit annual multipliers; no LLM or float math. |
| Confirmed input | Every income input must be renter-confirmed and traceable to a page/source box. |
| Abstention | Wrong scope, missing evidence, uncertainty, unsupported frequency, and household size outside 1-8 produce explicit review reasons. |
| No decisioning | Output is limited to a numerical comparison and `READY_TO_REVIEW` / `NEEDS_REVIEW`; it never approves, denies, scores, ranks, or determines eligibility. |
| Untrusted documents | Embedded instructions are recorded as ignored data and never enter rule selection or math. |

## Frozen sources

The checked-in organizer corpus is pinned by SHA-256 in
`data/rule_corpus/manifest.json`. The service verifies the same audited hash in
code at startup, so changing the corpus and manifest together still fails closed.
Runtime network access is disabled.

- `HUD-MTSP-001`: FY 2026 MTSP limits effective May 1, 2026.
  Source: <https://www.huduser.gov/portal/datasets/mtsp.html>
- `HUD-MTSP-002`: Boston-Cambridge-Quincy FY 2026 60% table for household sizes
  1-8. Source: <https://www.huduser.gov/portal/datasets/mtsp/mtsp26/HERA-Income-Limits-Report-FY26.pdf>,
  PDF page 130.
- `CH-INCOME-001`: organizer annualization convention, frozen July 18, 2026.
- `CH-DECISION-001`: numerical comparison is allowed; final determinations remain
  human and program-specific.

The table used by the service is parsed from the checksum-pinned rule record:

| Household size | Frozen 60% threshold |
| ---: | ---: |
| 1 | $72,000 |
| 2 | $82,320 |
| 3 | $92,580 |
| 4 | $102,840 |
| 5 | $111,120 |
| 6 | $119,340 |
| 7 | $127,560 |
| 8 | $135,780 |

## Deterministic formulas

The allowlisted recurring-income frequencies and exact annual multipliers are:

| Frequency | Formula |
| --- | --- |
| weekly | confirmed gross amount x 52 |
| biweekly | confirmed gross amount x 26 |
| semimonthly | confirmed gross amount x 24 |
| monthly | confirmed gross amount x 12 |
| annual | confirmed gross amount x 1 |

Each source is rounded to cents with decimal half-up rounding, then the annualized
sources are summed. The comparison is exactly `below_or_equal` when annualized
income is less than or equal to the frozen threshold and `above` otherwise. These
labels are numerical relationships, not eligibility conclusions.

Example from organizer household HH-001:

```text
$2,166.00 x 26 periods/year = $56,316.00
$56,316.00 compared with $72,000.00 -> below_or_equal
```

## API

### `GET /rules/scope`

Returns the corpus version, frozen program/year/area, effective date, all eight
thresholds, the complete HUD citation, and the human-decision boundary.

### `POST /rules/evaluate`

Example request:

```json
{
  "household_id": "HH-001",
  "program_id": "LIHTC_MTSP_60",
  "rule_year": 2026,
  "area": "Boston-Cambridge-Quincy, MA-NH HMFA",
  "ami_percentage": 60,
  "household_size": 1,
  "income_sources": [
    {
      "source_id": "HH-001-WAGES",
      "label": "Confirmed biweekly gross wages",
      "amount": "2166.00",
      "frequency": "biweekly",
      "confirmed": true,
      "uncertain": false,
      "uncertainty_reason": null,
      "evidence": {
        "source_document_id": "HH-001-D02",
        "field_name": "gross_pay",
        "page": 1,
        "source_box": [340, 528, 397.38, 544],
        "page_width": 612,
        "page_height": 792,
        "synthetic": true,
        "untrusted_text_detected": false
      }
    }
  ]
}
```

The response exposes every confirmed input, evidence reference, multiplier,
per-source formula, sum formula, threshold, comparison, citation, effective date,
and review reason. A field correction is propagated by resubmitting the corrected
confirmed value; the deterministic response is recomputed without hidden state.

### `POST /rules/question`

Allowlisted topics are the frozen threshold, effective date, program scope,
decision boundary, HUD property-data limitations, HUD geocode precision,
untrusted document instructions, the 60-day simulation convention, the federal
LIHTC statutory anchor, and compliance monitoring. Threshold questions require
household size 1-8. Unknown questions abstain instead of inventing a rule.
Requests to decide, approve, deny, qualify, score, or rank are refused and
redirected to the cited rule and a human reviewer.

## Explicit abstention behavior

| Condition | Result |
| --- | --- |
| Wrong program, area, percentage, or year | No threshold and no calculation |
| No income source | No calculation |
| Unconfirmed or uncertain source | No calculation; correction/confirmation requested |
| Missing or invalid source box | Schema failure or explicit missing-evidence reason |
| Non-synthetic document | No calculation |
| Unsupported frequency | No calculation |
| Household size outside 1-8 | Income may be annualized, but no threshold comparison is made |
| Unsupported rule question | Cited-topic abstention and human-review guidance |

## Verification

Run:

```bash
python -m unittest discover -s backend/tests -v
python -m unittest discover -s data/realdoor-hackathon-starter-pack/starter/tests -v
```

The rule tests cover all organizer gold annualized amounts and thresholds,
boundary math, wrong-year attacks, corpus tampering, malformed evidence boxes,
unconfirmed/uncertain inputs, prompt injection, cited questions, and refusal.
