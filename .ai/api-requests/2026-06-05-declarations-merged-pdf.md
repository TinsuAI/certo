# Data Hub API Request: merged declarations PDF (TKX / TKN ghép)

## Use Case
When an operator exports a closed CO dossier, customers want the related
**TKX (export) and TKN (import) declaration files merged into a single
standard PDF per direction** — e.g. one `6. TKN GHEP.pdf` for all import
declarations and one `1. TKX.pdf` for all export declarations — instead of a
folder of separate per-declaration files. Today operators produce these
merged PDFs by hand (print each tờ khai, then concatenate).

The dossier already uses a numbered-slot PDF convention
(`app/demo_data.py`: `1. TKX.pdf`, `2. BL.pdf`, `5. QUY TRINH ….pdf`,
`7. INV + PBO.pdf`). CO wants to drop the merged TKX/TKN PDFs straight into
those slots during `export-dossier-zip`.

CO cannot do the merge itself:
- The source declaration files are **`.xls`, not PDF** (prod evidence below),
  so "merge into a standard PDF" requires rendering each `.xls` to a faithful,
  print-standard PDF first — that rendering is Data Hub-domain knowledge of the
  customs declaration document, not CO business logic.
- The file blobs live **only in Data Hub**; CO has no access to them today
  (the Bearer `download.zip` is manifest-only — open defect
  `2026-06-04-declarations-download-zip-missing-file-bytes.md`).
- CO has **no PDF tooling** (no pypdf/reportlab/weasyprint) and would otherwise
  re-implement customs-document rendering already owned by DH.

A canonical merged-declaration PDF in DH is reusable by any consumer and keeps
a single, consistent "PDF chuẩn" definition.

## Existing Endpoint Gap
- `GET /v1/hub/clients/{client_id}/declarations/download.zip` (Bearer) —
  returns the raw per-declaration files in a ZIP (and currently omits the bytes
  — separate defect). Even once fixed it returns separate `.xls` files, not a
  merged PDF. CO cannot render/merge `.xls`.
- `GET /v1/hub/clients/{client_id}/declarations` (Bearer) — metadata only
  (`file_count`, `earliest_bcct_date`), no document rendering.
- No DH surface returns a rendered or merged declaration PDF.

## Proposed Contract
**Method and path:**
`GET /v1/hub/clients/{client_id}/declarations/download.pdf`

(Mirrors `download.zip` so CO reuses the same query-builder + auth path.)

**Query parameters:**
- `direction` — required — `import` (TKN) or `export` (TKX).
- `declaration_nos` — required — comma-separated, ≤ 500 entries.
- `filename` — optional — preferred `Content-Disposition` filename; default
  `declarations_{client_id}_{direction}.pdf`.
- `sort` — optional — `declaration_no` (default) or `registration_date`.

**Request body:** none (GET).

**Response body:**
- `200` — `application/pdf`, a **single merged PDF**:
  - One declaration after another, in `sort` order (default `declaration_no`
    ascending), deterministic.
  - Each declaration rendered to the standard print layout of the tờ khai
    (A4). A declaration with multiple files contributes all its pages, ordered
    by filename.
  - Declarations with **no file** are skipped from the body and reported via
    response headers (below) — never inserted as a blank/error page unless
    `include_manifest=true`.
  - `Content-Disposition: attachment; filename="…"`.
- **Response headers (so CO can warn the operator about gaps):**
  - `X-Declarations-Requested: <n>`
  - `X-Declarations-Included: <n>`
  - `X-Declarations-Missing: <n>`
  - `X-Declarations-Missing-Nos: <comma-separated, ≤ first 50>`
- **Zero match / all missing** — `200` with a single well-formed info page
  ("Không có tờ khai có file") + the headers above. Never an empty/corrupt PDF.

**Error cases:**
- `400 invalid_direction` — direction not `import`/`export`.
- `400 declaration_nos_required` — empty/missing.
- `400 too_many_declaration_nos` — > 500.
- `400 invalid_sort` — sort not in allowed set.
- `401` — bearer token required / invalid.
- `403 forbidden` — token cannot view the client.
- `404 client not found`.

## Auth
**Required scope:** `hub:read` (same as `declarations` / `download.zip`; this is
read-only rendering, no mutation).

**Client scoping rule:** token must be authorized for `client_id` (same check
as `download.zip`); files scoped to that client only.

**Token type:** Bearer (operator JWT forwarded by CO, or service token).

## Data Semantics
**Source of truth:** the customs declaration files DH stores
(`hub.customs_declaration_files` blobs, same rows `download.zip` lists). The
merged PDF is a rendering of those exact blobs.

**Precision requirements:** faithful, lossless rendering of each declaration's
content; deterministic page order; standard A4 layout. Page content stable for
the same inputs (byte-stability not required — PDF producers may embed
timestamps — but page order and visible content must be deterministic).

