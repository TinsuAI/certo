# Data Hub API Changelog

Append-only, dated record of contract changes to `/v1/hub/*`. Sister apps (CO, BCQT) consume this as the change-detection source of truth alongside `docs/API_CONTRACT.md`.

## Heading conventions

Each entry must use one of these heading prefixes:

- `## YYYY-MM-DD — Breaking: <summary>` — fires `api_contract_changed` notifications. Endpoint rename / removal / shape change / required field addition. Sister apps must update code.
- `## YYYY-MM-DD — Additive: <summary>` — silent. New endpoint or new optional field. Sister apps may opt in.
- `## YYYY-MM-DD — Cosmetic: <summary>` — silent. Doc rewording, examples, clarifications. No code impact.

Only `Breaking:` headings trigger notifications to `dev`/`admin` users (CO + BCQT operators) via the in-app notification system.

## Entries

## 2026-06-09 — Additive: SAP Material Group + non-declarable BOM-row exclusion (mig 078)

Silent / opt-in; no consumer code change required.

- `GET /v1/hub/materials` (and per-material) gain three additive fields:
  `material_group` (raw SAP code), `item_category` (derived nature),
  `customs_relevance` (`excluded_non_material` | `declarable` |
  `declarable_unmatched` | `review` | null). Derived from
  `hub.client_material_group_map` × BCCT-import evidence.
- `POST /v1/hub/products/bom/artifacts:batch` accepts body
  `exclude_non_declarable` (bool, default **false**); single-artifact GET
  `/products/{product_code}/bom/artifacts/{artifact_id}` accepts it as a query
  param. When true, drops rows soft-excluded as non-declarable ("rác":
  drawing/document/label/phantom). Echoed in `filter_applied.exclude_non_declarable`.
- BOM artifact-row `payload` now also carries `material_group`, `phantom`, `bulk`.
- Default-off everywhere → existing CO/BCQT calls unchanged. CO opts in for
  johnson-vn after verification. Full note:
  `.ai/sister-app-notes/2026-06-09-bom-row-exclusion-and-material-group.md`.
- **mig 079 (same-day correction):** `customs_relevance` is **import-aware** — a
  material with a BCCT import line is always `declarable`, never rác (regardless of
  Material Group). `excluded_non_material` is now non-imported document/label only;
  RD07 (SAP "Set/Semi-Assy", not "drawing") → declarable, its drawings →
  `declarable_unmatched`. No shape change; same enum.

## 2026-06-08 — Cosmetic: staleness flags are convertibility-aware (fewer false positives)

No shape change, no consumer code impact. The staleness predicate behind
`is_stale` / `has_uom_drift` / `state` / `stale_count` (Track D) now mirrors
the UoM convertibility classifier: a BOM-vs-catalog unit difference is flagged
only when the units are genuinely **incompatible** (no factor). Same-canonical
(alias), same-family `base_factor` (g↔kg), client overrides (either direction),
and tier-A 1:1 (count/assembly) pairs are accepted silently.

Effect for consumers (CO / BCQT):
- `stale_count` (source-summary `bom` block) and per-artifact `state` show
  **fewer** flagged items — false positives on convertible UoM diffs are gone.
  Values drop; this is a correctness improvement, not a contract change.
- **No code change needed.** Standing-contract reminder: read each BOM row's
  own `uom`. A convertible catalog edit no longer re-normalizes already-
  published rows, so `row.uom` may differ from the catalog's current uom while
  staying physically correct.

Data Hub mig 077; brief `.ai/features/2026-06-08-bom-staleness-fingerprint/`.

## 2026-06-07 — Additive: `bom` block on `/source-summary`

**New optional block** on `GET /v1/hub/dncxs/{client_id}/source-summary`, alongside the existing `material_catalog` / `product_catalog` / `bcct` blocks. Company-level BOM aggregates over alive (non-tombstoned) artifacts, for per-company BOM dashboards:

```json
"bom": {
  "exported_with_bom": 130, "exported_without_bom": 43, "exported_total": 173,
  "product_count": 171, "stale_count": 8, "multi_version_count": 65,
  "last_published_at": "2026-05-29T..+00:00"
}
```

