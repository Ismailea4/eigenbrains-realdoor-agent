# Transparent financial-readiness engine

RealDoor transforms fragmented synthetic rental documents into a transparent,
evidence-linked financial-readiness profile. It describes affordability,
stability, liquidity, downside scenarios, and document consistency without an
opaque black-box score or an approval, denial, ranking, or eligibility outcome.

## Safety boundary

`PASS`, `REVIEW`, and `ABSTAIN` are **individual metric statuses only**:

- `PASS`: the metric was calculated and is within its published descriptive or
  configured range. It does not mean the household passes an application.
- `REVIEW`: a published descriptive category, configured scenario, discrepancy,
  or provisional input requires human review. It does not mean denial.
- `ABSTAIN`: required confirmed evidence is missing, out of scope, or unsuitable
  for deterministic calculation.

The response intentionally has no overall status, risk score, recommendation,
approval probability, or provider-facing acceptance decision. The policy exposes
`aggregate_score_enabled: false`.

## Six MVP metrics

| Metric | Deterministic formula | Status source |
| --- | --- | --- |
| Verified monthly income | Sum of traceable `CONFIRMED` recurring monthly sources | Evidence state only; no acceptance threshold |
| Housing-cost burden | `(rent + recurring utilities) / confirmed gross monthly income` | HUD descriptive 30% and 50% categories |
| Income stability | Population standard deviation / mean monthly income | Versioned internal CV threshold; not law |
| Liquid-reserve coverage | Confirmed accessible liquid funds / monthly housing costs | Calculation only; no minimum threshold |
| Downside affordability | `confirmed income x (1 - shock) / housing costs` | Explicit configurable scenario; not law |
| Cross-document reconciliation | `abs(max - min) / max(abs(values))` | Versioned internal tolerance; not law |

All monetary arithmetic uses Python `Decimal`. Ratios are rounded half-up to four
decimal places; monetary outputs are rounded half-up to cents.

## Confidence-aware inputs

Extraction confidence is never multiplied into a financial amount. Inputs are
separated into:

- `CONFIRMED`: included in the conservative confirmed scenario;
- `PROVISIONAL`: shown only in potential scenarios and requires confirmation;
- `UNVERIFIED`: excluded from calculations.

Every confirmed or provisional value requires a valid synthetic-document page
and source box. Embedded document instructions are recorded as ignored untrusted
text and cannot modify formulas, thresholds, tools, or data access.

## Metric details

### Housing burden

HUD describes housing costs including utilities above 30% of monthly income as
cost burden and above 50% as severe cost burden. RealDoor presents these as
descriptive affordability indicators, not universal private-rental rules.

### Income stability

At least three confirmed monthly observations are required. The response includes
coefficient of variation, mean, median, lowest month, recent average, largest
month-to-month decrease, and linear monthly trend. A high CV describes variation;
it is not a negative inference about gig work or a newly started job.

### Liquid reserves

Only confirmed, genuinely accessible funds are counted. Retirement accounts,
credit, illiquid assets, and entries marked inaccessible are excluded. No minimum
reserve coverage is treated as law or provider policy.

### Downside scenario

The default 15% income shock is a visible hackathon scenario. A renter-selected or
historically observed shock may be supplied with its rate, basis, and description.
The response always exposes the shock and formula.

### Reconciliation

At least two confirmed document observations are required for a fact. Missing
evidence returns `INSUFFICIENT_EVIDENCE`; it is never interpreted as financial
weakness. Discrepancies are shown fact by fact with evidence links.

## Versioned policy and sources

The engine loads `data/risk_management/advisory_policy.json`, verifies its pinned
SHA-256, and performs no runtime network retrieval.

- HUD CHAS background: <https://www.huduser.gov/portal/datasets/cp/CHAS/bg_chas.html>
- HUD rental-screening AI guidance:
  <https://archives.hud.gov/news/2024/FHEO_Guidance_on_Screening_of_Applicants_for_Rental_Housing.pdf>
- CFPB tenant-screening accuracy and correction information:
  <https://www.consumerfinance.gov/rules-policy/tenant-background-checks/review-your-rental-background-check/>

The HUD and CFPB sources support transparent, accurate, correctable presentation.
They do not supply the internal CV, stress, or reconciliation configuration.

## API

- `GET /financial-readiness/policy` exposes the policy version, complete metric
  thresholds, frozen scope, effective date, and scoring-disabled flag.
- `POST /financial-readiness/evaluate` returns exactly six typed metric results,
  confidence-aware income scenarios, citations, evidence, formulas, details, and
  human-readable review reasons.

A corrected source value is handled by resubmitting the request. Because the
service is stateless and deterministic, all downstream ratios and scenarios update
without retained raw document contents.

## Verification

```bash
python -m unittest discover -s backend/tests -v
python -m unittest discover -s data/realdoor-hackathon-starter-pack/starter/tests -v
```

Tests cover exact formulas, evidence links, confidence separation, correction
propagation, volatility, inaccessible assets, custom stress scenarios,
reconciliation conflicts, scope abstention, prompt injection, policy tampering,
schema validation, and the absence of an aggregate score or decision field.
