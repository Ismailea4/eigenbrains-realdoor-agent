# Frozen rule corpus

This directory pins the only rules scope supported by the RealDoor MVP:

- Program: LIHTC / HUD Multifamily Tax Subsidy Project (MTSP) 60% comparison
- Geography: Boston-Cambridge-Quincy, MA-NH HMFA
- Rule year: FY 2026
- HUD effective date: 2026-05-01
- Household sizes: 1 through 8

`manifest.json` records the corpus version, exact organizer-corpus SHA-256, program
selection, rule IDs, and the fact that runtime network access is disabled. The
service verifies those values at startup and fails closed if the corpus changes.

The frozen corpus remains at
`data/realdoor-hackathon-starter-pack/rules/rule_corpus.jsonl`; it is not replaced
by live search results at runtime. See `docs/rules_and_math.md` for the API contract,
calculation formulas, citation behavior, and abstention rules.
