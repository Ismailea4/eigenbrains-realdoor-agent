# Saad Extended Synthetic Fixtures

This directory contains nine deterministic, fictional documents created to
exercise extraction cases beyond the organizer pack:

- household size 7 and a longer apartment address;
- decimal weekly hours and a weekly pay frequency;
- a larger monthly benefit amount;
- decimal employment hours;
- semimonthly pay, raster-only input, and embedded prompt-injection text.
- a detailed property rent statement with lease facts and a rent ledger;
- a two-page bank deposit statement for gig-income corroboration;
- a self-employment profit-and-loss statement with deterministic net-income
  verification.
- a data-minimized fictional government ID with legal name, DOB, and expiration
  date, but no credential number, signature, or barcode.

The matrix extension also extracts pay-stub YTD gross pay, benefit issuing
agency, and bank name/ending balance.

The detailed tables remain visible for human packet review, while extraction
copies only allowlisted summary fields. This is intentional data minimization.

The extension does **not** modify the organizer pack or its checksum manifest.
Every PDF contains a visible synthetic-data notice. Gold source boxes use PDF
points with a bottom-left origin on a 612 x 792 point page.

Regenerate with Python 3.11 from the repository root:

```powershell
.venv\Scripts\python.exe scripts\generate_saad_synthetic_documents.py
```

Generated files are deterministic and accompanied by `checksums.sha256`.

The layouts are based on public IRS, FDIC, SSA, HUD, CFPB, and Massachusetts
reference patterns. See `docs/synthetic_document_references.md` for the source
matrix and the exact design elements reused. No official logos or real records
are included.
