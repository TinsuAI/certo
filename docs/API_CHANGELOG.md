# Data Hub API Changelog

Append-only, dated record of contract changes to `/v1/hub/*`. Sister apps (CO, BCQT) consume this as the change-detection source of truth alongside `docs/API_CONTRACT.md`.

## Heading conventions

Each entry must use one of these heading prefixes:

- `## YYYY-MM-DD — Breaking: <summary>` — fires `api_contract_changed` notifications. Endpoint rename / removal / shape change / required field addition. Sister apps must update code.
- `## YYYY-MM-DD — Additive: <summary>` — silent. New endpoint or new optional field. Sister apps may opt in.
- `## YYYY-MM-DD — Cosmetic: <summary>` — silent. Doc rewording, examples, clarifications. No code impact.

Only `Breaking:` headings trigger notifications to `dev`/`admin` users (CO + BCQT operators) via the in-app notification system.

## Entries

## 2026-05-02 — Breaking: rename /co-config → /client-config; drop CO-runtime fields

**Endpoints touched:**
- `GET /v1/hub/dncxs/{client_id}/co-config` — deprecated. Sunset 2026-05-16. Returns `Deprecation: true` + `Sunset` + `Link: rel="successor-version"` headers during grace window.
- `GET /v1/hub/dncxs/{client_id}/client-config` — added (replaces co-config).
- `GET /v1/hub/dncxs/{client_id}/source-summary` — `co_stock_row_count` + `co_stock_row_count_semantics` removed; `client_config` sub-object reshaped to match `/client-config`.

**Why:**
Data Hub was returning CO-specific runtime config (`co_stock.lot_policy`, `allocation_code.*`) it didn't own. Master data (declaration types, fiscal year) is now persisted in `hub.client_config` with a versioned snapshot model. CO-runtime config moves back to CO; BCQT-runtime stays in BCQT.

**New shape (`/client-config`):**
```json
{
  "schema_version": 1,
  "client_id": "growatt-vn",
  "preset_key": "dncx",
  "eligible_import_declaration_types": ["E11", "E15"],
  "relevant_export_declaration_types": ["E42"],
  "fiscal_year_start_month": 1,
  "config_version": 3,
  "config_hash": "601d43362456eee3"
}
```

**Migration guide for CO:**
1. Switch reads from `/co-config` to `/client-config`. Map response fields:
   - `bcct.eligible_import_declaration_types` → `eligible_import_declaration_types` (top-level).
   - `bcct.relevant_export_declaration_types` → `relevant_export_declaration_types` (top-level).
   - `co_stock.lot_policy` — gone. Read from CO local config (`app/client_config_store.py`).
   - `allocation_code.strategy` / `description_regex` / `fallback` — gone. Read from CO local config.
   - `allocation_code.data_hub_code_resolution_mode` — gone. Read from `GET /v1/hub/dncxs/{id}` `code_resolution_mode` field.
2. Drop the 2 declaration-type rows from `/clients/{id}/config` UI; keep the 4 CO-runtime rows (lot_policy + allocation_code).
3. Cache invalidation: compare `config_hash` per fetch, drop derived state when it changes.
4. Cutover deadline: 2026-05-16. After that, `/co-config` returns 410 Gone.

**Migration guide for BCQT:**
1. Use `/client-config` as the source of truth for `eligible_import_declaration_types` and `relevant_export_declaration_types` when filtering BCCT rows for Mẫu 15 / 15a / 16.
2. `fiscal_year_start_month` is the canonical fiscal-year boundary. Default 1 if absent / `config_version=0`.

**Provider tests asserting new shape:** `tests/test_client_config.py`, `tests/test_read_api_auth.py` (TBD next pass).
