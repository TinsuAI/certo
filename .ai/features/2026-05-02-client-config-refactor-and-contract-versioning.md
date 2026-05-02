# Feature: Client-config refactor + API contract versioning

Hướng B from the 2026-05-02 architectural discussion: stop pretending Data Hub owns CO-specific runtime config; keep only true agency master data (declaration-type registry); rename `co-config` → `client-config`; build a real change-notification mechanism for sister apps so this is the last time we silently break a contract.

## Scope

**Confirmed direction:** Hướng B1 (Data Hub builds new UI for Nhóm A; CO drops the master fields from its UI; CO keeps Nhóm B local). User confirmed 2026-05-02.

**In:**

1. New `hub.declaration_type_catalog` table — **the catalog of customs declaration type codes** (E11, E15, E31, A12, etc.). Each row: `code`, `direction` (import|export), `description`, `notes`, `created_at`, `updated_at`, `is_active`. **No domain knowledge hardcoded in Python**: the table seeds from a versioned data file at `data/seeds/declaration_types.xml` (or YAML — see Decisions) shipped with the repo, but every row is editable / addable / deletable via Data Hub UI after seed.
2. New `hub.client_type_presets` table — **named profiles** for "loại hình hoạt động của DNCX": `preset_key` (e.g. `dncx`, `sxxk`, `gia_cong`, `manual`), `display_name`, `default_eligible_import: list[str]`, `default_relevant_export: list[str]`, `is_system: bool` (system-seeded vs user-created), `is_active`. Same pattern: seed from `data/seeds/client_type_presets.xml`, but presets are addable / editable / deletable via Data Hub UI. System presets cannot be deleted but can be edited; user-created presets can be deleted.
3. New `hub.client_config` table — **per-client overrides**: `client_id` (PK), `preset_key` (nullable FK to `client_type_presets.preset_key`, can be `null` for fully manual), `eligible_import_declaration_types: list[str]`, `relevant_export_declaration_types: list[str]`, `fiscal_year_start_month: smallint` (1-12, default 1; supports BCQT settlement periods + CO origin year boundaries for non-calendar fiscal years e.g. Japanese DNCX with April start), `config_version: int` (monotonic, bumped on edit), `config_hash: text` (sha256 of canonical JSON), `created_at`, `updated_at`, `updated_by` (user_id). When `preset_key` is set, the lists default to the preset's defaults but can be overridden per client (snapshot semantics — picking a preset copies its current defaults into the client row; later preset edits do NOT cascade to clients that already chose it, to avoid retroactive contract changes).
4. UI at `/admin/declaration-types` — staff can view/add/edit/disable declaration type codes. Edits write through to the table; the seed file is read once on first install only.
5. UI at `/admin/client-type-presets` — staff can view/add/edit/delete presets. System presets show a "system" badge and have delete disabled; user presets are fully editable.
6. UI at `/clients/{id}/config` (Data Hub) — staff edits per-client config: pick a preset (autofills the two lists from preset defaults), or override the lists directly. Shows current `config_version` + `config_hash`. Multi-select inputs populated from `hub.declaration_type_catalog` filtered by `direction`.
7. New endpoint `GET /v1/hub/dncxs/{client_id}/client-config` returning a slimmed payload with only the master-data fields above plus `config_version` + `config_hash`.
3. Deprecate `GET /v1/hub/dncxs/{client_id}/co-config`. Keep it serving the old shape (with `Deprecation` + `Sunset` headers per RFC 8594) for one grace window. Old shape mirrors new client-config fields where they overlap; CO-runtime fields (`co_stock.lot_policy`, `allocation_code.*`) keep returning their hardcoded placeholders so no in-flight CO request 500s.
4. Drop `co_stock_row_count` + `co_stock_row_count_semantics` from `source-summary` response. Shape `source-summary.client_config` becomes the new client-config shape.
5. **Contract-change mechanism (the deliverable the user asked for):**
   - `docs/API_CHANGELOG.md` — append-only, dated, per-endpoint, with breaking-vs-additive flag and migration notes. Cross-linked from BCQT-System and barry-CO-main DECISIONS.md.
   - `Deprecation` + `Sunset` HTTP headers on retired endpoints (RFC 8594). Sister apps log warnings.
   - Reuse existing notification system (migration 015): new trigger `api_contract_changed` fires on commits that touch `docs/API_CONTRACT.md`, notifies `dev`/`admin` users (which are the CO + BCQT operator accounts). Pre-commit hook or lightweight CI check enforces "any change to `app/routes/api.py` requires a paired entry in `API_CHANGELOG.md`".
   - Per-resource `config_version` + `config_hash` already exist in the response — formalize semantics: "increment `config_version` on every staff edit; `config_hash` is sha256 over canonical JSON of the config fields". Consumers compare `config_hash` on each fetch to invalidate caches.

