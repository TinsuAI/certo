# Feature: BOM adapter "module management" (B.0)

**Captured** 2026-06-14 from BACKLOG B.0 / B.0b + DECISIONS 2026-06-09
("format/client extensibility lives in adapters + data, never in core").

**Driver:** reassure that BOM/declarability work isn't over-fit to Johnson/SAP.
Deliver *visibility* (what adapters exist, what signals they emit) + close the
"format-variant as DATA not code" loop. NOT runtime code upload.

## Scope

**IN (this slice):**

1. **Read-only Adapter registry admin view** — global page `/admin/bom-adapters`
   (dev/admin only). Lists the 5 registered `BomAdapter`s with, per adapter:
   `name`, legacy alias(es) → name, `label_key`/`description_key` (rendered),
   `supports_mapping_override`, `emits_intermediate_btp_versions`,
   `post_ingest_hooks`, whether `detect()` is implemented, registration order
   (= fallback order when no detect score). Footnotes the 2 raw-edge legacy
   aliases (`sap_indented_raw`, `growatt_factory_technical`) that only resolve
   for hook lookup. Plus a **read-only binding matrix** (which client binds which
   adapter, from item 2). Pure visibility; no mutation here.

2. **Per-client default adapter binding.** Migration adds nullable
   `hub.clients.default_bom_adapter text` (null = `auto`). The BOM upload form
   (`app/routes/bom.py` `upload_form` GET) pre-selects this client's bound
   adapter instead of the hardcoded default; a "đặt làm mặc định cho client"
   control next to the profile dropdown persists the chosen value. Validate
   against `adapter_names() + {'auto'}` (legacy names resolve via `resolve()`).
   The global registry view (item 1) renders the binding matrix read-only.

3. **Per-client `client_material_group_map` admin UI** — mirror the existing
   `client_column_aliases` UI. Per-client page (e.g.
   `/clients/{id}/material-group-map`): list rows, add/edit, delete. Editable
   fields: `material_group` (uppercase/trim), `item_category` (enum dropdown),
   `is_declarable` (bool), `notes`. New rows tagged `source='staff_form'`.
   Gate: `auth.require_can_edit_client`. New store `app/stores/material_group_map.py`
   (list/upsert/delete) + routes in `admin.py` + template mirroring
   `admin/client_column_aliases.html`. Link it from the column-aliases page.
   **Banner + re-run backfill button:** banner explains the two-step
   (classification updates live; bảng kê exclusion needs backfill); a "chạy lại
   backfill cho client này" button enqueues the backfill via the existing
   background-jobs infra (mig 076 + `app/routes/jobs.py` `_RECIPES`/`_spawn_job`).
   Requires: new job kind `material_group_backfill` (add to
   `background_jobs_kind_check` via a new migration) + a `_RECIPES` entry +
   generalizing `scripts/backfill_johnson_material_group.py` to take `--client-id`
   (johnson-specific today; the job runner passes client_id).

4. **Tighten + document the adapter contract (light):** promote `detect` from a
   commented hint to a real (optional-return-None) method on the `BomAdapter`
   Protocol; have the 3 abstaining adapters return `None` explicitly so the
   extension point is self-documenting. Write a short onboarding doc
   (`docs/bom-adapters.md` or AGENTS.md section): "new BOM format = 1 adapter
   module implementing the Protocol + `register()` + `detect()` + tests + deploy;
   new column names for an existing shape = `client_column_aliases` row, zero
   code; new item-type token = `client_material_group_map` row."

5. **Tests + screenshots** per feature-folder convention.

**OUT (explicit):**

- **Runtime `.py` upload / boot-time package loading** — forbidden by DECISIONS
  2026-06-09 (RCE-by-design, bypasses CI). The governed git/CI registry IS the
  anti-chaos pattern.
- **Making `detect()` strictly enforced at `register()`** — keep optional; the
  ranking already treats abstain (None) as registration-order fallback.
- **B.0b renames/generalizations:** `material_group` → `item_type_token`, and map
  key `(client_id, material_group)` → `(client_id, signal_kind, signal_value)`.
  Both deferred (YAGNI until a 2nd signal/format). Note: the new group-map UI +
  the `default_bom_adapter` column built here will need updating when the rename
  lands.
- **Auto re-run backfill on map edit** — the button is manual/explicit; map edits
  do NOT auto-cascade a backfill (keeps the destructive-ish re-tag staff-driven).

