# declarations download.pdf — faster + Ecosys-friendly (compact + split)

**Date:** 2026-06-18
**Status:** Implemented (local). Tests green.
**Requested by:** CO (certificate-of-origin) dossier export.

Two production problems on
`GET /v1/hub/clients/{client_id}/declarations/download.pdf` (and its
cookie mirror). Fix both **without breaking the contract**: with none of
the new params present the response body is byte-for-byte identical to
today; all new headers are additive.

## Problem 1 — too slow

Real case: ~194 import declarations → ~5668-page PDF → ~43–45s, almost
all of it inside soffice rendering the `.xls` to the official layout.

What already existed (verified in code, do NOT re-add):
- **Per-declaration render cache**, content-addressed by source `.xls`
  sha256 + `RENDER_VERSION`
  (`render_cache/declarations/{ver}/{sha}.pdf`). A merge only renders
  cache-misses; warm/overlapping exports are near-instant.
- Response already **streamed from a temp file** via `FileResponse`
  (bounded memory at the HTTP layer; pypdf still builds the merge in
  RAM — unchanged, acceptable).

What this change adds:
1. **Parallel render of cache-misses** — `render_many_xls_to_pdf` now
   splits misses into a bounded pool of concurrent soffice processes
   (each already hermetic: unique `-env:UserInstallation`). Pool size
   `DATA_HUB_RENDER_POOL` (default 4); only parallelizes when misses
   exceed `DATA_HUB_RENDER_MIN_CHUNK` (default 8) so small sets keep one
   cold-start-amortized batch. ~194 cold misses: one 59s batch → ~4
   chunks ≈ 15s wall.
2. **Timing/cache headers** (always, additive): `X-Render-Ms`,
   `X-Render-CacheHits`, `X-Render-CacheMisses`.

## Problem 2 — file too large for legacy Ecosys (~2 MB limit)

Two independent levers, both shipped.

### A. `quality = print | compact`  — pivoted to LOSSLESS (2026-06-18)
- `print` (default) = today, lossless, byte-identical.
- `compact` = **lossless** pypdf object dedup + content-stream
  recompression (`compress_identical_objects` + `compress_content_streams`).
  Profile id `COMPACT_VERSION = "pypdf-dedup-1"`. Guarded: output is
  kept only if smaller than print, so compact ≤ print, never broken.
- **Why the pivot:** the original spec assumed embedded scans → gs image
  downsampling. But the user confirmed **all TKX/TKN arrive as Excel** →
  the rendered PDFs are pure vector (text + grid), **0 images**. Verified
  on real Johnson data: gs `/screen|/ebook|/printer|/prepress` all
  *inflate* (~111-113%); the merged size is **page-count-driven**
  (~5.7 KB/page, 5668 pages ≈ 32 MB). The only real lossless win is
  deduping the font programs duplicated across concatenated declarations
  (one font seen 443× across 25 decls) → ~9% on real data. Ghostscript
  dependency **dropped** (no Dockerfile/CI change); no lossy/legibility
  concern.
- `compact` is **not** the Ecosys fix — it cannot bridge 32 MB → 2 MB.
  `max_part_bytes` split is. compact just trims and composes with split.
- Header `X-Pdf-Bytes` (always); `X-Pdf-Quality` (`print` | `pypdf-dedup-1`).

### B. `max_part_bytes` (size-bounded split)
- Absent → single PDF as today.
- Present → `application/zip` of
  `{stem}-part-001.pdf … part-NNN.pdf`, each ≤ cap, split on
  **declaration boundaries** (never split one declaration), in
  declaration_no order. `stem = declarations_{client_id}_{direction}`.
- A single declaration that alone exceeds the cap → its own part +
  `X-Pdf-Oversize-Nos: <csv>`.
- Packing greedy by per-declaration unit size; each unit is the
  declaration's merged (and, if compact, compacted) PDF. pypdf concat of
  N units is ≤ Σ unit sizes, so `Σ ≤ cap ⇒ part ≤ cap`; a post-write
  verify re-splits any over-cap multi-decl part as a guard.
- Headers `X-Pdf-Parts: <n>`, `X-Pdf-Bytes` (sum of parts).
- Zero included (nothing to split) → single info-page PDF (not a zip).
- CO passes its configurable per-file limit (default 2 MB) and, on a zip
  response, drops parts into dossier slots; falls back to single-PDF on
  any DH error.

## Validation (gs measured)
- raw 700×700 uncompressed-image PDF: **1,470,666 → 27,961 B** (gs ebook).
- tiny vector-only `.xls` render: gs *inflates* 16,833 → 18,433 →
  inflate guard keeps the 16,833 original. (Why the compact provider
  test uses an image-heavy fixture, not the text fixtures, to assert
  `compact < print`.)

## Backward compatibility (hard requirement)
No `quality`, no `max_part_bytes` → identical body to today. Existing
17 provider tests stay green. New headers additive.

## New params validation (same 400 shape as the contract)
- `quality ∉ {print, compact}` → `400 invalid_quality`.
- `max_part_bytes` not a positive int → `400 invalid_max_part_bytes`.

## Tests (`tests/test_declarations_download_pdf_bearer.py`, gs-gated)
- compact: 200 pdf, `X-Pdf-Bytes < print`, text markers survive
  (no field loss), page count preserved.
- `max_part_bytes` over limit: 200 zip, N parts each ≤ limit,
  deterministic names/order, reassemble == single-PDF content;
  oversize declaration → own part + `X-Pdf-Oversize-Nos`.
- `max_part_bytes` under limit (fits) → single application/pdf, no zip.
- cache: first call misses>0; identical second call CacheHits==included,
  lower X-Render-Ms.
- no new params → content-equivalent to pre-change; `X-Declarations-*`
  unchanged.
- negatives unchanged + new `invalid_quality` / `invalid_max_part_bytes`.

## Deployment dep (NEW)
`Dockerfile` + CI now install `ghostscript`. Env knobs:
`DATA_HUB_GS_BIN` (default `gs`), `DATA_HUB_GS_TIMEOUT` (300s),
`DATA_HUB_RENDER_POOL` (4), `DATA_HUB_RENDER_MIN_CHUNK` (8).
Render cache footprint unchanged (compact output is NOT cached — only
lossless per-file renders are; the prune cron at TTL30d/6G still
applies; see render_cache outage 2026-06-12).

## Open questions back to CO
1. Dominant cost = the `.xls`→layout render (soffice), not concat —
   confirmed by code: concat is pypdf, render is the 43–45s.
2. Yes, DH already persists per-declaration renders (content-addressed
   cache); the merge reuses them. This change parallelizes only the
   cold-miss renders.
3. compact profile = gs `/ebook`, images 150 DPI (mono 300), fonts
   subset, XObjects deduped, linearized. Confirm this is accepted as
   legible on the old Ecosys portal before relying on `compact`.
4. Split stays on declaration boundaries; a typical single TKN renders
   well under 2 MB, so 2 MB cap packs many declarations/part and only
   flags a genuinely oversize declaration.
