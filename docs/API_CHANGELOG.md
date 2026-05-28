# Data Hub API Changelog

Append-only, dated record of contract changes to `/v1/hub/*`. Sister apps (CO, BCQT) consume this as the change-detection source of truth alongside `docs/API_CONTRACT.md`.

## Heading conventions

Each entry must use one of these heading prefixes:

- `## YYYY-MM-DD — Breaking: <summary>` — fires `api_contract_changed` notifications. Endpoint rename / removal / shape change / required field addition. Sister apps must update code.
- `## YYYY-MM-DD — Additive: <summary>` — silent. New endpoint or new optional field. Sister apps may opt in.
- `## YYYY-MM-DD — Cosmetic: <summary>` — silent. Doc rewording, examples, clarifications. No code impact.

Only `Breaking:` headings trigger notifications to `dev`/`admin` users (CO + BCQT operators) via the in-app notification system.

## Entries

## 2026-05-28 — Additive: `GET /v1/hub/bcct` — `since` + `tombstones` for incremental pull

**Params added:** `since` (ISO-8601 UTC) + `include_tombstones` (`true`/`false`).
**Field added:** `server_time` (always present in response); `tombstones[]` (when `include_tombstones=true`).

**Why:**
CO is moving `refresh_co_stock_for_client()` from destructive DELETE+INSERT to diff-based incremental refresh. The full-corpus pull (~65k Johnson rows, ~8-10s) was the dominant cost of every refresh. CO request: `barry-CO-main/.ai/api-requests/2026-05-28-bcct-incremental-since-filter.md`.

**Contract:**
- `since=<ISO-8601 UTC>`: filter to rows whose `indexed_at > since`. Timezone-naive strings return 400 `invalid_since`.
- `include_tombstones=true` (requires `since`): include a `tombstones` array of `{transaction_key, removed_at, reason}` for rows deleted in the window. Sourced from `hub.bcct_row_history` (`action='delete'`). Without `since` → 400 `include_tombstones_requires_since`.
- `server_time`: always returned. Callers use it as the next call's `since` — closes the gap from multiple rows sharing one `indexed_at` tick.
- Backward compatible: omit `since` → existing shape plus the new `server_time` field. Existing callers ignore unknown keys.

**Auth:** unchanged — `hub:read` scope, user JWT or service token with `client_ids` whitelist.

**Tombstone first-page-only:** the `tombstones` array is returned in full on the first page (its size is bounded by deletions, which are rare). Pages 2+ return `tombstones=[]` when `include_tombstones=true` was passed.

**`transaction_key` stability** (CO correctness prerequisite): confirmed deterministic. Built as `f"{declaration_no}-{line_no}"` when declaration_no is present (the normal case). Edge fallback `f"{customs_code}-{token_hex(4)}"` only triggers when declaration_no is empty — should not occur in normal customs data.

**Tests:** 9 provider tests in `tests/test_bcct_incremental_since.py` cover the happy paths, tombstone semantics, pagination, and all 4 error cases.

**Commit:** TBD (this entry lands with the route change).

## 2026-05-15 — Additive: `GET /v1/hub/clients/{c}/declarations`

**Endpoint added:** `GET /v1/hub/clients/{client_id}/declarations`.

**Why:**
CO needs the TKX/TKN tab to answer "có tờ khai / thiếu tờ khai" per
referenced declaration. The existing
`GET /api/v1/clients/{c}/declarations` already exposed `file_count`
but is cookie-session protected and returned `401 login required` to
CO's service-token Bearer caller. BCCT row presence (via
`/v1/hub/bcct`) does NOT equal declaration-file presence — the
status answers the file question, not the BCCT-row question.

**Contract:**
- `direction` optional (`import` or `export`).
- `declaration_nos` optional, comma-separated (max 500). Exact-match
  on the canonical `declaration_no` string. When provided, response
  is single-page (no cursor).
- `has_files` optional (`yes` or `no`). Filters by `file_count > 0`.
- `cursor` + `limit` (default 200, max 500). Standard pagination
  contract.
