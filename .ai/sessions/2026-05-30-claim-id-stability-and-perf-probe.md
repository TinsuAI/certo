# Session: Claim ID stability + /origin perf probe

**Date:** 2026-05-29/30
**Commits:** `2b9c535`, `24d4731`, `cdbeef2` (+ 2 CI commits by user: `5d34ed8`, `ea25b36`)

## What Was Done

### #2 — Guard `data_hub_target_url` against empty deep-link
`_data_hub_overview_context` previously always emitted `data_hub_target_url`
regardless of whether there was a real DH page. `/config` calls it with
`dh_path=""` so the field was an empty URL. `client_context` (legacy path)
never set it at all — old Jinja undefined rendered href="" silently.

Fixed in two layers:
- `_data_hub_overview_context`: only emit the field when `dh_path` is non-empty.
- `client_context` (legacy): explicitly set `data_hub_target_url` for
  catalog/bom/bcct in DH mode, `None` otherwise.
- 4 templates (`bom.html`, `bcct.html`, `catalog.html`, `catalog_table.html`):
  wrap the "Mở trên Data Hub" button in `{% if data_hub_target_url %}`.

One test broke during the change (DH-mode BOM page test asserting button text
was present) — traced to the legacy path not setting the field. Fixed by
setting it in `client_context` for the right tabs. 374→380 tests pass.

### Claim ID stability (carry-over HIGH)
**Problem:** `claim_id_for(case_id, sheet_product_code, source_row, material_index)`
used the material's *position* in the BOM list. Reordering materials changed
every claim's ID, causing the re-lock no-op matcher to emit phantom
`claim_release` + `claim_lock` audit events (net-zero qty but misleading log).
Separately: the INSERT used `on conflict do update set claimed_qty = excluded`
(last-write-wins), which silently dropped qty when one material claimed the
same lot via two allocation lines.

**Discovery findings:**
- Stock totals were NOT corrupted by reorder — re-lock deletes by
  `(client_id, case_id, sheet_product_code)` then re-inserts. The audit log
  was the actual casualty.
- The under-claim bug (overwrite, not sum) was independent of reorder.

**Fix:**
- `claim_id_for` now takes `material_code` as the identity field (positional
  index as fallback only when code is empty).
- Extracted `_build_claim_rows` helper: aggregates allocations per claim_id,
  summing `claimed_qty` on collision. Both the INSERT tuple list and the
  audit-event matcher are built from this.
- No DB migration: `claim_id` is the sole PK; legacy claims replace themselves
  on next lock/release. Stock math never parses the ID.

TDD: 6 DB-free unit tests written first, RED confirmed (ImportError), then
GREEN. 3 Postgres-gated e2e ledger tests pass with local DB.

### /origin perf probe (in-flight, not shipped)
Status.md noted cold /origin ~2.7s. Traced the call graph:
- `co_case_step("origin")` → `co_case_context` → `co_case_light_context`
- `co_case_light_context` calls `co_case_source_context` (DH BCCT pagination)
  then `bom_service.workspace` (DH BOM fetch, only when `bom_product_codes`
  non-empty).
- `preload_co_case_origin_context` runs synchronously on case detail load —
  it warms `source_snapshot` (persisted to case record) and may warm BOM cache
  when case has products.
- `bom_service.workspace` has a 60s in-process TTL cache keyed on
  `(base_url, client_id, token, sorted_product_codes, case_id)`.

Added timing instrumentation (uncommitted) to measure where time is spent:
`[origin-timing]` INFO lines in `co_case_light_context` for source and BOM.
**Measurement not completed** — user ran handoff before clicking Origin.

### `can_view_client` investigation (closed — non-issue)
STATUS carried a note "must use -vn long form on prod". Investigated fully:
- Prod `clients` table is empty — CO loads clients live from DH API.
- `client["id"]` returned by DH is canonical long-form (`growatt-vn`).
- All template URLs use `{{ client.id }}` → always long-form on prod.
- 403 only fires for typed/bookmarked short URLs, not normal UI navigation.
- Seed/demo data (`demo_data.py`) uses short IDs — local dev only.
- Rejected fuzzy-match fix as wrong direction (trades correctness for
  convenience, replicates the existing `_CLIENT_ID_FALLBACK_SUFFIXES` smell
  into the auth layer).

## Decisions Made

- **Claim ID key = material_code, not position.** Stable under reorder.
  Fallback to index only when code is empty (rare, unnamed materials).
- **Sum on collision, not overwrite.** Two allocation lines with the same
  (case, sheet, lot, material) are a merge-and-sum, not a conflict.
- **No DB migration for claim_id.** PK-only, no external references, legacy
  claims self-replace.
- **No DB unique constraint** for new claim identity — deferred by user.
- **`can_view_client` fuzzy-match rejected.** The real fix is one canonical ID
  everywhere, which prod already has. Short IDs are a local-dev artifact.

## What Didn't Work

- Initial proposal to add fuzzy suffix-matching in `can_view_client` — ông
  correctly rejected it as wrong-direction (spreading a hack, not fixing the root).

## Open Items

- **`/origin` perf measurement incomplete.** Timing instrumentation is in
  `app/main.py` (uncommitted). Run local server, open a Johnson case (large
  BCCT), click Origin cold then warm, read log. Then decide: is the bottleneck
  source_context or bom_workspace?
- **Origin lock TTL cleanup** — not started.
- **Customs FX backfill** — not started.
- **Seed missing CO forms** (D/E/AK/AANZ/AJ/RCEP/UKVFTA/VK/VC/VJ) — not started.
- **HS↔form coherence + criteria token validation** — not started.
- **DB unique constraint** for claim identity — user deferred.
