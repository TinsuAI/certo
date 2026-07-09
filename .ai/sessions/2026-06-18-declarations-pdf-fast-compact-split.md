# Declarations download.pdf — faster + compact + split (shipped v0.19.0)

**Date:** 2026-06-18
**Outcome:** Built → real-data verified → PR #11 → merged → released **0.19.0** →
deployed to prod (live at git_sha `589bdae`, build 05:51).

## What Was Done

CO asked to fix two prod problems on
`GET /v1/hub/clients/{client_id}/declarations/download.pdf` (+ the cookie mirror)
without breaking the contract.

- **Problem 1 (slow — ~194 decls ≈ 43–45s):** cache-miss renders now run in a
  **bounded parallel soffice pool** (`render_many_xls_to_pdf`,
  `DATA_HUB_RENDER_POOL`=4, min-chunk `DATA_HUB_RENDER_MIN_CHUNK`=8). Measured
  ~2.8× on heavy fixtures. The content-addressed render cache (sha256 +
  `RENDER_VERSION`) and the temp-file `FileResponse` streaming already existed —
  NOT re-added. Added `X-Render-Ms` / `X-Render-CacheHits` / `X-Render-CacheMisses`.
- **Problem 2 (too large for legacy Ecosys ~2 MB):**
  - `quality=print|compact`. **compact = LOSSLESS** pypdf object dedup +
    content-stream recompression (`compress_identical_objects` +
    `compress_content_streams`, profile `pypdf-dedup-1`), guarded ≤ print.
  - `max_part_bytes` → `application/zip` of declaration-boundary parts each ≤
    cap, declaration_no order; a declaration alone over cap → its own part +
    `X-Pdf-Oversize-Nos`. Split decision is on the **merged-PDF size** (fits →
    single PDF). Headers `X-Pdf-Bytes`/`Parts`/`Quality`.
- **Fixed a PRE-EXISTING ZIP flake** (surfaced on PR CI, unrelated to PDF):
  `_build_declarations_zip` used `writestr(str, data)` → wall-clock entry mtimes
  → the bearer-vs-cookie byte-identity test flaked when two requests straddled a
  1-second boundary. Now writes via `ZipInfo` with fixed mtime `(1980,1,1,…)` +
  DEFLATE → reproducible. Applied to `download.zip` AND the new split-zip.
- Files: `app/declarations_pdf.py`, `app/routes/declarations.py`,
  `app/routes/api.py`, `tests/test_declarations_download_pdf_bearer.py` (+25
  cases), `docs/API_CONTRACT.md` (endpoint now documented), `docs/API_CHANGELOG.md`
  (Additive 2026-06-18), `CHANGELOG.md`,
  `.ai/features/2026-06-18-declarations-pdf-fast-compact-split/brief.md`.

## Decisions Made

- **compact = lossless dedup, NOT ghostscript image downsampling.** The original
  CO spec assumed embedded scans → gs `/ebook` at 150 DPI. The user corrected:
  **all TKX/TKN arrive as Excel** → rendered PDFs are pure vector (0 images).
  Verified on real Johnson data: gs `/screen|/ebook|/printer|/prepress` all
  INFLATE (~111–113%); merged size is **page-count-driven** (~5.7 KB/page, 5668
  pages ≈ 32 MB). The only lossless win is deduping fonts duplicated across
  concatenated declarations (one font referenced 443× across 25 decls) → ~9%.
  → **Ghostscript dependency dropped entirely** (Dockerfile/CI reverted to
  net-zero). Memory saved: `project_declarations_all_excel_vector`.
- **Split is the real Ecosys fix, compact is not** — compact can't bridge
  32 MB → 2 MB; `max_part_bytes` does.
- **Backward compat:** the no-param path keeps the original single-pass merge
  verbatim → byte-for-byte identical; all new params/headers additive.
- **Per-declaration units serve both single + zip paths**, compacted in
  parallel — avoids a throwaway whole-document compaction in the split case.
- **Release/branch hygiene:** branched off `main` (not the in-flight docs
  branch); merge-commit per repo convention; cut 0.19.0 as a `chore(release)`
  touching only `pyproject.toml` + `CHANGELOG.md`.

## What Didn't Work

- **gs `/ebook` compact** — fully built first (gs image-downsample, inflate
  guard, ghostscript added to Dockerfile + CI, image-fixture tests showing 53×
  on raw-image PDFs), then **ripped out** after the all-Excel finding. The
  raw-image test fixture became irrelevant; rewrote the compact test to use
  duplicate-heavy declarations (4 same-blob decls → dedup 32%).
- **Branch base trap:** after `gh pr merge`, the local `origin/main` ref was
  stale; `git merge --ff-only origin/main` reported "up to date" while the
  working tree showed pre-feature code. Fix: `git fetch` first, confirm
  `git log` shows the merge commit + feature code BEFORE cutting the release.

## Open Items

- **CO question (in PR #11):** do dossiers ever carry embedded raster scans
  (`file_kind=pdf` uploads)? If yes, reconsider an optional image-downsample
  profile alongside the lossless compact.
- Johnson `material_group` prod backfill still pending (carry-over 2026-06-17).
- `docs/agency-staff-guide` branch (`d5ae3ab`) still unpushed/unmerged.