**Out:**

- Real CO stock calculation (`co_stock_qty` after lot allocation). Stays in CO entirely. Data Hub provides raw filterable BCCT; CO does FIFO/weighted-avg.
- Removing `co_stock.lot_policy` and `allocation_code.*` from CO. Those move to CO schema as part of CO's own work — out of scope for this Data Hub change.
- Service-account JWTs (separate backlog item).
- `/api/v1/hub/...` legacy session-cookie route. Deferred — not part of the v1 contract surface.

## Decisions

1. **No hardcoded domain knowledge.** Customs declaration type codes (E11, E15, E31, …) and DNCX activity-type presets (dncx, sxxk, gia_cong, …) are *configurable data*, not Python constants. Today they live in `barry-CO-main/app/client_config_store.py:14-31` as Python dicts — that is wrong. They move to `hub.declaration_type_catalog` and `hub.client_type_presets` tables, seeded from versioned files in `data/seeds/`, edited via Data Hub UI.
2. **Seed file format: YAML, not XML.** User suggested XML. YAML preferred because the project is already Python (PyYAML in deps probably), seeds are short flat lists, YAML diffs cleaner in PR review, and there is no existing XML tooling in the repo. Seed file is the *initial* state only; after first install the table is the source of truth, seed is no longer read. Re-seeding is an explicit ops action (`scripts/reseed_declaration_types.py --force`), not automatic.
3. **Preset → client is snapshot, not live link.** When a client picks preset `sxxk`, Data Hub copies the preset's current `default_eligible_import` and `default_relevant_export` into the client row. Subsequent edits to the preset do NOT auto-update existing clients — they only affect new clients picking the preset, and a "re-apply preset" button on the client config page if staff explicitly want to refresh. Reason: contract stability. CO and BCQT cache by `config_hash`; if a preset edit silently changed every client config, every consumer's cache would invalidate at once with no audit trail per client.
4. **System presets vs user presets.** System presets (seeded from file) cannot be deleted, only edited or disabled (`is_active=false`). User presets (created via UI) are fully deletable. Prevents staff accidentally wiping the standard `dncx`/`sxxk`/`gia_cong` foundation.
5. **`co-config` is deprecated, not deleted.** Hard removal would break CO at runtime today. Two-step: ship `client-config` first, give CO a window to migrate, then remove `co-config` after CO confirms cutover.
6. **Migration window: 1 release cycle (~2 weeks).** Tracked via `Sunset` header date + a one-time scheduled agent (`/schedule`) to open the removal PR.
7. **`config_version` is monotonic per (client_id).** Bumped by Data Hub on staff edit, not by client requests. `config_hash` is the actual change-detection primitive; `config_version` is for human reading.
8. **Master data UI lives in Data Hub.** Even though CO has its own UI today, that becomes vestigial after the migration. CO's `/clients/{id}/config` page drops the 2 declaration-type rows and keeps only the 4 CO-runtime rows (lot_policy + allocation_code).
9. **Source of truth for sister-app contract = `docs/API_CONTRACT.md` + `docs/API_CHANGELOG.md`.** Code is authoritative for behavior; the markdown pair is authoritative for contract.
10. **Provider tests are the safety net.** Every endpoint in API_CONTRACT.md must have a matching test in `tests/test_api*.py` that asserts the documented shape. CI will block contract drift.

## Risks

1. **CO test fixture lock-in.** `barry-CO-main/tests/test_data_hub_integration.py:493` mocks the old `co-config` shape. CO needs a coordinated PR after Data Hub ships the new endpoint. Coordinate via cross-linked PRs and/or a single commit cycle.
2. **CO production code paths read fields that vanish.** Specifically `co_stock_row_count` (`barry-CO-main/app/main.py:516`) and `client_config["co_stock"]["lot_policy"]` (`portfolio.py:125`, `bcct.html:57`, `data_hub_client.py:163`). Data Hub keeping the deprecated `co-config` endpoint serving placeholders mitigates the runtime break, but CO will see degraded behavior (placeholders instead of CO-local values it had today). CO must move those reads to its own local config store, which it already has at `client_config_store.py` — the migration is "read from CO local store, not Data Hub" for those CO-specific fields.
3. **BCQT not yet a consumer.** Today BCQT references Data Hub only in design docs (`BCQT-System/.ai/DECISIONS.md`). The `client-config` endpoint design must already account for BCQT's settlement use case (Mẫu 15 / 15a / 16 also filter by declaration type) — confirm the same `eligible_import_declaration_types` and `relevant_export_declaration_types` are sufficient, or extend the schema while we're touching it.
4. **Migration ordering.** Data Hub ships → CO migrates → grace window → Data Hub removes. If CO migration slips, removal PR must wait. The scheduled agent should *open* the removal PR, not auto-merge.
5. **Existing migration numbering.** Next number is 019 (after 018). Confirm no in-flight migration branches.
6. **`config_hash` recomputation on every read** is fine at current scale but may need caching when the table grows. Defer optimization.

