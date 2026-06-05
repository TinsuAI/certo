# Declarations merged "tờ khai ghép" PDF (download.pdf)

**Date:** 2026-06-06
**Status:** Implemented (local), tests green. Deploy needs LibreOffice in the image (Dockerfile updated).
**Requested by:** CO (certificate-of-origin) service — server-side dossier builder.

## Problem

Operators file a single merged PDF of all a client's import (TKN) or
export (TKX) customs declarations with HQ (e.g. `6. TKN GHEP.pdf`).
Today they **print each declaration and concatenate by hand**. CO wants
to fetch this server-side and drop it into a numbered dossier slot.

## Endpoint

`GET /v1/hub/clients/{client_id}/declarations/download.pdf` (Bearer,
`hub:read`) — mirror of the operator cookie route
`GET /clients/{client_id}/declarations/download.pdf` (also added; bounces
to `/login?next=` when unauthenticated). Mirrors `download.zip` for auth,
client scoping, query parsing, and the 500 cap.

Query params:
- `direction` **required** — `import` (TKN) | `export` (TKX)
- `declaration_nos` **required** — comma-separated, ≤ 500, deduped, order preserved
- `filename` optional — Content-Disposition filename; default `declarations_{client_id}_{direction}.pdf`
- `sort` optional — `declaration_no` (default) | `registration_date`

Response: `200 application/pdf`, one merged PDF. Each declaration rendered
to the standard A4 tờ khai layout, one after another in `sort` order;
within a declaration, every file's pages in `original_filename` order.
Declarations with no usable file are **skipped from the body** and
reported via headers:

```
X-Declarations-Requested:   <n>
X-Declarations-Included:    <n>   # declarations contributing ≥1 page
X-Declarations-Missing:     <n>
X-Declarations-Missing-Nos: <comma-sep, first 50>
X-Render-Version:           soffice-1
```

Zero match / all missing → `200` with a single info page
("Không có tờ khai có file…") + the headers above. Never empty/corrupt.

Errors (same shape as download.zip): `400 invalid_direction |
declaration_nos_required | too_many_declaration_nos | invalid_sort`;
`401` bearer; `403` forbidden / scope / client-whitelist; `404` client
not found.

## Source-document decision — **Case B** (documented "PDF chuẩn")

DH has **no** pre-existing per-declaration print/PDF view, and added no
PDF library before this. So this is Case B. But the key finding:

**The stored per-declaration `.xls` is NOT a raw data export — it IS the
official ECUS/VNACCS print form laid out as a spreadsheet.** Sheet
`TKN`/`TKX` carries the `<IMP>`/`<EXP>` watermark, the `Số tờ khai`
grid, per-line `<01>`/`<02>` blocks, and the page `X/N` marker. A
supplementary `HANG` data sheet sits beside it (no print area, excluded
from print).

**"PDF chuẩn" definition:** the stored `.xls` rendered to PDF by
**LibreOffice headless** (`soffice --convert-to pdf`). That reproduces
exactly the document the operator prints and merges by hand today —
verified byte-for-layout against the customer sample `6. TKN GHEP.pdf`
(same watermark, grid, fonts, page count; `HANG` correctly excluded).
This avoids the "grid pasted onto a page" anti-pattern: we render the
official form, not a spreadsheet dump.

## Architecture

- **Renderer** (`app/declarations_pdf.py`): `soffice --headless
  --convert-to pdf` with a unique per-call `-env:UserInstallation`
  profile (concurrency-safe, hermetic). Batches all `.xls` in one
  invocation to amortize cold start (~1s + ~0.3s/file).
- **Cache:** content-addressed by source `.xls` sha256 →
  `render_cache/declarations/{RENDER_VERSION}/{sha}.pdf` on the
  FileBackend. `RENDER_VERSION` is part of the key, so bumping it
  invalidates old entries transparently.
- **Pre-render then merge** (per 2026-06-06 decision "print trước, demand
  thì nối"): per-declaration PDFs are pre-rendered into the cache; the
  merge endpoint just concatenates cached PDFs with `pypdf`, streamed
  from a temp file (bounded memory) via `FileResponse`. **Lazy fallback:**
  a cache miss renders on-the-fly at request time, so correctness never
  depends on a warm cache.
- **Warming:** (1) best-effort pre-render on single declaration upload
  (`upload_declaration_file`); (2) `scripts/backfill_declaration_pdfs.py`
  for existing files + bulk-ZIP commits (which skip inline warming to
  keep commits fast). Idempotent, batched.
- **`pdf` file_kind** passes through unchanged (operator-uploaded real
  PDFs); `scan`/`other` contribute nothing (and count as missing if a
  declaration has only those).

## Deployment dependency (NEW)

`Dockerfile` now installs `libreoffice-calc` + `fonts-liberation
fonts-dejavu-core` (`--no-install-recommends`, no JRE). Adds ~a few
hundred MB to the image. Env knobs: `DATA_HUB_SOFFICE_BIN` (default
`soffice`), `DATA_HUB_SOFFICE_TIMEOUT` (default 180s). After deploy, run
the backfill once to warm existing declarations:
`docker exec data-hub-app-1 python scripts/backfill_declaration_pdfs.py`.

## Relationship to download.zip

`download.zip` already streams the real blob bytes (`backend.get`) — the
"manifest-only" defect referenced in the task was fixed 2026-06-04. The
merge endpoint reads the **same** blobs via the same store
(`list_files_for_declarations`) + FileBackend, so no dual fix was needed.

## Tests

`tests/test_declarations_download_pdf_bearer.py` (synthetic 2-sheet
`.xls` fixtures via xlwt, real soffice renders, pypdf assertions):
- multi-declaration import → 200, pages ≥ included, declaration_no order
- single declaration / multiple files → all pages, filename order
- `sort=registration_date` → order follows BCCT registration date
- mixed present/missing → present merged, missing nos in header, valid PDF
- zero / all-missing → single info page + headers
- default + sanitized custom filename
- negatives: 400 (invalid_direction / declaration_nos_required /
  too_many / invalid_sort), 401, 403 (scope + client whitelist), 404
- **render-fidelity golden** (env-gated `DATA_HUB_REAL_DATA_DIR`): real
  ECUS `.xls` → official layout (`<IMP>`/`<EXP>` + title present).

Result: **17 passed, 1 skipped** (golden skipped without real-data env);
golden **passes** against `data/source_inventory/johnson-vn/.../TKN`.

## CO side (no DH action)

CO adds `download_declarations_pdf(client_id, direction, declaration_nos,
filename, sort)` mirroring its `download_declarations_zip`, places the
merged import/export PDFs into numbered dossier slots (e.g.
`6. TKN GHEP.pdf`), reads `X-Declarations-Missing*` to warn the operator,
and falls back to current behavior on any DH error.

## Done criteria

- [x] Bearer + cookie endpoints, hub:read scope, client-scoped
- [x] Merge in sort order; multi-file by filename; missing skipped+reported
- [x] Headers: Requested/Included/Missing/Missing-Nos + Render-Version
- [x] Zero/all-missing → info page, never empty/corrupt
- [x] Fidelity = official tờ khai (Case B, LibreOffice), verified vs sample
- [x] Pre-render + cache + lazy fallback; backfill script; upload warm
- [x] Provider tests green; Dockerfile installs LibreOffice
- [ ] Deploy to prod + run backfill (next session / on user go-ahead)
