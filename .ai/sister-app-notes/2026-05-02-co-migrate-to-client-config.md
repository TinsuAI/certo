# Notes for CO repo (barry-CO-main)

**Provider:** Data Hub  ·  **Consumer:** CO  ·  **Date:** 2026-05-02

Posted from Data Hub side — to be picked up by an agent inside `~/workspace/client/barry-CO-main` and turned into a real CO PR. **Do not auto-merge.** Read `docs/API_CHANGELOG.md` in the Data Hub repo for the canonical breaking change.

## What changed in Data Hub

- Added `GET /v1/hub/dncxs/{id}/client-config` (consumer-agnostic master config).
- Deprecated `GET /v1/hub/dncxs/{id}/co-config`. Sunset: **2026-05-16**.
- Removed `co_stock_row_count` + `co_stock_row_count_semantics` from `/source-summary`.
- New per-client master data: `eligible_import_declaration_types`, `relevant_export_declaration_types`, `fiscal_year_start_month`.
- Backfill from CO local JSON (`data/local/client-config/clients/*/config.json`) already done on Data Hub side via `scripts/backfill_client_config_from_co.py`. Master fields are now in `hub.client_config`.

## What CO must do before 2026-05-16

1. **Switch the read path** in `app/data_hub_client.py` (and any direct callers in `app/main.py`, `app/portfolio.py`, `app/co_case_store.py`):
   - `GET /v1/hub/dncxs/{id}/co-config` → `GET /v1/hub/dncxs/{id}/client-config`.
   - Read `eligible_import_declaration_types` / `relevant_export_declaration_types` / `fiscal_year_start_month` directly from top-level (no longer nested under `bcct.*`).
   - `co_stock.lot_policy`, `allocation_code.*` are gone from the response.

2. **Move CO-runtime config to CO local store only.** `app/client_config_store.py` is the right home for:
   - `co_stock.lot_policy`
   - `allocation_code.strategy` / `description_regex` / `fallback`

   Drop the master fields (`eligible_import_declaration_types`, `relevant_export_declaration_types`, `declaration_type_preset`) from CO local store — those come from Data Hub now.

3. **Drop the 2 declaration-type rows** from `/clients/{id}/config` UI in `app/templates/client_config.html`. Keep:
   - Tồn C/O → policy lot (kept; CO-runtime).
   - Mã phân bổ → strategy / regex / fallback (kept; CO-runtime).

   Remove or redirect the section editing eligible/relevant declaration types — staff edits those at Data Hub now (`/clients/{id}/declaration-config`).

4. **Allocation `code_resolution_mode`** — read from `/v1/hub/dncxs/{id}` `code_resolution_mode` field, not from `/co-config`.

5. **Cache invalidation** — compare `config_hash` on each fetch; drop derived state when it changes.

6. **Update test fixture** at `tests/test_data_hub_integration.py:493` — match new `/client-config` shape.

7. **Stock counters in CO** — replace `source_summary["co_stock_row_count"]` reads with CO's own filtered query against `/v1/hub/bcct?direction=import&...`. Apply the `eligible_import_declaration_types` filter from `/client-config` to compute usable stock locally.

## Useful URLs (Data Hub)

- New endpoint contract: `docs/API_CONTRACT.md` "Client Config (master data)" section.
- Breaking change entry: `docs/API_CHANGELOG.md` "2026-05-02 — Breaking".
- Data Hub UI: `/clients/{id}/declaration-config` (where staff now edit the declaration type config).

## Risk

- CO production calls keep working during the grace window because Data Hub keeps `/co-config` serving the legacy shape (now backed by `hub.client_config` for master fields). After 2026-05-16 the old endpoint returns 410 Gone — CO must be cut over by then.