- Auth: user JWT or service token with `hub:read` scope; `client_ids`
  whitelist enforced.
- Identity: `(client_id, declaration_no, direction)`. The same
  declaration_no can ship as two rows when present in both
  directions.

**Errors:**
- `400 invalid_direction` / `400 invalid_has_files` / `400 too many
  declaration_nos`.
- `401 bearer token required` (strict mode).
- `403 forbidden` (scope or whitelist).
- `404 Client not found`.

**Related operator route (cookie-session, web only):**
`GET /clients/{client_id}/declarations/download.zip?direction=…&declaration_nos=…&filename=…`
returns a ZIP containing every uploaded file for the requested set
plus a `DANH_SACH_TO_KHAI.txt` manifest. Files land at archive root
(no subfolders); duplicate filenames are suffixed `_1`, `_2`, …
When zero files match, the archive still ships with the manifest +
a `NO_FILES_FOUND.txt` marker. Unauthenticated callers receive
a `303` to `/login?next=…`.

**Why two routes:** the Bearer summary is consumed programmatically
by CO before dossier export to drive the in-app "thiếu tờ khai"
warnings; the ZIP download is opened by the operator's browser from
CO links and naturally rides the existing Data Hub cookie session.

**Provider tests:**
- `tests/test_declarations_api_v1_hub.py` (17 tests; default list,
  filters by direction / has_files / declaration_nos, exact same-no
  in both directions, pagination cursor round-trip, all 400/401/403
  paths, service-token scope + whitelist enforcement).
- `tests/test_declarations_download_zip.py` (12 tests; login bounce,
  validation, root-level files, duplicate-filename dedupe, manifest
  counts, NO_FILES_FOUND marker, direction identity, filename param
  sanitization).

**Spec:** `barry-CO-main/.ai/api-requests/2026-05-15-declaration-file-status.md`.

## 2026-05-13 — Additive: `GET /v1/hub/clients/{c}/bcct/by-codes`

**Endpoint added:** `GET /v1/hub/clients/{client_id}/bcct/by-codes?codes=A,B,C`.

**Why:**
CO derives "tồn CO" by paginating the full client BCCT (`direction=import`)
and applying CO-side `allocation_code` + `lot_policy` rules. For Johnson with
65k+ BCCT rows the substitute modal needed ~30s per fetch, even though it
only consumes stock for ~20 candidate codes returned by the substitute
lookup. This endpoint returns the same BCCT row shape filtered to a specific
code set, so the substitute-stock derivation stays bounded.

**Contract:**
- `codes` (required, comma-separated, max 100; case-insensitive exact match
  against `customs_code`).
- `direction` optional (typically `import`).
- `include_material_identity` optional, default `false`, same semantics as
  `/v1/hub/bcct`.
- `cursor` + `limit` (default 200, max 1000) — standard pagination.
- Auth: same as the rest of `/v1/hub/*` (user JWT or service token with
  `hub:read` scope, client_ids whitelist enforced).
- Row shape: identical to `/v1/hub/bcct`. Pagination shape: identical
  (`items`, `next_cursor`, `total_estimate`).

**Errors:**
- `400 missing codes` — empty / whitespace-only `codes` param.
- `400 too many codes` — more than 100 codes per request.
- `404 Client not found` — unknown `client_id`.
- Unknown codes → `200` with empty `items` (not `404`).

**Why not `/v1/hub/co-stock`:**
Splits "Data Hub returns BCCT slice" vs "CO applies its own
`allocation_code` / `lot_policy` rules". Data Hub doesn't own CO runtime
config (locked 2026-05-02 with the `/co-config → /client-config` rename), so
the stock derivation stays in CO.

**Provider tests:** `tests/test_bcct_by_codes_api.py` (19 tests; codes
filter single/multi/mixed-case/URL-decoded, direction combine,
include_material_identity attach, pagination, all 400/403/404 paths,
service-token scope + whitelist enforcement).

**Spec:** `barry-CO-main/.ai/api-requests/2026-05-13-bcct-by-codes-lookup.md`.

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