Field semantics in `docs/API_CONTRACT.md` (Source Summary section). Notes for consumers:
- **Headline is the export trio.** `exported_with_bom` / `exported_without_bom` / `exported_total` are over distinct BCCT export `customs_code`s — the products CO certifies — and are independent of catalog category. `with + without == total`. They are exact-`customs_code` matches → blind to NB codes inside `goods_name` parens; treat as a close approximation, not an absolute count.
- `product_count` is a **secondary** internal coverage metric: distinct codes with a BOM including BTP sub-assemblies (Johnson derives a BOM per intermediate BTP). It is NOT a finished-product count — do not show it as "# thành phẩm có BOM".
- `stale_count` counts products with an `is_stale` BOM (Track D), `multi_version_count` products with >1 logical version, `last_published_at` is the most recent publish.
- No new round-trip: CO reads this in the source-summary call it already makes.

Motivation: CO API request `barry-CO-main/.ai/api-requests/2026-06-07-products-total-count.md`. The companion ask — real `total` + cursor pagination on `GET /v1/hub/products` — is deferred (Data Hub backlog C.4); CO does not need product enumeration yet.

## 2026-06-05 — Additive: `depth` filter + `is_shallow` field on BOM artifacts

**New optional query param** on `GET /v1/hub/products/{p}/bom/artifacts` and `POST /v1/hub/products/bom/artifacts:batch`:
- `depth` = `full` | `any` (default `any`).
  - `any` (default / omitted): no behavior change — shallow artifacts still returned.
  - `full`: exclude SHALLOW flats (`is_shallow=true` — `flatten_strategy='purchased_btp_as_leaf'` plus the conservatively-shallow `mixed_confirmed`/`no_strategy` flattened rows). Keeps `technical_exploded`, `self_produced_btp_exploded`, `manual_flat_as_provided`, and `flatten_status='not_applicable'`.

**New optional field** on every artifact item (list, `:batch`, single-artifact GET):
- `is_shallow` (bool) — `true` iff the artifact is a shallow/partial flatten. Server-computed via `app.stores.bom.is_shallow_flatten` (single-sourced with `bom_shape`).

**Echoed** in `filter_applied.depth` on every response.

**Why:**
`shape=flat` keeps `flatten_status IN ('flattened','not_applicable')` but does NOT encode flatten depth. A shallow flatten (`purchased_btp_as_leaf`) passes `shape=flat` and leaked into CO's certificate-of-origin picker next to the fully-exploded version, letting an operator pick a structurally incomplete BOM (e.g. johnson-vn VGM0121-05: a 2-row shallow vs a 223-row full). `depth=full` lets the picker exclude shallow flats. Applied before `latest_per_variant` so a shallow artifact is dropped from partition selection, not allowed to win its `(bom_variant_id, flatten_strategy)` partition.

**Impact:**
None for existing callers (default `any` is a no-op). CO opts in by passing `depth=full` from its picker. New `400 invalid_depth` for `depth` not in `{full, any}`.

**Commit:** TBD (this entry lands with the change).

## 2026-05-28 — Breaking: `category_override` field removed from materials JSON

**Field removed** from `/v1/hub/clients/{c}/catalog/materials` and `/v1/hub/materials/{customs_code}` responses:
- `category_override` (text, was always emitted even when null).

**Why:**
Backing column `hub.materials.category_override` + `override_reason` (mig 002 scaffold, 2026-05-01) were a "patch instead of edit" design from before the audit trigger (mig 045) and the catalog edit form (A.3) supplanted them. The UI to set overrides was never built. Data audit 2026-05-28: 0/13,589 rows across Growatt + Johnson had either column set. Dead architecture.

**Impact:**
None expected. CO `data_hub_client.py` consumes `category` (used for product/material partition) but not `category_override` — verified by grep. If a downstream consumer was reading `category_override`, the field is now absent from JSON.

**Mig:** 072.

**Commit:** TBD (this entry lands with the schema change).

## 2026-05-28 — Breaking: BOM vocab v1 URL aliases removed

**Endpoint removed (was 308 redirect since mig 031, 2026-05-07):**
- `GET /v1/hub/products/{p}/bom/versions` → use `/v1/hub/products/{p}/bom/artifacts` directly.
- `GET /clients/{c}/bom/version/{id}` (UI) → use `/clients/{c}/bom/artifact/{id}`.
- `GET /clients/{c}/bom/{p}/versions` (UI) → use `/clients/{c}/bom/{p}/artifacts`.

**Why:**
3-week grace period elapsed. CO and BCQT codebases verified clean of old URL refs (`grep -rn "bom/version\|bom/versions"` returns zero). Demo is internal-only so external-bookmark risk is low. Tracked in `.ai/BACKLOG.md` C.3.

