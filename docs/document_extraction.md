# Document Extraction Pipeline

## Scope

`backend/app/services/extractor.py` parses only synthetic RealDoor PDFs. It is
an evidence extractor, not an eligibility engine. Every returned value is a
proposal with `confirmed=false` and `reusable=false`; another service must not
use it until the renter confirms or corrects it.

The implementation targets Python 3.11.

## Trust model

- File bytes are processed in memory and are not written by the parser.
- The PDF must contain a visible synthetic/training notice.
- Only the `FieldName` enum in `backend/app/schemas/profile.py` is returned.
- Embedded instructions are detected as `SecurityFlag` records and never
  become applicant/profile fields.
- No document text can invoke a tool, change a rule, or trigger a model call.
- Unknown types, missing fields, invalid values, and unavailable OCR cause an
  explicit review/abstention path rather than a guessed value.

## Supported documents

| Type | Allowlisted fields |
|---|---|
| Application summary | person name, household size, mailing address, application date |
| Pay stub | person name, pay date/period, frequency, hours, hourly rate, gross pay, net pay |
| Employment letter | person name, letter date, hours per week, hourly rate |
| Benefit letter | person name, letter date, monthly amount, frequency |
| Gig statement | person name, statement month, gross receipts, platform fees |
| Property rent statement | tenant, property/address/unit, statement date, lease dates, monthly rent, current balance |
| Bank deposit statement | account holder, statement period, total deposits |
| Self-employment statement | owner/business, statement month, gross receipts, expenses, net business income |

The detailed statement PDFs contain realistic ledger and transaction tables for
packet preview. Those row descriptions are intentionally not copied into the
profile. Only the minimum summary fields above are allowlisted.

Fixture layout references and their permitted design influence are recorded in
`docs/synthetic_document_references.md`.

The parser deliberately excludes the organizer field
`untrusted_instruction_text`. Its presence is represented as a security flag.

## Processing flow

1. Validate the PDF signature, 10 MB size cap, five-page cap, and encryption.
2. Extract horizontal text lines with PyMuPDF. Rotated synthetic watermarks are
   excluded from field matching.
3. If a page has no meaningful text layer, render it at 300 DPI and run the
   optional Tesseract adapter.
4. Classify one supported document type from its printed heading.
5. Find exact allowlisted labels and the closest aligned value line.
6. Normalize dates, months, money, hours, household size, and payment cadence.
7. Convert source geometry to the organizer's coordinate contract.
8. Detect prompt-injection phrases and return them only as ignored security
   evidence.
9. Group the same evidence-linked leaves into a document-specific
   `structured_data` object suitable for schema-constrained API responses.
10. Verify self-employment net income as gross receipts minus expenses in
    deterministic Python.
11. Return `extracted` only when every required field is grounded and no
    warning or security flag is present; otherwise return `needs_review` or a
    typed error.

## Source-box coordinates

PyMuPDF reports `(x0, top, x1, bottom)` from the top-left. RealDoor requires
`[x1, y1, x2, y2]` PDF points from the bottom-left. For page height `H`:

```text
realdoor_box = [x0, H - bottom, x1, H - top]
```

Raster OCR pixel boxes are first scaled to PDF points and then converted with
the same formula. The parser never asks a model to invent coordinates.

## Python 3.11 setup

```powershell
C:\Users\PC\AppData\Local\Programs\Python\Python311\python.exe -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r backend\requirements.txt
```

Raster documents also require the `tesseract` executable on `PATH`. If it is
missing, vector PDFs still work and raster input raises `OCRUnavailableError`.
This is a deliberate abstention, not silent partial extraction.

On Windows, the standard `C:\Program Files\Tesseract-OCR\tesseract.exe` path is
detected automatically. A nonstandard installation can be selected with the
`TESSERACT_CMD` environment variable.

## Usage

```python
from app.services.extractor import extract_document

result = extract_document(pdf_bytes)
payload = result.model_dump(mode="json")
print(payload["structured_data"])
```

`structured_data` is a discriminated union keyed by `document_type`. Each leaf
is an `ExtractedField`, so its value, confidence, source evidence,
`confirmed=false`, and `reusable=false` travel together. Missing leaves are
explicitly `null`; the parser does not invent replacements.

Set `PYTHONPATH=backend` when importing from the repository root.

## Tests

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s backend\tests -v
```

The regression suite verifies Python 3.11, exact values on all 24 organizer
PDFs when Tesseract is installed, source-box containment for born-digital
fixtures, prompt-injection isolation, raster abstention, file validation,
synthetic-only enforcement, deterministic checksums, nested structured output,
financial consistency warnings, and all eight documents in the Saad extension
pack. Raster tests are explicitly skipped on machines without Tesseract.

## Optional model extension

A later multimodal/LLM adapter may interpret OCR tokens, but it must return
only allowlisted field values plus existing token IDs. The server must derive
boxes from those IDs and reject unknown IDs. The model must have no tools and
must not perform calculations, rule selection, eligibility decisions, or
session actions.
