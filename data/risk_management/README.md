# Optional renter-budget policy

`advisory_policy.json` is the versioned, checksum-pinned configuration for the
six renter budgeting metrics. It is intentionally separate from the official
HUD MTSP rule corpus and cannot change program-rule calculations.

- HUD's 30% and 50% housing-cost-burden categories are labeled descriptive
  indicators, not rental acceptance rules.
- Income-CV, stress, and reconciliation thresholds are labeled configurable
  internal policy or scenario values, not law.
- Liquid-reserve coverage has no minimum acceptance threshold.
- Aggregate scoring is disabled.
- Provider screening use is prohibited; live session calculation is off until
  the renter explicitly enables it, and administrators retain a kill switch.

The backend verifies the policy SHA-256 at startup and fails closed if any value
changes without a reviewed code update.
