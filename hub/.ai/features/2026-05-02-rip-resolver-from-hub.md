# Feature: Rip BCQT-flavored code resolver out of Data Hub (Option B-lite)

**Date:** 2026-05-02 (post-RBAC)
**Status:** Approved by user after critic review.
**Trigger:** Critic surfaced that `app/stores/code_resolution.py`:
1. Hosts a settlement-flavored algorithm in master-data app (cross-app coupling).
2. Is a *lossy port* of `bcqt-growatt/settlement/code_map.py` — collapses NVL/TP into single `direction='import'`, so resolved_customs_code stored in hub is **wrong for TP** today.
3. Is read by no actual consumer in the public read API (read API exists but no real client; CO doesn't use it; BCQT-System hasn't migrated yet).

Window to rip cleanly is now (zero API users) — cost grows weekly.

## Scope

**Drop from hub:**
- `hub.code_mapping_resolutions` table (migration 003).
- `bcct_rows.resolved_customs_code` column + `idx_bcct_resolved` index (migration 005).
- `app/stores/code_resolution.py` module (move to `scripts/settlement_resolver.py` as a CLI tool; not imported by `app/`).
- All callers in routes (`bcct.py`, `bqd.py`), seed (`seed.py`), api (`api.py`).
- BQD page resolutions panel + manual "Resolve" button.
- `tests/test_code_resolution.py` (5 tests — they test removed code; equivalent tests get rebuilt in BCQT when it migrates).
- API endpoint `/v1/hub/resolutions` (no consumers).
- API field `resolved_customs_code` on `/v1/hub/bcct/*` endpoints (no consumers).

**Keep at hub:**
- `app/parsers/goods_name.py` — genuine ingestion (extract internal_code from BCCT goods_name at upload time). Hub-job.
- `hub.code_mappings` table (BQD pairs) — master data.
- `bcct_rows.internal_code` column — populated by parser at ingestion.
- `code_resolution_mode` field on `hub.clients` — still meaningful (controls parser pick: identity vs growatt).
- `/v1/hub/bcct/*` endpoints (without resolved_customs_code).

**Move out (to `scripts/settlement_resolver.py`):**
- The full `resolve_for_dncx` algorithm + helpers, refactored to write to a sandbox/file output (no longer touches hub schema). When BCQT migrates to consumer mode, this script gets ported into BCQT, fixed for NVL/TP split, and stored in BCQT-side state.

## Migration 009 (`009_rip_resolver.sql`)

```sql
drop index if exists hub.idx_bcct_resolved;
alter table hub.bcct_rows drop column if exists resolved_customs_code;
drop table if exists hub.code_mapping_resolutions;
```

Note: `hub.code_mappings` (BQD pairs) STAYS. Only the materialized resolution + denormalized projection are dropped.

## File changes

| File | Action |
|---|---|
| `db/migrations/009_rip_resolver.sql` | NEW |
| `app/stores/code_resolution.py` | DELETE (after move) |
| `scripts/settlement_resolver.py` | NEW (CLI tool — destined for BCQT) |
| `app/routes/bcct.py` | Remove resolver import + call (line 13, 83). |
| `app/routes/bqd.py` | Remove resolver import + 2 calls (lines 12, 85, 101); remove `trigger_resolve` route (92-98); remove `_list_resolutions` helper (173+); remove `resolutions` template var. |
| `app/routes/api.py` | Remove `lookup_resolution` import (line 23); remove `api_list_resolutions` endpoint (219+); remove `resolved_customs_code` from BCCT response columns (lines 142, 179). |
| `app/seed.py` | Remove resolver import + 2 calls (lines 15, 145, 280). |
| `app/templates/clients/bqd.html` | Remove resolutions panel + "Resolve" button. |
| `tests/test_code_resolution.py` | DELETE. |

## i18n cleanup

Search for keys mentioning resolution panel: `bqd.resolutions_*`, `bqd.resolve_button`, etc. Remove if found.

## Test plan

1. Migration 009 applies cleanly — DROP table + column.
2. `uv run pytest -q` passes (40 tests after dropping 5 resolution tests).
3. `uv run python -c "from app.main import app"` boots without import errors.
4. Manual: server starts, `/clients` loads, BQD page loads (no panel/button), uploads still work (no resolver crash), seed runs cleanly on empty DB.
5. Curl API: `/v1/hub/bcct` returns rows without `resolved_customs_code` field; `/v1/hub/resolutions` returns 404.

## Done criteria

- Migration 009 in place + applied.
- All 9 files modified per above.
- pytest green.
- Server boots + auto-seed works.
- 27 screenshots: BQD screenshot may show no resolutions panel (re-take or accept one missing pixel diff).
- STATUS.md updated.
- DECISIONS.md gets new entry: "2026-05-02 Settlement resolver moved out of hub".
- Session summary written.
