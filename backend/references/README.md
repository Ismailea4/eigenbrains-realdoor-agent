# Supplemental reference catalog

`rules.json` is the supplied LIHTC reference list used by
`backend/references_checker.py` for document-type matching. The typo in the
original script name (`refrences_checker.py`) is corrected throughout the
backend.

This catalog is supplemental: it does not replace or modify the checksum-pinned
HUD rules corpus under `data/realdoor-hackathon-starter-pack/rule_corpus/`.
Its page numbers are preserved as supplied locators, but they are not treated as
authoritative citations until a human maps them to a named source edition. The
deterministic rules engine remains the only authority for program selection,
thresholds, effective dates, and calculations.

The default checker uses only the allowlisted document type. It does not send
names, addresses, amounts, evidence text, or other extracted values to an
external service. Optional official-domain research requires both
`REALDOOR_EXTERNAL_REFERENCE_RESEARCH_ENABLED=true` and explicit caller consent.