**Impact:**
After this release the old URLs return 404, not 308. Any caller still using the old paths breaks. None known at ship time.

**Tests:** 3 redirect tests removed from `tests/test_bom_vocab_rename.py`; schema + ID-prefix tests retained.

**Commit:** TBD (this entry lands with the route change).

## 2026-05-28 — Additive: `GET /v1/hub/products/{p}/bom/artifacts` — picker filter params

**Params added:** `intents`, `lifecycle`, `shape`, `latest_per_variant`, `case_id`. **Response field added:** `filter_applied` echo block (always present).

**Why:**
CO's per-TP BOM picker (operator's selection surface for which BOM artifact drives origin calculations) leaks tombstoned, draft, superseded, foreign-case `modified_for_case`, and `technical_non_flattened` rows. Operators can silently pick a stale or wrong-case BOM — correctness issue, not cosmetics. The `/bom/latest` endpoint already computes the right set via `latest_flattened_versions`, but `409`s on dual-source variants instead of returning all winners. CO request: `barry-CO-main/.ai/api-requests/2026-05-28-bom-artifacts-active-flat-filter.md`.

**Contract:**
- `lifecycle=active` ⇒ `status='published' AND tombstoned_at IS NULL`. Default `all` (back-compat).
- `shape=flat` ⇒ `flatten_status IN ('flattened','not_applicable')`. Default `any` (back-compat).
- `intents=<comma-list>` from `{asserted_technical, staff_edit, derived, customs_declared, modified_for_case}`. When `modified_for_case` is included, `case_id` is required and scopes those rows to `context.case_id == case_id`. Other intents pass through unchanged.
- `latest_per_variant=true` partitions by `(bom_variant_id, flatten_strategy)` and keeps newest `published_at` per partition (deterministic tiebreak: `artifact_no DESC`, then `artifact_id DESC`). Default `false`.
- `filter_applied` echo always returned — consumers detect server-side support and fall back to client-side filtering when the field is absent.

**Defaults preserve raw-history behavior** — CO picker opts in by passing explicit filter params. Existing admin/debug consumers see no change.

**Errors:** `400 invalid_lifecycle`, `400 invalid_shape`, `400 invalid_intents`, `400 invalid_boolean`, `400 case_id_required`, `400 conflicting_intent_params`.

**Tests:** 13 provider tests in `tests/test_bom_artifacts_picker_filter.py` (defaults, each filter dimension, dual-source partition, error cases, picker full combination).

**Commit:** TBD (this entry lands with the route change).

## 2026-05-28 — Additive: `GET /v1/hub/clients/{c}/declarations/download.zip` — Bearer mirror of operator ZIP download

**Endpoint added:** `GET /v1/hub/clients/{client_id}/declarations/download.zip`.

**Why:**
CO is building a self-contained dossier ZIP in the "Review & Xuất" step that consolidates Bảng kê C/O + supporting chứng từ + all referenced TKX/TKN declaration files. The existing cookie route at `/clients/{cid}/declarations/download.zip` is operator-browser only — `auth.current_user()` returns `None` for Bearer callers and the route 303s to `/login`. CO server can't pull the bytes server-side, so the dossier today ships with manifest links only, forcing the operator into a second manual step. CO request: `barry-CO-main/.ai/api-requests/2026-05-28-bcct-declarations-download-bearer.md`.

**Contract:**
- Same query params as the cookie route: `direction` (required, `import`/`export`), `declaration_nos` (required, comma-separated, max 500), `filename` (optional).
- Default archive filename: `declarations_{client_id}_{direction}.zip`.
- Response shape identical to the cookie route: files at archive root with `_1`/`_2` collision dedup, `DANH_SACH_TO_KHAI.txt` manifest, `NO_FILES_FOUND.txt` marker on zero-match.
- Auth: `hub:read` scope; user JWT or service token with `client_ids` whitelist (`include client_id`).

**Errors:** `400 invalid_direction`, `400 declaration_nos_required`, `400 too_many_declaration_nos`, `401 bearer token required`, `403 forbidden`, `404 Client not found`.

**Pattern:** mirror, not dual-auth retrofit on the cookie route ([[project_api_routing_convention]] — precedent: substitute API mirror 2026-05-13).

**Tests:** 13 provider tests in `tests/test_declarations_download_zip_bearer.py` (happy paths, error paths, service-token scope, client whitelist, strict-mode 401).

**Commit:** TBD (this entry lands with the route change).

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