**Pagination:** none; single PDF, ≤ 500 declarations per call (same cap as
`download.zip`). CO batches if a dossier exceeds 500 per direction.

**Idempotency:** GET, safe and idempotent; no side effects.

**Versioning or pinning:** none; reflects current stored files. If DH later
changes the canonical render, bump a `X-Render-Version` header so CO can note
it in the dossier.

## ⚠️ Open question / feasibility risk (DH must confirm before building)
The customer's "PDF chuẩn" is the **official printed tờ khai** (what they merge
by hand today). The stored source is `.xls`. DH must confirm whether it can
produce that official-looking printout from what it stores:
- **If** DH already has a per-declaration print/PDF view (e.g. the operator's
  "in tờ khai") → reuse it; this request is just "render those + concatenate".
- **If** the `.xls` is only a data export (not the printable form) → DH needs to
  decide where the print-standard document comes from (render a standard
  template from the `.xls` fields, or pull the official PDF from the customs
  system). CO defers entirely to DH on this; we only need the merged PDF out.

Also: this endpoint reads the same blobs as `download.zip`, so it depends on DH
being able to access those blobs — the same access path blocked by defect
`2026-06-04-…-missing-file-bytes`. Fixing that defect and building this should
share the blob-read code.

## Tests Required In Data Hub
**Provider tests:**
- Bearer + `hub:read` + matching client, multi-declaration import →
  `200 application/pdf`, single valid PDF, all declarations with files rendered
  in `declaration_no` order; `X-Declarations-Included` == count with files.
- Single declaration with multiple files → all files' pages present, ordered by
  filename.
- `sort=registration_date` → page order follows registration date.
- Render-fidelity golden test: a known sample declaration renders to the
  expected standard layout (no data loss vs the `.xls`).

**Negative tests:**
- `400` for invalid_direction / declaration_nos_required / too_many /
  invalid_sort.
- `401` no/invalid bearer; `403` client not authorized; `404` unknown client.

**Edge cases:**
- Mixed (some have files, some don't) → present files merged; missing reported
  in `X-Declarations-Missing*` headers; PDF still valid.
- Zero match / all missing → single info page + headers, valid PDF.
- Large set near the 500 cap → streams without buffering whole PDF in memory.

## CO Consumer Plan
**Adapter method to add in `app/data_hub_client.py`:**
`download_declarations_pdf(client_id, *, direction, declaration_nos, filename=None, sort="declaration_no") -> bytes`
— mirrors `download_declarations_zip`; returns raw PDF bytes; reads the
`X-Declarations-Missing*` headers to surface gaps.

**Call sites that will consume the adapter:**
- `app/routers/co_case.py::export_co_case_dossier_zip` — after building the
  TKX/TKN summary, fetch the merged import + export PDFs and place them in the
  dossier as the numbered slots (`1. TKX.pdf`, `6. TKN GHEP.pdf` — direction →
  slot name mapping in CO). Falls back to current manifest/zip behavior on any
  DH error (same defensive pattern as `_try_fetch_declaration_archives`).

**Consumer tests:**
- Container-side probe: `download_declarations_pdf` returns `%PDF` bytes and a
  page count ≥ included declarations.
- Dossier assembly test: merged PDFs land in the correct numbered slots; gap
  headers produce an operator warning; DH-down falls back without 500.

## Approval
**Data Hub contract owner:** _pending_

**Approval date:** _pending_

**Data Hub commit:** _pending_

## Status — shipped + verified (2026-06-06)
DH shipped the endpoint (implemented **case A**: official tờ khai render, not a
raw `.xls` grid). CO verified against the configured DH (`DATA_HUB_API_BASE_URL`,
client johnson-vn):
- import/export → 200 `application/pdf`, official "Tờ khai hàng hóa
  nhập/xuất khẩu (thông quan)" layout, A4.
- Merge + ordering by `declaration_no` asc; `X-Declarations-Requested/Included/
  Missing/Missing-Nos` correct; missing/bogus → 1-page info PDF; dedup; 400
  (invalid_direction / declaration_nos_required / too_many / invalid_sort);
  401; `sort=registration_date` accepted.

**CO consumer — implemented:**
- `app/data_hub_client.py::download_declarations_pdf` (returns
  `{content, requested, included, missing, missing_nos}`).
- `app/routers/co_case.py::_try_fetch_declaration_pdfs` → dossier embeds
  `03-to-khai/TKX-ghep.pdf` / `TKN-ghep.pdf`; skips a direction with zero
  included files; falls back to manifest mode on any DH error.
- `create_dossier_zip(..., declaration_pdfs=...)`.
- Endpoint registered in `tests/test_data_hub_policy.py` allowlist.
- Tests: `tests/test_dossier_zip_bearer_probe.py` (adapter validation, header
  parse, dossier embed); full suite green. End-to-end checked with real DH
  bytes → valid embedded PDFs.

Remaining: final end-to-end check once this DH endpoint is on prod DH (CO prod
dossier export uses the service-token path).
