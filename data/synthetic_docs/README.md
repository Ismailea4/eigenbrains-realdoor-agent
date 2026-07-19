# 📦 Synthetic Documents Directory

Contains evaluation PDFs, images, and synthetic pay stubs/benefit letters provided by the organizers.

These are used strictly for local development and testing the OCR `extractor` pipeline.

## Team extension

`saad_extended/` contains nine additional deterministic fixtures and matching
gold boxes. It expands coverage to household size 7, decimal hours, weekly and
semimonthly pay, a larger benefit amount, raster input, and embedded prompt
injection. It also includes detailed property-rent, bank-deposit, and
self-employment statements with data-minimized structured extraction. It does
not modify the organizer pack. The ninth fixture adds a fictional,
data-minimized government ID for the user-provided extraction matrix.
