# DH-side build prompt — merged declarations PDF (TKX / TKN ghép)

Hand this prompt to the Data Hub AI agent. It is self-contained (does not
require the CO repo). This is a NEW contract (a new read-only endpoint), and it
depends on the same blob-access path as the open `download.zip` bytes defect —
read the "Relationship" note before starting.

---

```
You are working in the Data Hub codebase. Build a new read-only endpoint requested by the CO (certificate-of-origin) service.

## Goal
Return ALL of a client's TKX (export) or TKN (import) customs declarations as ONE merged, print-standard PDF. Operators file a single "tờ khai ghép" PDF with HQ (e.g. "6. TKN GHEP.pdf"); today they print and concatenate each declaration by hand. CO will fetch this server-side and drop it into the dossier as a numbered slot.

## New endpoint
GET /v1/hub/clients/{client_id}/declarations/download.pdf
Query:
  - direction       required   import (TKN) | export (TKX)
  - declaration_nos required   comma-separated, ≤ 500
  - filename        optional   Content-Disposition filename; default declarations_{client_id}_{direction}.pdf
  - sort            optional   declaration_no (default) | registration_date

Mirror the existing GET .../declarations/download.zip for auth, client scoping, query parsing, and the 500 cap — reuse that handler's plumbing.

## Response
200, application/pdf, Content-Disposition: attachment; filename="...".
A SINGLE merged PDF:
  - One declaration after another in `sort` order (default declaration_no ascending), deterministic.
  - Each declaration rendered to the standard A4 print layout of the tờ khai. A declaration with multiple files contributes all its pages, ordered by filename.
  - Declarations with no file are SKIPPED from the body and reported via headers (below), not inserted as blank/error pages.

Response headers so CO can warn the operator about gaps:
  X-Declarations-Requested: <n>
  X-Declarations-Included:  <n>
  X-Declarations-Missing:   <n>
  X-Declarations-Missing-Nos: <comma-separated, first 50>

Zero match / all missing: 200 with a single well-formed info page ("Không có tờ khai có file") + the headers above. Never an empty or corrupt PDF.

Errors (same shape as download.zip):
  400 invalid_direction | declaration_nos_required | too_many_declaration_nos | invalid_sort
  401 bearer required/invalid   403 forbidden (client)   404 client not found
Auth scope: hub:read (read-only render, no mutation). Token must be authorized for client_id.

## CRITICAL — confirm the source document BEFORE building the renderer
The stored declaration files are .xls (prod evidence: import 107271918940 -> 2025060921_107271918940.xls; export 308189816340 -> VNG26010020_308189816340.xls). The customer's "PDF chuẩn" means the OFFICIAL printed tờ khai they merge by hand today — not a raw spreadsheet dump.

Decide and tell CO which case applies:
  (A) DH already has a per-declaration print/PDF view (the operator's "in tờ khai"). -> Reuse it; this task is just "render each + concatenate in order". Preferred.
  (B) The .xls is only a data export, no canonical print form. -> DH must decide where the print-standard document comes from: render a standard tờ khai template from the .xls fields, OR pull the official PDF from the customs system. Pick one, render consistently, and document the chosen "PDF chuẩn" definition. Add X-Render-Version header.

Do NOT ship a PDF that is just the .xls grid pasted onto a page if the customer expects the official tờ khai layout — confirm with the CO owner which layout is "chuẩn" if unsure.

## Relationship to the open download.zip defect
This endpoint reads the SAME blobs as GET .../declarations/download.zip, which currently has an open defect: it returns the manifest only and never streams the file bytes (the blobs exist in storage; the handler just doesn't read them). The merge endpoint needs those same blobs, so share the blob-read code and fix both together. If you fix download.zip first, this endpoint reuses that blob-read path to feed the renderer.

## Implementation notes
- Stream / bound memory: don't buffer the whole merged PDF if the set is near the 500 cap; the cookie download route already streams the .xls archive — follow that pattern.
- Page order and visible content must be deterministic for the same inputs (byte-identical not required; embedded PDF timestamps are fine).
- Multi-file declaration: include every file's pages, ordered by filename; reflect that in X-Declarations-Included counting (count by declaration, not by file).

## Acceptance
- download.pdf (Bearer, hub:read, authorized client) for a multi-declaration import set -> 200 application/pdf, one valid PDF, every declaration WITH a file rendered in declaration_no order, headers report requested/included/missing correctly.
- Render fidelity matches the agreed "PDF chuẩn" (case A reuse, or case B documented template) — no data loss vs the source.
- Missing-file declarations excluded from body, listed in X-Declarations-Missing-Nos; PDF still valid.
- Zero/all-missing -> info-page PDF + headers, no crash.
- Auth/param negatives as listed.

## Provider tests (add)
- Bearer + hub:read + matching client, multi-declaration import -> 200 application/pdf; parse the PDF, assert page count ≥ included declarations and order follows declaration_no.
- Single declaration with multiple files -> all files' pages present, ordered by filename.
- sort=registration_date -> order follows registration date.
- Render-fidelity golden test against a known sample declaration.
- Mixed present/missing -> present merged, headers report the missing nos, PDF valid.
- Zero match / all missing -> single info page + headers.
- Negatives: 400 (invalid_direction / declaration_nos_required / too_many / invalid_sort), 401, 403, 404.

## CO side (for context, no DH action)
CO adds an adapter `download_declarations_pdf(client_id, direction, declaration_nos, filename, sort)` mirroring its existing download_declarations_zip, and during dossier export places the merged import/export PDFs into the dossier's numbered slots (e.g. "6. TKN GHEP.pdf"), falling back to the current behavior on any DH error. CO reads the X-Declarations-Missing* headers to warn the operator.

After building, report: which source-document case (A or B) you implemented, the chosen "PDF chuẩn" layout, the final response/headers, and the provider-test results, so CO can verify end-to-end.
```