## Decisions

- **Registry view is GLOBAL, not per-client** — adapters are process-global
  singletons. Put it in the global admin button-bar (`admin/users.html` nav,
  beside UoM standards / Service tokens), `active_root='admin'`.
- **Mirror, don't abstract.** `client_column_aliases` (store + 4 routes +
  template, all live) is the proven pattern; copy its shape for the group-map UI
  rather than building a generic config-table framework (matches
  `feedback_macros_over_view_engine` — promote only after 3+ duplications; this
  is the 2nd).
- **Declarability keys on `is_declarable`, not `item_category`.** Verified
  `hub.v_material_classification` (mig 079): `item_category` is descriptive only;
  the declarable axis is the `is_declarable` boolean (after import-evidence wins).
  So the form must make `is_declarable` the meaningful toggle; `item_category` is
  a constrained-enum descriptor. Constrain it to the known set
  (drawing|document|label|packaging|metal|hardware|plastic|consumable|
  assembly_set|finished|other) via dropdown to avoid free-text drift.
- **Correct-by-default holds.** Removing/omitting a map row → those leaves fall to
  `declarable_unmatched` (review), never "broken" — consistent with the two-layer
  model. Adding a `material_group` that matches no ingested data is a harmless
  no-op.

## Risks

- **(central) Map edit ≠ bảng kê re-exclusion.** `v_material_classification` reads
  the map LIVE, so classification updates instantly. But the consumer-facing
  `exclude_non_declarable` filter lives on the STORED `bom_artifact_rows.excluded_at`
  column (`app/stores/bom.py:921,1927`), written only by
  `scripts/backfill_johnson_material_group.py --apply`. So flipping
  `is_declarable` in the UI does NOT re-tag existing rows until backfill re-runs.
  Staff will expect immediacy. **Mitigation (chosen):** prominent banner on the
  group-map page ("phân loại cập nhật ngay; loại trừ khỏi bảng kê cần chạy lại
  backfill cho client này") + a "chạy lại backfill cho client này" button
  enqueuing the idempotent, import-aware script via the jobs infra (item 3).
- **`item_category` free-text drift** if not constrained — mitigated by enum
  dropdown (above).
- **Raw-edge parsers aren't `BomAdapter` instances.** `bom_edges.py` parsers
  (`sap_indented_raw`, `growatt_factory_technical`) only alias INTO the registry
  via `_LEGACY_ALIASES` for hook resolution. **Decided:** registry view shows the
  5 Protocol adapters; raw-edge aliases appear as a footnote only.
- **Binding validation:** `default_bom_adapter` must validate against live
  `adapter_names() + {'auto'}` at set-time; a stored value whose adapter is later
  removed should degrade to `auto` (resolve() returns None) rather than 500 the
  upload form. Cover in tests.
- **`backfill_johnson_material_group.py` generalization** — adding `--client-id`
  must not change johnson behaviour (default/loud if the arg is omitted) and must
  stay idempotent + import-aware; regression-test against johnson before wiring
  the button.
- **No CSRF on POST** — pre-existing project gap (E.4); the group-map + binding
  POSTs inherit it. Out of scope, note for consistency.
- **Permission surface:** group-map + binding edits are per-client →
  `require_can_edit_client` (matches column-aliases). Registry view is dev/admin
  global. No new permission key.

## Resolved (was Open Questions)

1. **Per-client adapter binding — DO IT** (not deferred). Smallest model: nullable
   `hub.clients.default_bom_adapter`, read by the upload form default + a
   "set as default" control; registry view shows the matrix read-only. (Item 2.)
2. **Backfill staleness UX — banner + re-run button** (enqueue via jobs infra),
   not banner-only. (Item 3.)
3. **Registry view membership — 5 Protocol adapters + raw-edge footnote.** (Item 1.)

## Next step

`/tdd` — risk concentrates in the group-map store (upsert/enum-validation), the
binding validation/degrade path, and the `--client-id` backfill generalization;
worth tests first. Registry view + doc are low-risk (test-after + screenshots).
Suggested build order: (1) backfill `--client-id` + job recipe/migration
test-first → (2) group-map store+routes test-first → (3) binding migration +
store + form wiring → (4) templates (group-map, registry, banner/button) → (5)
screenshots → `/rev`. Migrations needed: `080` (clients.default_bom_adapter) +
`081` (background_jobs_kind_check += material_group_backfill) — or fold into one.
