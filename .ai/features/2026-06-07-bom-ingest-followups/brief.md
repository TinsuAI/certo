# BOM ingest follow-ups (backlog B)

**Date:** 2026-06-07
**Scope:** Four open BOM-ingest backlog items closed in one pass. Most of
section B was already shipped before the 2026-05-13 audit lag; these were
the genuine remainders.

## What shipped

### B.1.5 — adapter `detect()` / match_score ranking
- New optional `detect(blob, *, root_code) -> float | None` on the
  `BomAdapter` Protocol. `parse_with_fallback` now ranks candidates:
  adapters returning a positive score are tried first (highest score wins,
  registration order breaks ties); abstaining adapters (`None`) keep
  registration order **after** them.
- **No regression by construction:** when no adapter implements `detect`
  (or all abstain), the ranked order equals registration order — identical
  to prior behaviour. Verified by `test_detect_abstain_preserves_registration_order`.
- `detect` implemented on the two deep-tree adapters:
  `sap_indented_walk` (0.95, fires on Level+Component & no product_code)
  and `sap_exploded_levels` (0.9, fires on material_code + Level). This
  fixes the ambiguity where a multi-level file (Level column) was grabbed
  and silently flattened by the more permissive `manual_flat` (registered
  earlier). Other adapters abstain; add `detect` as needed.
- Files: `app/parsers/bom_adapters/__init__.py`,
  `app/parsers/bom_adapters/sap_exploded_levels.py`,
  `app/parsers/bom_adapters/sap_indented_walk.py`.

### B.2.5 — multi-role warning at upload
- `app/stores/bom_multirole.py::compute_multirole_warnings(client_id, products)`
  flags upload component codes already present in
  `bcct_rows.direction='export'` for the client — a code that is both an
  exported finished good and a BOM sub-component (multi-role).
- Advisory only (non-blocking, like `multi_level_flat`). Rendered as a red
  panel in `bom_preview.html`; wired into `preview_view`.
- Matches on `customs_code` only — shares the A.5 paren-code blind spot
  (acceptable for an advisory). See `project_bom_code_multirole.md`.

### B.3 — friendly parse-error UX (BOM side)
- The 5 parse-error `HTTPException(400)` sites in
  `bom.py::upload_submit` (auto-no-match, technical_raw, rigid,
  LLM-unavailable, LLM-mapping-rejected) now return `_render_parse_error()`
  → `clients/bom_upload_error.html`. Status stays 400; body is friendly
  HTML with recovery options + a re-upload link instead of raw
  `{"detail": ...}` JSON.
- The `Invalid profile` guard stays a bare 400 (input validation, not a
  file-content problem). BQD/Catalog parse-error paths remain open.

### B.2.7 — regression coverage
- `tests/test_bom_ingest_followups.py` (8 tests): detect ranking (both
  directions), multi-role store + preview render, HTML-not-JSON parse
  error, and auto upload→preview→confirm end-to-end.

## Verification
- Full suite: **1389 passed, 16 skipped** (was 1381 + 8 new).
- Screenshots (live dev server :8754) in `screenshots/`:
  - `01_multirole_warning.png` — preview panel listing exported component.
  - `02_detect_ranking_sap_exploded.png` — ambiguous Level-column file
    resolving to `sap_exploded_levels` (summary header shows the adapter),
    not `manual_flat`.
  - `03_friendly_parse_error.png` — styled 400 error page with recovery.
- Repro: `uv run python -m scripts.screenshot_bom_ingest_followups`.

## Not done (still open)
- B.1 item 3 (extract standalone ingest scripts into adapter classes) —
  deemed not worth it (session 2026-05-29): CLI scripts and UI adapters
  serve different purposes.
- B.2 items 1-6 were already shipped pre-audit; B.2.7 has pytest coverage
  but no browser-level Playwright E2E.
- B.3 for BQD/Catalog upload paths.
