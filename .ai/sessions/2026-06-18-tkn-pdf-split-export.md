# Session 2026-06-18 (part 2) — TKN merged-PDF split for Ecosys + DH consumption

Continuation of `2026-06-18-client-feedback-criterion-redesign.md`. After the criterion/UI batch
deployed, Data Hub shipped the merged-PDF efficiency endpoint and CO built the consumer side (mục 5).
Commit `30c50f3` (deployed, prod live).

## What Was Done
- **DH responded** to the CO open questions on the PDF-efficiency prompt: dominant cost = `soffice`
  .xls→layout render (not concat); per-declaration render cache already exists (this change only
  parallelizes cold misses); compact = gs `/ebook` 150 DPI (lossy, needs Ecosys legibility sign-off);
  split stays on declaration boundaries (a typical TKN ≪ 2 MB). DH then **deployed** the endpoint.
- **Verified the live DH endpoint** (raw httpx + via adapter, johnson-vn real declarations): single →
  `application/pdf` 235 KB, `X-Render-CacheHits` works; `max_part_bytes=50_000` → `application/zip` 3
  parts (each %PDF) + `X-Pdf-Oversize-Nos`; `quality=compact` → smaller PDF (`X-Pdf-Quality=pypdf-dedup-1`).
- **Built the CO consumer (commit `30c50f3`):**
  - `data_hub_client.download_declarations_pdf`: + `quality` (default `print`), `max_part_bytes`; detects
    `application/zip` (unzip → `parts[]`, `content=None`) vs `application/pdf`; parses new `X-Pdf-*` /
    `X-Render-*` headers. Back-compat: single PDF still sets `content` + a 1-entry `parts`.
  - `co_case._try_fetch_declaration_pdfs`: reads the per-client cap, passes `max_part_bytes`; embeds each
    part as `03-to-khai/{case_code}-to-khai-nhap-part-NNN.pdf` (a single PDF keeps the unsuffixed slot).
  - **Config UI** on the client config page: new "Xuất hồ sơ" section, cap in **MB** (default 2),
    stored on the **client overlay** `client.export_overrides.tkn_pdf_max_part_mb`, handled in the
    CO-side block of `pages.save_client_config_route` BEFORE `require_local_source_writes()`.
- **Tests** (`tests/test_export_pdf_split.py`, 8): adapter quality/max_part_bytes params, single vs
  zip parse, oversize, bad-quality reject; `_try_fetch` embed (split parts + cap→bytes 1.5MB/2MB);
  `create_dossier_zip` embeds parts under `03-to-khai/`; route persists cap to `export_overrides`
  (mock store, source-guard off). Full suite **610 pass**.
- **End-to-end vs live DH:** fetched real split bytes → `create_dossier_zip` → unzipped: 2 MB cap → 1
  file `03-to-khai/…nhap.pdf` (235 KB); 50 KB cap → 3 files `…part-001/002/003.pdf`, all valid %PDF.

## Decisions Made
- **Default `print` (lossless) + 2 MB split** (user-approved). `compact` is wired in the adapter but
  intentionally **not exposed in the UI** — it's lossy and needs the user to confirm Ecosys legibility
  first. Lossless split alone solves the size problem (a TKN ≪ 2 MB packs many per part).
- **Config lives on the client OVERLAY, not `client_config`** — the careful-discovery payoff: DH
  source-mode is ON (`.env DATA_HUB_ENABLED=1`), so `require_local_source_writes()` 409s `client_config`
  saves. The CO-side cap must be editable in source-mode → store it like `min_days_before_export`
  (client object via `app_state_store`, handled before the guard). First built it in `client_config`,
  then reverted after discovering the 409.
- **Cap stored in MB** (human-friendly UI), converted to bytes (× 1e6) at the DH call.
- **Split-part embed reuses the existing `declaration_pdfs` dict** — `create_dossier_zip` keys by
  filename, so N parts = N entries; no signature change.

## What Didn't Work
- First placed the cap in `client_config` (store + migrate + validate + template + route) — **reverted**
  after the live POST returned **409** (`require_local_source_writes` blocks client_config saves in DH
  source-mode). The client-overlay approach (like min_days) is the correct, source-mode-safe placement.
- **Deploy gotcha (carried from part 1):** a commit body containing the literal CI-skip token (even in
  "No [skip ci]: …") made GitHub skip the whole pipeline → prod didn't deploy. Fixed with an
  `--allow-empty` re-trigger commit. Now a saved lesson.
- Could not exercise the route persistence against a **live Postgres** this session (dev DB `/clients`
  was 503; `get_app_state_store()` is Postgres-only so file-mode doesn't persist). Covered by a unit
  test (mock store) + the pattern being identical to the working `min_days` path.

## Open Items
- `compact` UI toggle — deferred until the user confirms Ecosys accepts the gs /ebook 150 DPI output.
- Route persistence not verified against live Postgres (unit-tested + pattern-identical to min_days).
- Pre-existing: config-page POST 409 in source-mode (CO-side fields persist before the guard, but the
  response is a 409) — affects min_days too; clean UX is a separate fix.
- EX1 (configurable column-K ref) and XX1 (origin NVL → M-N) remain in the backlog.
- Mục 6 (BOM default per-client) and mục 4a (cost-allocation) not started.