## Open Questions

All resolved 2026-05-02:

1. **Backfill from CO JSON files** → **YES, automatic.** Script reads `barry-CO-main/data/local/client-config/clients/{client_id}/config.json` (3 real files exist: growatt, do-thanh, johnson) and seeds matching `hub.client_config` rows, mapping `declaration_type_preset` → `preset_key`. Staff don't re-enter.
2. **Grace window length** → **2 weeks fixed.** Sunset header date = deploy_date + 14d. Scheduled agent opens removal PR at sunset.
3. **BCQT pre-emption — what shared fields to add now** → **Add `fiscal_year_start_month: int` (default 1) only.** BCQT runtime config (Mẫu 15/15a column mappings, `path_type`) stays in BCQT — that's BCQT-specific runtime, not shared master. `customs_unit_code` deferred until concrete demand.
4. **Notification granularity** → **Only `## Breaking:` entries trigger notifications.** Additive (new endpoint, new optional field) and cosmetic (rewording, examples) entries are logged in changelog only. Pre-commit/CI hook parses `API_CHANGELOG.md` for `## YYYY-MM-DD — Breaking:` headings; new ones fire `api_contract_changed` notification to `dev`/`admin` users.
5. **Seed file path** → **`data/seeds/declaration_types.yaml` + `data/seeds/client_type_presets.yaml`.** Matches existing `data/manual_test/` convention.
6. **Legacy `/api/v1/hub/...` route** → **Out of scope.** Touch only if trivially in the way.

## Suggested Next Step

This is a multi-piece change with cross-repo blast radius. Suggest TDD per piece, sequenced:

1. **Piece 1 — Seed files + migrations + stores** (~1 day): `data/seeds/declaration_types.yaml`, `data/seeds/client_type_presets.yaml`. Migration 019 creates `hub.declaration_type_catalog`, `hub.client_type_presets`, `hub.client_config`. Seed loader runs once on migration apply. Stores: `app/stores/declaration_types.py`, `app/stores/client_type_presets.py`, `app/stores/client_config.py`. Integration tests against Postgres.
2. **Piece 2 — Admin UI for declaration types** (~0.5 day): `/admin/declaration-types` — list + add + edit + disable. Audit-logged via GUC.
3. **Piece 3 — Admin UI for presets** (~0.5 day): `/admin/client-type-presets` — list + add + edit + delete (delete disabled for system presets).
4. **Piece 4 — Per-client config UI** (~1 day): `/clients/{id}/config` Data Hub page. Preset picker + override checkboxes. Save bumps `config_version`, recomputes `config_hash`. Re-apply-preset button.
5. **Piece 5 — New endpoint** (~0.5 day): `GET /v1/hub/dncxs/{client_id}/client-config` reading from new table. Provider tests asserting shape. Update `API_CONTRACT.md`.
6. **Piece 6 — Deprecation of old endpoint** (~0.5 day): `Deprecation` + `Sunset` headers on `/co-config`; old endpoint reads from new table for the overlapping fields, keeps placeholders for CO-runtime fields. Update `API_CONTRACT.md` and create `API_CHANGELOG.md`.
7. **Piece 7 — Source-summary slim** (~0.5 day): drop `co_stock_row_count*` from response; bump version; changelog entry.
8. **Piece 8 — Notification trigger** (~0.5 day): wire `api_contract_changed` notification trigger via existing notification system; document subscriber model.
9. **Piece 9 — Backfill script** (~0.5 day): one-shot `scripts/backfill_client_config_from_co.py` that reads CO JSON files and seeds `hub.client_config` rows.
10. **Piece 10 — Cross-repo PRs** (coordination): companion PRs in `barry-CO-main` to switch reads to new endpoint + drop the 2 declaration-type rows from CO's UI. BCQT gets a one-line entry in DECISIONS.md.
11. **Piece 11 — Schedule removal** (after CO confirms cutover): `/schedule` agent in 2 weeks to open the removal PR for `/co-config`.

Total: ~5 days of Data Hub work + ~1 day CO migration + 2-week grace window before removal.
