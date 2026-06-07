# Backlog

Ideas captured but not yet planned. Each item should grow into a feature
brief (`.ai/features/YYYY-MM-DD-<slug>/brief.md`) before being built.

For *current* in-flight state and immediate next steps, see `STATUS.md`.
For past architectural decisions, see `DECISIONS.md`.

Audited 2026-05-13 — open items grouped by theme; shipped items moved
to the bottom log with brief annotation.

---

## Themes (TOC)

- [A. Catalog & material identity](#a-catalog--material-identity)
- [B. BOM upload & adapter infrastructure](#b-bom-upload--adapter-infrastructure)
- [C. Sister-app coordination](#c-sister-app-coordination)
- [D. Aggregate data history](#d-aggregate-data-history)
- [E. Architectural follow-ups](#e-architectural-follow-ups)
- [F. Data operations](#f-data-operations)
- [G. Polish & independent items](#g-polish--independent-items)
- [Shipped — kept for context](#shipped--kept-for-context)
- [Notes](#notes)

---

# A. Catalog & material identity

Cluster of catalog data-quality work captured 2026-05-09 (Mã chờ duyệt
session). Phase 1 of catalog multi-source SHIPPED (provenance, observed
roles, candidate feed, candidate richness). Phase 2 + supporting items
remain open. Identity-resolution items (parser-rules, paren-extract)
sit here too because they share the catalog data graph.

## A.1 Phase 2 catalog — CLOSED 2026-05-28 (dead-code drop, not refactor)

**Captured 2026-05-09**. Original plan: replace single-value `category`
+ `category_override` patch with multi-role `roles[] text[]`. ~2-3 days
cross-cut refactor.

**Closed without doing the refactor.** Discovery 2026-05-28 found:

- `category_override` + `override_reason` (mig 002 scaffold) were a
  "patch instead of edit" design from before mig 045 audit trigger and
  the A.3 edit form supplanted them. The UI to set overrides was never
  built (session 2026-05-01 to-do #11, dropped on the floor).
- Data audit on local dev DB: **0/13,589 rows** across Growatt + Johnson
  have either column set. Dead architecture, not active hack.
- `observed_roles[]` (mig 046) already surfaces multi-role truth at the
  view level. The 421 observed-multi-role rows render "Đa nguồn" badge
  today without any declared-side change.
- Declared/observed conflict count: **1** out of 13,589. The hypothetical
  pain `roles[]` would resolve does not exist in current data.

**Mig 072 shipped** (2026-05-28): drop both columns + recreate
`v_material_roles` without `coalesce(override, category)`. ~30 min,
not 2-3 days. Phase 3 declared multi-role deferred until a concrete
staff workflow blocker appears. See
`project_bom_code_multirole.md` memory revision.

Manual fields (item 2 of the original plan: `hq_registration_no`,
`hq_registration_date`, `supplier_hint`, `name_source`, `uom` — `uom`
already shipped via mig 063) tracked separately if/when needed.

## A.2 Catalog conflicts page — SHIPPED 2026-05-15

Dedicated review queue at `/clients/<cid>/catalog/conflicts` surfacing
both `declared_observed_conflict` (column on `v_material_roles`) and
sourcing-confirmation conflict (Python/SQL-derived from
`btp_sourcing` vs observed `observed_roles[]`). Inline `btp_sourcing`
dropdown with `return_to` redirect to keep staff on the queue.
Catalog list shows a "X dòng cần review" nav banner when count > 0.
Brief: `.ai/features/2026-05-15-catalog-conflicts-page/brief.md`.
+8 provider tests (1101 passed). No suppress mechanism — staff
resolve by editing declared category or btp_sourcing (immutable
principle, [[feedback_no_derived_in_source]]).

## A.3 Catalog edit permission (per-role configurable)

**Captured 2026-05-09**. User: *"cho user quyền edit (configurable
trong giao diện phân quyền)"*.

Today catalog UI has Accept/Promote/Tombstone but no general "edit row"
form for an existing material. Add:

- `/clients/<id>/catalog/<material_code>/edit` — form to edit name,
  category, uom, production_source, supplier_hint, hq_registration_*.
- Permission gate via existing role system. New permission key
  `catalog:edit_material` exposed in role-management UI.
- Audit captures every edit (mig 045 trigger already in place).
- "no DELETE" rule — edits stay versioned in audit table.

**Effort**: ~1 day (form + permission UI + tests + screenshots).

## A.4 Catalog material detail — cross-source inconsistency warnings

**Captured 2026-05-09**. User: *"Trong view của mỗi mã vật tư, cần query
chéo các thông tin ở các nơi, cảnh báo bất nhất nếu có. Ví dụ các dòng
trong BCCT dùng mã đó nhưng lại khác mã HScode, etc."*

Existing detail page (`/clients/<id>/catalog/<material_code>/detail`)
shows: provenance, observed signals (from v_material_roles), audit
history, recent BCCT refs, recent BOM artifacts.

Add **cross-source inconsistency panel**:

- **HS code drift**: same material_code declared with multiple `hs_code`
  values in BCCT → warn "Mã HQ này đã khai 3 mã HS khác nhau: X (47 lần),
  Y (3 lần), Z (1 lần)".
- **UoM drift**: BCCT.unit vs BOM.uom vs materials.uom mismatch.
- **Origin drift**: BCCT.origin variation across declarations for same
  code.
- **Direction drift**: code declared as both import + export (multi-role
  hint).
- **Sourcing drift** (mig 046 sourcing_confirmation_conflict): catalog
  says btp_nm but BCCT shows is_consumed_in_bom + is_in_own_bom_root →
  inconsistent.
- **Code mappings drift**: 1 NB code mapped to multiple HQ buckets,
  vice versa.

Each warning has: severity, evidence count, link to drilldown.

**Effort**: ~1 day (detail-page section + 5-6 warning queries + tests).

**Status 2026-05-10**: ✅ initial implementation shipped (Feature 3 in
`.ai/features/2026-05-10-johnson-onboarding/brief.md`):
`app/stores/catalog_bcct_analysis.py` + panel in
`app/templates/clients/catalog_detail.html`. Covers unit (CRITICAL),
hs_code (WARN), goods_name (INFO), origin (INFO). Common-prefix/suffix
diff highlight surfaces divergent characters per-value.

## A.4.2 Substitute XLSX bulk upload (P1 client_confirmed)

**Captured 2026-05-10** during Feature 4 MVP. Manual-add UI covers
single-pair entry; bulk-import path deferred.

**Scope:** XLSX with columns `material_a_code`, `material_b_code`,
optional `notes`. Upload route under `/clients/{cid}/substitutes/upload`,
inserts rows with `source='client_confirmed'` and current user as
`confirmed_by`. Conflict policy: existing auto rows (`trigram`,
`same_hs`) coexist as separate sources for the same pair (UNIQUE on
client+a+b+source). Rejected pairs silently skipped (caller intent
unclear); surface count in toast.

**Effort:** ~0.5 day (parser + route + UI button on catalog list).

## A.4.3 Smarter goods_name similarity (insignificant-diff folding)

**Captured 2026-05-10** during Feature 3 review. User: *"Cần thuật toán
thông minh hơn, tên hàng sai khác nhau không đáng kể"*.

Current INFO drift on `goods_name` flags any string-distinct value as
drift. Many cases are noise:
- whitespace / punctuation variants (`"M10x1.5P;G10;OIL"` vs `"M10x1.5P mm"`).
- different unit annotation in description (when `unit` itself doesn't drift).
- minor ordering of attributes.
- typos / abbreviation variants.

Need a similarity threshold or normalization pass that folds
near-duplicate descriptions into one bucket and only flags when the
difference is semantic (different product). Candidates:
- **Normalize then bucket**: lowercase + strip punctuation/whitespace +
  collapse digits to placeholder; identical normalized form = same bucket.
- **Token Jaccard ≥ threshold**: split on `[,.;\s]+`, intersection/union
  ≥ 0.85 = same bucket.
- **Trigram similarity ≥ 0.85** via pg_trgm (already enabled by Feature 4).

Output: bucket count + per-bucket representative + outlier list
("3 dòng có mô tả khác đáng kể"). Folds noise into a single chip with
`×N variants` annotation; surfaces only the truly different ones.

Wait until Feature 4 ships pg_trgm, then build on top of it. Keep current
naive implementation as fallback for clients without pg_trgm.

**Effort**: ~0.5-1 day after pg_trgm available.

## A.5 v_material_roles paren-aware (replace material_observations workaround)

**Captured 2026-05-09** (Mã chờ duyệt v3 review). Issue surfaced when
Growatt's NB material `001.0001100` showed `observed_count=0` on detail
page despite 68 BCCT references via paren-extract.

**Root cause**: `hub.v_material_roles` view JOINs by
`bcct_rows.customs_code` only. NB codes that live inside `goods_name`
parens (Growatt-shape) are invisible to the view. Affected fields:
`has_imports`, `has_exports`, `observed_count`, `observed_first_at`,
`observed_last_at`, `observed_directions`, `is_multi_role`,
`declared_observed_conflict`.

**Current workaround** (ships now, MUST be replaced):
- `app/stores/material_observations.py::compute_observations` —
  per-client (rules-driven, generic), recomputes signals from BCCT at
  request time using parser rules paren-extract.
- Wired into `/catalog/<code>/detail` only. **Not** wired into list
  page (`/catalog`), so the table still shows 0 for affected rows.
- 5 tests (`tests/test_material_observations.py`) cover the helper.
- Per-row Python work — fine for 1 detail page, NOT scalable to list
  view with hundreds of rows.

**Proper fix — 3 options:**

1. **Rebuild view as materialized view with re2-aware resolution.**
   Refresh on BCCT confirm + on parser_rules edit. Pros: fast reads,
   matches existing API. Cons: needs Postgres plpython3u extension OR
   external Python refresher script + materialized view.

2. **Generated/cached column on `bcct_rows`.** Add
   `bcct_rows.internal_code` (was dropped in mig 038), populated by a
   trigger on insert/update that runs the parser rules. View JOINs
   `b.customs_code = m.material_code OR b.internal_code = m.material_code`.
   Pros: SQL-only, no plpython. Cons: reintroduces dropped column;
   trigger must fire whenever rules change (re-derive existing rows).

3. **Replace view entirely with Python-computed materialization.**
   Cron job + a real `hub.material_observations` table refreshed on
   every BCCT/BOM change (post-ingest hook). Pros: fully decouple from
   SQL constraints. Cons: another batch job to maintain.

**Original recommendation**: option 2 (generated column). Most
surgical, no new infrastructure.

**Design re-examined 2026-05-13** (user deferred A.5 with "chưa rõ
lắm"). Original recommendation conflicts with memory
`feedback_no_derived_in_source`: source tables hold only manual input,
not derived/cached values — that principle drove mig 038 dropping
`material_identity` in the first place. Three options surveyed this
session:

- **B (original) — stored column + trigger.** Reintroduces
  `bcct_rows.internal_code`. Trigger has to run re2 parser rules on
  every insert + re-derive all rows whenever `client_parser_rules`
  change. pgsql has no re2; would need plpython3u OR an external
  Python refresher. Violates `no_derived_in_source`.
- **C — separate derived table.** New
  `hub.bcct_internal_codes (client_id, declaration_no, line_no, internal_code)`
  populated by Python (post-ingest hook + rules-change hook). View
  JOINs both `customs_code` and the derived table. Aligns principle:
  bcct_rows stays pure manual; derived data sits in its own table.
  Cost ~1-1.5d.
- **D — runtime Python supplement.** Wire existing `compute_observations`
  into the list page in batch mode (one BCCT query for ~100 codes per
  page render). ~2-4h. Solves the user-visible symptom (list page
  count) but keeps the workaround code and the view as-is. Only 1 of
  3 removal triggers met.

**Status:** deferred. Re-engage when bandwidth + clarity converge. If
shipped, prefer C over B; D is a tactical bridge if user wants the
list page fixed sooner.

**Removal trigger** for the workaround:
- View returns correct signals on `001.0001100` directly (no Python
  override needed).
- `material_observations.py` deleted; route handler skips supplement.
- List page `/catalog` "Quan sát BCCT" column shows correct counts
  for paren-extract NB materials.

**Effort**: 1-1.5 days for option B or C; ~2-4h for option D (partial).

## A.6 Scripts that lost SQL `material_identity` access (deferred 2026-05-08)

Mig 038 dropped `bcct_rows.material_identity` jsonb column. Three
scripts that did SQL-side `material_identity->>...` access now fall
back to `customs_code` only — degraded for Growatt-style imports
where the agency NVL code lives in goods_name parens.

1. **`scripts/settlement_resolver.py::_load_bcct_universe`** — used to
   collect distinct internal codes from BCCT rows for BCQT-side
   settlement matching. Now returns customs_code only. Rewrite to
   call `compute_internal_code(row, client=client)` per row in Python,
   then dedup. ~30 min.
2. **`scripts/detect_dual_source_btps.py`** — classifier for
   "imported BTP that's also self-produced". Used `material_identity`
   to match `b.<computed>=m.customs_code` for the import-count
   subquery. Now uses `b.customs_code = m.customs_code` only —
   under-counts Growatt imports because customs_code is the HQ-side
   "DOV"/"TEM.IN" bucket, not the agency NVL code in parens.
   Rewrite needs Python-side compute per row + GROUP BY in code.
   ~1h.
3. **`app/agent/tools.py::_query_bcct`** — agent tool that surfaced
   `internal_code` to the LLM for natural-language BCCT lookup. Now
   omits the field. Agent can still infer from goods_name. Lower
   priority — rewrite when agent feature ramps up.

All three are at the SAME architectural pinch-point: SQL-side
aggregation over jsonb that's no longer there. Generalized fix:
materialized view that re-derives material_identity for analytics
queries. Defer until performance pain emerges. Tightly coupled with
A.5 (same root cause).

---

# B. BOM upload & adapter infrastructure

Cluster around the BOM upload flow: UX polish, parser robustness,
adapter framework. Auto-detect default + manual_flat 4-shape SHIPPED
2026-05-13; remaining items below.

## B.1 Modular BOM ingest adapters (per supplier shape)

**Captured 2026-05-06.** Two distinct supplier-file shapes have
shipped so far:

- **Growatt-shape** — agency provides one file per code (TP and BTP
  separately). Ingest yields per-code `raw_graph` directly. Result:
  144/147 BTP shallow leaves are decomposable from their own
  `bom_artifacts` rows.
- **Johnson-shape** — agency provides one deep-tree file per TP.
  Ingest yields TP-level `raw_graph` only; intermediate BTPs have
  edges (in `hub.bom_edges`) but no `bom_artifacts` row keyed to them.
  Result: 0/342 BTP shallow leaves decomposable until a derive step
  runs.

Both shapes converge on the same in-DB model (raw_graph / shallow /
full_flat per `project_bom_3_shapes.md`, now 4-shape after 2026-05-13),
so the divergence lives entirely in the **parse + post-ingest** path.
Treat each supplier shape as a pluggable adapter / add-on.

**Goals:**

1. **Adapter interface** — formalize the contract: `detect(file) →
   match_score`, `parse(file) → list[bom_version_payload]`,
   `post_ingest_hooks → [...]`. New supplier shapes drop in as a
   registered adapter under `app/parsers/bom_adapters/` with no
   core-code changes. *(Mostly SHIPPED — `bom_adapters` registry +
   `parse_with_fallback` + `auto` profile (2026-05-13); post_ingest_hooks
   wired; **`detect → match_score` ranking SHIPPED 2026-06-07** — optional
   `detect(blob, root_code) → float|None` on the Protocol; abstain (None)
   preserves registration order = no regression; positive scores tried
   first. `detect` implemented on `sap_indented_walk` (0.95) +
   `sap_exploded_levels` (0.9) so deep-tree files no longer get grabbed
   + flattened by the more permissive `manual_flat`. Other adapters abstain;
   add `detect` as needed.)*
2. **`derive_btp_shallows.py`** — post-ingest hook for Johnson-shape
   adapter (and any future deep-tree shape). For each intermediate
   `parent_code` in `bom_edges` that is classified `btp_sx`,
   materialize a `bom_artifacts` row keyed to that code with
   `flatten_status='flattened'`,
   `flatten_strategy='purchased_btp_as_leaf'`, walking from that node
   down to first BTP/NVL leaves. After this runs, Johnson reaches
   Growatt-level decomposability and resolver Phase 3 can compose
   shallow → full_flat without knowing supplier shape.
3. **Canonical adapter registry** — extract current ingest scripts
   (`ingest_technical_raw_batch.py`, `ingest_curated_xlsx_direct.py`)
   into adapter classes: `growatt.py`, `johnson.py`, plus a
   `default.py` fallback. Selection by `client_id` + filename
   heuristics; UI override per upload.
4. **Phase 3 readiness** — resolver should rely only on the unified
   in-DB model, never on adapter-specific quirks. Divergence ends at
   parse-time, not propagated downstream.

**Why now:** v3 model has settled and we have two real shapes to
abstract from — one is enough to risk over-fitting, three risks
under-fitting, two is the sweet spot.

**Cross-link:** the **BCCT-side configurable parsing rules** shipped
2026-05-08 as `hub.client_parser_rules`. The BOM-side adapter work can
reuse the same table shape with `output_field='bom_*'`, unifying both
into a single per-client rule infra.

**Estimate (BOM-side only):** ~10-15h to formalize the registry +
extract scripts + write `derive_btp_shallows.py` + tests. Bundle with
Phase 3 resolver work since they share the "uniform in-DB model"
assumption.

## B.2 UI BOM upload — wire up v3 concepts (Phase 3c follow-ups)

**Captured 2026-05-05** + 2026-05-07 (consolidated). Auto-detect ship
2026-05-13 closed item 0; remaining items below. Some overlap with
B.1 (modular adapters) and Phase 3c (post_ingest_hooks).

1. **`bom_variant_id` field in upload form** — staff should pick a
   batch label (e.g. `agency_2026-05-05` or freetext) when uploading
   multiple supplier batches per product. Auto-derive default from
   filename or upload date if blank. Without this, multi-batch uploads
   via UI collide on `(product_code, default)` and trigger version-bump
   idempotency dedup.
2. **Auto-materialize post-upload** — when `technical_raw` confirms,
   trigger `materialize_shallow_and_full_flat` for the new
   `bom_artifacts` row inline (or async). Without this, shallow +
   full_flat versions only exist after a manual script run, which
   leaves the freshly-uploaded raw_graph orphan from BCQT/CO consumer
   queries. *(Partial — `post_ingest_hooks` registry wired into
   `app/routes/bom.py` confirm flow; explicit derive_btp_shallows hook
   registration still pending — see B.1.2.)*
3. **Auto-bootstrap BTP roster** — same trigger should re-run BTP
   detection (rule: parent_code in bom_edges + not a tp_root).
   Catalog `btp_sx` entries for newly-introduced intermediate codes
   land without a separate command.
4. **Shape badge in preview** — preview page currently shows flat rows.
   Add a header banner showing "This upload will create a `raw_graph`
   BOM" / "`manual_flat`" / "`shallow`" / "`full_flat`" so staff confirm
   with intent. Use `bom_shape()` helper (4-shape post-2026-05-13).
5. **Multi-role warning at upload** — *SHIPPED 2026-06-07.*
   `app/stores/bom_multirole.py::compute_multirole_warnings(client_id,
   products)` flags upload component codes that already appear in
   `bcct_rows.direction='export'` for this client. Advisory panel in
   `bom_preview.html` (non-blocking, like `multi_level_flat`); wired into
   `preview_view`. Matches on `customs_code` only — shares the A.5
   paren-code blind spot (acceptable for an advisory). Reference
   `project_bom_code_multirole.md`.
6. **Per-client policy gate** — `clients.auto_derive_shallow_from_raw`
   (`disabled` / `draft_only` / `publish`) should gate auto-materialize
   step. UI upload should respect the value: in `draft_only`, derived
   shallow/full_flat insert as `status='draft'` not `published`.
7. **Tests + docs** — Playwright E2E that drives upload → mapping →
   parse → preview → confirm and asserts shape + materialize side
   effects. Unit tests for the new auto-trigger functions. *(Partial —
   pytest regression `tests/test_bom_ingest_followups.py` (2026-06-07)
   covers auto upload→preview→confirm + the new detect ranking +
   multi-role warning + friendly parse-error. No browser-level Playwright
   E2E yet.)*

**Estimated effort**: 4-6h for items 1-6, +2-3h for tests + docs (item 7).

## B.3 BOM/BQD/Catalog parse-error UX — BOM side SHIPPED 2026-06-07

**BOM side SHIPPED 2026-06-07.** The 5 parse-error `HTTPException(400)`
sites in `bom.py::upload_submit` (auto no-match, technical_raw, rigid,
LLM-unavailable, LLM-mapping-rejected) now return
`_render_parse_error()` → `clients/bom_upload_error.html` (status stays
400, body is friendly HTML with recovery options + re-upload link) instead
of raw FastAPI `{"detail": ...}` JSON. The `Invalid profile` validation
guard intentionally stays a bare 400. **BQD/Catalog parse-error paths NOT
yet converted** — same treatment still open for them.

Original note (kept for the BQD/Catalog remainder):
Phase 2 universal preview-confirm pattern surfaces parsed
rows nicely when parsing succeeds. But when the parser rejects the file
outright (no LLM available, or LLM also fails), `app/routes/bom.py`
still raises `HTTPException(400, ...)` which the browser renders as raw
FastAPI JSON `{"detail": "..."}`.

Compare BCCT's `parse-mapping` error path which renders a proper
template with recovery options.

**Fix:** catch the final parse-error path and render an error template
or redirect with a `?error=...` toast (matching the post-upload toast
pattern from `c77da85`). Auto-detect 2026-05-13 already returns a
friendly Vietnamese 400 message but the rendering as raw JSON detail
remains.

## B.4 Manual mapping UI when LLM disabled

When LLM is unavailable AND a file fails rigid parse, the upload errors
with no recovery besides edit-in-DB. Add a "Manual mapping" link on the
parser-mapping preview when LLM is unavailable, surfacing the same
header→logical-field grid the LLM-confirmed flow uses. Reuses
`parser_mappings` cache once confirmed.

## B.5 Unified import UX across all data-import surfaces

**Captured 2026-05-12** during Phase 2 step 7 admin UI rollout. User
feedback: import flow của UoM-factors cần consistent với mọi surface
import dữ liệu khác (BCCT, BOM, Catalog, parser rules, code mappings,
declaration types, client-type-presets, ...). Hiện tại mỗi feature
implement import riêng → UX divergent.

**Common pattern phải có** ở mọi import surface:

1. **Download template button** (XLSX or CSV). Template generated
   on-the-fly từ store helper, có sample rows + sheet "Hướng dẫn".
   Giúp staff biết schema chính xác.
2. **Multi-format upload** (CSV + XLSX/.xlsm). Auto-detect by
   filename suffix. Both encode same column contract.
3. **Validation feedback**: row-level errors with row number + reason,
   capped to 20 displayed errors. "X inserted, Y failed — row N: ...".
4. **Idempotent semantic**: same source data, re-upload = no-op
   (upsert on PK).
5. **Source enum tagging**: each imported row gets tagged with
   `source='imported'` (or feature-specific) so audit trail
   distinguishes manual vs bulk.
6. **Confirm-before-write** pattern (matches BOM/BCCT preview-confirm
   flow): show "X rows will be added/updated, Y skipped" preview before
   committing. Currently UoM-factors imports immediately — this is OK
   for low-risk reference data but must change for higher-stakes
   imports.
7. **Audit trail per import**: who, when, file name + size, summary
   counts. Persisted to existing audit table.

**Inventory of import surfaces today** (audit needed):

| Feature | Status | Format | Template | Audit |
|---|---|---|---|---|
| BCCT upload | ✓ via parser | xlsx | — | upload_pending |
| BOM upload | ✓ via parser | xlsx | — | upload_pending |
| Catalog (DS DK HQ) | ✓ via parser | xlsx | — | upload_pending |
| `client_uom_overrides` | ✓ Phase 2 step 7 | csv + xlsx | ✓ | factor source enum |
| `client_parser_rules` | ? | — | — | — |
| `code_mappings` | ? | — | — | — |
| `declaration_types` | ? | — | — | — |
| `materials.uom` aliases | ? | — | — | — |

**Effort:** ~1 week. Sub-tasks:

1. **Audit + document existing import surfaces** (~0.5d). Walk each
   route + identify gaps vs the 7-point pattern.
2. **Design unified `ImportFlow` helper** at
   `app/stores/import_flow.py` (~2d). Generic CSV/XLSX parser with
   pluggable validation + commit functions. Each feature plugs in
   schema declarations.
3. **Refactor existing imports** to use the helper (~2d). Order:
   easiest wins first.
4. **Template generation convention**: each feature exposes
   `render_template_xlsx() -> bytes` returning an in-memory XLSX with
   header + sample rows + Hướng dẫn sheet. Endpoint at
   `/clients/{id}/<feature>/template.xlsx` or
   `/admin/<feature>/template.xlsx`.
5. **Unified UX template snippet** (`_import_form.html`) — Jinja2
   include rendering Download Template + File Upload + Source select +
   Submit, parametrized. Each feature uses it.

**Why deferred:**
- Phase 2 step 7 shipped a working CSV+XLSX import for one feature.
- The unified pattern requires understanding all current imports
  first — premature without that audit.
- Other features may have specific quirks (BCCT preview-confirm flow,
  parser-rules diff editor) that don't fit the simple-import pattern.

**Bring back when:**
- AI polish bandwidth.
- Or when adding a new import surface (do it right from start).
- Or after first customer ramps and import-flow inconsistency causes
  staff confusion.

---

# C. Sister-app coordination

Cross-repo work needed to bring CO + BCQT in line with Data Hub.
Sister-app notes live at `.ai/sister-app-notes/`.

## C.1 CO + BCQT — adopt service-account JWTs

**Captured 2026-05-02 PM.** Ship-blocking dependency for "API auth
strict promotion" below. No hard deadline — coexistence works fine.

Service-account JWTs are live in Data Hub (migration 020 + CLI). Sister
apps still call with permissive bearer / user JWT. To adopt:

1. **Mint tokens** (Data Hub admin):
   ```bash
   uv run python scripts/mint_service_token.py create \
     --name co --scopes hub:read,bom:propose \
     --client-ids growatt-vn,dke-vietnam-d0e3,johnson-vn,do-thanh-vietnam-2614 \
     --created-by <admin-email>

   uv run python scripts/mint_service_token.py create \
     --name bcqt --scopes hub:read \
     --created-by <admin-email>
   ```
2. **CO repo** (`barry-CO-main`): inject `DATA_HUB_SERVICE_TOKEN` env
   into `app/data_hub_client.py` Bearer header on every call. If CO
   verifies tokens locally, branch on `claims["typ"] == "service"` —
   service tokens have no email/role/name; `sub` is `svc:co`.
3. **BCQT repo**: same pattern, `hub:read` scope only.

Full instructions:
`.ai/sister-app-notes/2026-05-02-service-account-jwts-available.md`.
Design rationale: `.ai/features/2026-05-02-service-account-jwts.md`.

**Partial progress 2026-05-13**: substitute lookup mirrored at
`/v1/hub/clients/{c}/materials/{m}/substitutes` (Bearer-aware) after
CO reported 401 on the cookie-only `/api/v1/...` route. Note:
`.ai/sister-app-notes/2026-05-13-substitute-api-bearer-available.md`.
Other CO endpoints may have the same shape — audit if more 401s
surface.

**Pull this out of backlog when:** ready to coordinate the sister-repo
PRs, or when about to flip `api_auth_strict=true` (then it becomes
ship-blocking).

## C.1.a BCCT by-codes — soak test under real CO load

**Captured 2026-05-13** (this session). `GET /v1/hub/clients/{c}/bcct/by-codes`
shipped per CO API request
`barry-CO-main/.ai/api-requests/2026-05-13-bcct-by-codes-lookup.md`.
19 provider tests cover the contract (codes filter, case-insensitive,
URL-decoded, direction combine, pagination, all 4xx error paths,
service-token scope + whitelist enforcement). Live smoke against
Johnson confirmed correct rows + sub-100ms latency on small code lists.

**Not yet exercised:**

- **Real-load behaviour from CO**: only smoked with 2-3 codes against
  Johnson. CO's substitute modal calls with up to ~20 candidate codes
  + paginates if the resulting BCCT slice exceeds `limit`. Need to
  confirm latency stays low when CO is the actual caller (HTTP client,
  service token, real concurrent requests), not curl.
- **Pagination at boundary**: tests assert cursor round-trip on a
  2-row fixture. No test for a code with very long import history
  (e.g. a Johnson NVL with hundreds of TKN lines spanning multiple
  pages). Verify ordering stays stable across cursors.
- **`include_material_identity=true` with many rows**: tests cover
  attach correctness on 1 row. No assertion of per-row cost when the
  resolver runs across, say, 100 rows. Could surface a hot loop in
  `_attach_material_identity`.
- **DB plan**: SQL uses `where client_id = %s and upper(customs_code)
  = any(%s)`. Need to confirm Postgres uses the existing
  `(client_id, customs_code)` index (if any) or whether the `upper(...)`
  forces a seq scan on `bcct_rows`. EXPLAIN ANALYZE on Johnson once CO
  is hitting prod-shaped load.
- **CO consumer**: not yet shipped on CO side. CO `CLAUDE.md` requires
  Data Hub provider tests + changelog bump first (both done in this
  session). Awaiting CO ping-back via sister-app-notes when consumer
  ships.

**Pull this out of backlog when:** CO's consumer ships and we've
observed the endpoint under real substitute-modal load for at least a
day on the demo box. If latency or correctness issues appear, fold a
fix into this item; otherwise close out.

## C.2 API auth — flip dev-permissive reads to strict by default

**Captured 2026-05-02.** **Unblocked 2026-05-02 PM** — service-account
JWTs shipped (migration 020). Now waiting on sister-app cutover (C.1).

Today the read API on `/v1/hub/*` accepts non-empty legacy bearer
strings when `api_auth_strict=false` (default). Writes (BOM proposal
POST) always require a valid Data Hub JWT regardless of the flag. The
trade-off was chosen deliberately: prioritize dev/integration
ergonomics today, prioritize corruption prevention on writes.

**Promote when:**
- CO and BCQT have switched to service-account JWTs (per
  `.ai/sister-app-notes/2026-05-02-service-account-jwts-available.md`).
- We have a staging environment where strict mode can be soak-tested
  before flipping prod.

**Steps when promoting:**
1. Default `api_auth_strict=true` in fresh installs; add a one-time
   migration to flip existing installs after CO/BCQT confirm readiness.
2. Remove the legacy bearer fallback path in `_require_token`; keep
   only the JWT validation branch.
3. Update `docs/API_CONTRACT.md` to drop the dev-permissive mode
   section.
4. Update CO/BCQT consumer code to send real JWT on every read call.

## C.3 Drop BOM vocab v1 aliases — SHIPPED 2026-05-28

3-week grace period elapsed; sister apps verified clean of old URL
refs (CO + BCQT, `grep -rn "bom/version\|bom/versions"` zero hits).
`_alias_*` handlers in `app/routes/bom.py` + `app/routes/api.py`
deleted, the 3 redirect tests in `tests/test_bom_vocab_rename.py`
removed (schema + ID-prefix tests retained), `docs/API_CONTRACT.md`
alias section removed, `docs/API_CHANGELOG.md` Breaking entry added.

## C.4 `/v1/hub/products` — real `total` + cursor pagination (DEFERRED)

**Captured 2026-06-07** from CO API request
`barry-CO-main/.ai/api-requests/2026-06-07-products-total-count.md`.

`GET /v1/hub/products` is hard-capped at 50 with `total_estimate: null`
and no `next_cursor` — the route (`app/routes/api.py:1631`) calls
`list_products_with_bom(client_id, q=q)` with default `limit=50,
offset=0`, never honors a `cursor`/`limit`, never calls the existing
`count_products_with_bom()`. So any consumer that enumerates products
is silently truncated.

**The store layer already supports it** — `list_products_with_bom`
takes `limit`/`offset`, and `count_products_with_bom` returns an exact
count. The fix is route-wiring only:
1. Accept `cursor` + `limit` query params (validate → `400 invalid_cursor`
   / `400 invalid_limit`; server max e.g. 1000). Reuse the `_page_args`
   offset-cursor idiom already in the file.
2. Fetch `limit+1` to detect a next page; emit `next_cursor` (offset
   string) when more remain, else null.
3. Add `total = count_products_with_bom(client_id, q=q)`; keep
   `total_estimate` populated with the same value for back-compat.
4. Add `server_time`. Item payload unchanged.
5. Provider tests: exact `total` across pages, `next_cursor` non-null
   until last page, `sum(len(items)) == total` no dups, `limit` honored,
   negative cases (bad cursor/limit, scope/client 403), edge cases
   (0 products, exactly page-size, > page-size).

**Population note:** `/products` enumerates BOTH tp + btp products with
an alive (non-tombstoned) BOM artifact — `total` must match that
population (sum of `len(items)`). If CO specifically wants "# thành
phẩm (tp) có BOM" that is the `bom.product_count` in source-summary
(see the source-summary `bom` block work, shipped separately).

**Status: DEFERRED 2026-06-07.** CO does not need product enumeration
this way yet — its BOM dashboard headline is served by the
`source-summary.bom` block instead. Pull this out when a consumer
actually needs to page the full product list, or when the silent 50-cap
bites someone. ~2-3h (route + validation + tests).

---

# D. Aggregate data history

Single big-ticket item — generalizes the BOM immutability principle
(memory `project_bom_immutable_principle.md`) to other aggregate
tables. Touches every mutable hub table.

## D.1 Aggregate-data git-history

**Captured 2026-05-05** as a hard product principle from user.

**Principle (already enforced for BOMs, generalize to other aggregates):**

- Never physically `DELETE` rows from any aggregate-data table (BOMs,
  materials, code_mappings, client_config, parser_mappings, etc.).
- Edits = INSERT a new version with lineage back to the previous one.
- "Removal" is via tombstone / deactivation flag on the row, not row
  deletion.
- All aggregate data must support **git-like history**: who added what,
  who removed what, when, with revert / undo capability.

**Current state (HEAD as of 2026-05-05):**

| Table | History tracking | Gap |
|---|---|---|
| `bom_artifacts` + children | ✅ tombstone + parent_artifact_id lineage (mig 006/029) | Uses migration 027 cleanup pattern. Already conformant. |
| `bcct_rows` | ✅ `bcct_row_history` audit table + AFTER UPDATE/DELETE trigger (mig 013) | OK, but no UI for revert. |
| `materials` | ⚠️ `provenance` jsonb merge-on-conflict only | No history table. UPDATE overwrites name/category/unit/etc. |
| `code_mappings` | ❌ Plain table, UPDATE in place. | No history. |
| `client_config`, `parser_mappings`, `bom_flatten_decisions`, `client_uom_overrides`, `client_type_presets` | ❌ Plain tables. | No history. |
| `clients`, `users` | ❌ Plain tables. | No history (probably OK for users, debatable for clients). |

**Work units (each its own PR):**

1. **`materials_history` audit table + trigger** mirroring the
   `bcct_row_history` pattern. Capture full row before any UPDATE
   or DELETE, with `changed_at`, `changed_by` (read from
   `app.user_id` GUC), `change_kind ∈ {insert, update, delete}`.
2. **`code_mappings_history`** same pattern.
3. **`client_config_history`** + **`parser_mappings_history`** same.
4. **`/v1/hub/{table}/{key}/history` endpoints** — paginated audit
   timeline per entity.
5. **`/v1/hub/{table}/{key}/revert?to=<changed_at>`** — revert one
   row to a prior state. Implemented as INSERT-from-history (still
   append-only); audit captures it as a new change with
   `change_kind='revert'`.
6. **UI: history page per entity.** Reuse `bcct_row_history` page
   pattern. Diff view showing what changed.
7. **Document the "no DELETE" rule in `AGENTS.md` + standards repo.**
   Add a CI lint that scans for `DELETE FROM hub.<aggregate-table>`
   and fails on match unless explicitly tagged
   `-- ALLOW-DELETE: <reason>`.

**Why this matters:**

- Customs audit (TT 39/2018) requires 5-10 year retention of source
  data underlying settlement / origin certificates.
- Disputes between agency and customs auditor often hinge on "which
  version of the catalog/BOM/mapping was active when this transaction
  was filed?" — without history, the answer is "current state" which
  may not be the truth-of-record.
- Staff confidence: undo / revert lowers the cost of accidental
  destructive edits, which lowers the activation energy for staff
  to actually fix bad data.

**Out of scope for this backlog item:**

- BOM versioning is already done — don't redo it. The new history
  tables are for non-BOM aggregates.
- Operational tables (sessions, llm_usage, notifications,
  upload_pending) don't need this — they're transient.

---

# E. Architectural follow-ups

Items captured during /rev cycles or sprint retros that didn't make
the original cut. Smaller individually; bundle when convenient.

## E.1 Sprint D — parser/data architectural follow-ups (post-Sprints A/B/C)

**Captured 2026-05-03 PM** after Sprints A/B/C closed the immediate
correctness gaps. Each item below is its own PR (per plan-review
critic: "uncoupled changes — don't bundle"). No fixed order; ship in
parallel as bandwidth allows.

- **D1: `hub.declaration_types` lookup table.** *(SHIPPED — mig 019.)*
  Hardcoded `IMPORT_TYPES` / `EXPORT_TYPES` Python sets in
  `app/parsers/bcct.py` replaced with DB-seeded table sourced from
  Decision 1357/QĐ-TCHQ. Direction is now a SQL JOIN.

- **D2: `transaction_key` GENERATED ALWAYS AS column.** Make
  `transaction_key = '{declaration_no}-{line_no}'` a stored generated
  column on `hub.bcct_rows` so the invariant cannot drift. Migration
  touches every BCCT insert path; ship as its own PR.

- **D3: `normalized_hash` Decimal end-to-end + dual-version migration.**
  `app/stores/bom.py:normalized_hash` currently does
  `round(float(...), 9)` — float arithmetic drift undermines
  idempotency. Switching to Decimal changes every existing version's
  hash. Need a phase-in plan: compute v2 hash on writes, store both
  v1 + v2 during transition, dual-check on insert until backfill.

- **D4: Idempotency canonical-projection re-design.** Critic flagged
  that re-uploading the same Excel after fixing an unrelated catalog
  row currently silently dedup's because `normalized_hash` doesn't
  cover the upload-context dimension. Discovery doc first, then
  decide: log audit event on dedup-hit, OR widen the canonical
  projection, OR both.

- **D5: SAP indented-walk level-skip handling.** Reject (or pad with
  sentinel parents) BOM workbooks where indent levels skip
  non-contiguously (e.g. L2 → L4 missing L3). Need a real Johnson SAP
  sample exhibiting the case to reproduce — fixture
  `johnson_sap_english_headers.xlsx` may already cover it; verify
  before writing speculative code.

- **D6: BOM idempotency unique index audit.** Same
  uq_bom_idempotent_v2 design — verify the (`actor`, `intent`)
  column tuple is the right granularity vs upload identity.

- **D7: Fixture-pinned regression test for BOM-vs-CO compare.**
  Replace the gitignored `data/screenshots/_compare_report.md` with
  `tests/regression/test_real_bom_compare.py` env-gated, pinning
  per-file leaf-set match thresholds against checked-in fixture
  corpus.

- **D8: Cross-table `hub.integrity_findings` materialized view.**
  Surface every catalog-vs-BOM-vs-BCCT inconsistency in one place
  (orphan BTP_SX, UOM mismatches, ghost codes, etc.). Defer until 3+
  consumers want the same data — currently the per-page badges from
  Sprint B cover MVP need. Cross-link with A.4 (catalog material
  detail cross-source warnings).

- **D9: `bcct_rows.artifact_id` point-of-use binding.** Already
  designed in `.ai/features/2026-04-30-data-hub-mvp.md` (BCQT-side).
  Implement when BCQT migration sprint lands.

## E.2 Phase 3 review follow-ups (deferred 2026-05-07)

Captured during /rev of commits `5fb814a..dadbd0f`. Four Minor
findings deferred — low value individually, batch when convenient.

1. **Catalog matching column ≠ classifier matching column.**
   *Superseded 2026-05-09 by A.5 "v_material_roles paren-aware" entry
   above — same root cause, more concrete plan + workaround link.*
2. **`api_create_preset` body validation thin.** No name length
   cap, no whitespace strip, no charset restriction. Add
   `name = body["name"].strip()` + max length guard (e.g. 64).
3. **PATCH preset has no `updated_at` audit.** Mig 030 schema only
   has `created_at`; PATCH overwrites silently. Add
   `updated_at timestamptz` column via fresh migration; auto-touch
   in PATCH endpoint.
4. **`derive_btp_shallows` count-before/count-after `created` flag.**
   Fragile under concurrency. OK for single-threaded CLI.
   Migrate to `RETURNING xmax = 0` (Postgres-native "was this an
   insert?") if running multi-process becomes a thing.

## E.3 Parser-rules infra polish (deferred 2026-05-08)

Captured during the configurable-bcct-parsing bundle session
(commits `046601e..9dbbbca`). Core CRUD + UI + 3 test panel modes
shipped; below are nice-to-haves deferred:

1. **Playwright E2E** for `/clients/<id>/parser-rules` flow:
   create rule → test panel preview → disable → audit history.
   Memory `feedback_feature_folder_with_screenshots.md` requires
   committed screenshots for UI features.
2. **Per-key cache invalidation** for `_RULES_CACHE` in
   `app/parsers/client_parser_rules.py`. Currently any rule edit
   calls `clear_rules_cache()` which drops all cached entries
   process-wide. Benign at current scale (~5-10 clients × 1-2 output
   fields), but per-key drop would scale better.
3. **`preview_token` mechanism** on rule create/update endpoints
   (brief R2 belt-and-suspenders). Save-time would require user to
   have run preview within last N minutes against the same pattern.
   Defer until first real-world misconfig surfaces.
4. **CI workflow: soft-fail LLM `/models` smoke step**. Currently
   `Smoke LLM /models (best effort)` uses `bash -e` which propagates
   curl exit 22 (401 from upstream `codex-lb-demo.sgnai.dev`).
   Fix in `.github/workflows/<workflow>.yml`: add
   `continue-on-error: true` OR rewrite the step to gracefully
   handle non-2xx without exit. Today the workflow shows red on
   GitHub even when actual deploy + tests + API smoke pass.
5. **Memory updates** — pending verification across sessions:
   - `internal_code` + `material_identity` columns gone; live via
     runtime helpers.
   - Hardcoded growatt regex replaced by `hub.client_parser_rules`.
   - BCCT field semantic split: FX (`*_nt`) vs VND domains.
   - Resolver Stage 2 (paren-extract) wins over Stage 1 (customs).
   - Payload jsonb sparse; typed columns are source of truth.

## E.4 /rev cross-cuts (still open)

- **CSRF protection** on POST endpoints (pre-existing project gap).
- **`set_config('app.user_id', ..., false)`** — switch to `true`
  (LOCAL) if connection pooling lands. Today every `connect(user_id=...)`
  call gets a fresh connection, so SESSION-scoped GUC is fine.
- **Migration numbering gap** (010 → 012, no 011) — cosmetic; renaming
  applied migrations would diverge `schema_migrations` rows across
  environments.

---

# F. Data operations

Programmatic data-ops scripts driven by client onboarding + clean-up
needs.

## F.1 Growatt programmatic bulk re-ingest — SHIPPED 2026-05-28 + 2026-05-29

Both halves delivered (see "Shipped" section for the full record):
- **BCCT** — Growatt onboard session 2026-05-28 (`ccbb3ad`), incremental
  ingest.
- **BOM** — wipe + re-ingest 2026-05-29 (`03e9c4b`): 57 TP raws from 3
  source batches → 212 BTP raw_graphs derived → 269 raw_graphs × 3 shapes
  = 807 published artifacts, + 16 manual_flat restored from snapshot
  (no XLSX source to replay) = 823 artifacts on local + demo. 1260 tests
  pass. Session log: `.ai/sessions/2026-05-29-growatt-bom-wipe-reingest.md`.

The `scripts/bulk_reingest.py --client <id>` generalization (fold Johnson
+ Growatt into one tool) was **not** built — both ran via the existing
per-step scripts. Capture as a fresh item if a third client makes the
duplication worth abstracting.

---

# G. Polish & independent items

Smaller items not yet themed into a cluster.

(Currently empty — items pending classification go here as they
arise. As of 2026-05-13, nothing here.)

---

# Shipped — kept for context

Recent ships (2026-05-09 onward) annotated for cross-reference. Older
ships are in the legacy "Notes" section at the very bottom or removed
per `git log .ai/BACKLOG.md`.

## BOM UoM conversion engine (Phase 2 + Phase 3) — SHIPPED 2026-05-12 + 2026-05-13

**Phase 2** brief: `.ai/features/2026-05-12-bom-uom-conversion-phase-2/brief.md`.
Migrations 055-058. 18 commits + UX polish. +103 tests. Sub-tasks A
(ingest preview), B (refresh wires UoM), C (`client_uom_overrides`
admin UI), D (audit trail) all delivered.

**Phase 3 follow-ups** (E manual_flat drift signal + F
refresh-as-supersede + G refresh-time preview):
- E + F folded into Phase 2 ship (brief items 2/3/6).
- G shipped 2026-05-13: `plan_refresh()` pure planner +
  `commit_refresh()` with `skip` + `edits` params; GET preview route
  + template; POST extensions for skip/inline_factor; UI swap to GET
  preview default; no-op detection with "Xác nhận đã xem". 18 new
  tests. Reused `hub.bom_audit_events` (mig 006) for `refresh.skipped`
  events — no new audit table. Brief:
  `.ai/features/2026-05-13-bom-refresh-preview/brief.md`.

## UoM standardization table — SHIPPED 2026-05-10

Mig 051 + `app/stores/uom_standards.py`. Reused existing
`hub.uom_canonical` + `hub.uom_aliases` (mig 021); extended with 10
new canonicals + ~50 aliases covering real BCCT data. Wired into
`_uom_drift` warning (only fires on real semantic conflict) and
candidate refresh (canonical buckets, not raw alias counts).

**Per-agency override (`client_uom_aliases`)**: NOT shipped — deferred.
Only needed when an agency uses an alias that conflicts with another
client's canonical mapping.

**Admin UI polish — DEFERRED 2026-05-10** (user: "chưa hài lòng lắm,
sẽ quay lại sau"). Pending improvements: edit canonical inline;
delete with FK protection; conversion factor explorer; group aliases
under canonical; per-client `client_uom_aliases` override + UI;
better empty-state; tooltip / docs explaining `base_factor`.

## Mã chờ duyệt — passive candidate feed — SHIPPED 2026-05-09

Mig 047 created `hub.catalog_candidates` + `hub.catalog_candidate_rejections`
+ added `hub.materials.production_source` enum. Route
`/clients/<id>/catalog/candidates` shipped. Replaced the deferred
`catalog_derive_configs` rule-form design.

Brief: `.ai/features/2026-05-09-ma-cho-duyet/brief.md`.

## Candidate richness — match catalog row fields — SHIPPED 2026-05-09

Mig 048 (extra stats: import/export/decl counts, bom_role,
co-occurrence) + Mig 049 (richness: hs_code, uom, origin,
inferred_production_source). Refresh logic enriches candidates from
BCCT + BOM. Accept form prefills these fields so staff don't drop
sparse materials into catalog.

## Track D BOM staleness — SHIPPED 2026-05-11 + 2026-05-13

Captured 2026-05-10 as part of BOM vocab + 3-shape audit. 8 dimensions
of staleness identified; option 1 (staleness flag + manual refresh)
picked over options 2-4. Phase 1 mig 053+054 (`is_stale` flag + 5
triggers D1/D7/D8/D2±). Phase 2 mig 055-058 (Phase 2 UoM, D9
catalog-insert trigger). Phase 3 G (refresh preview). Memory
`project_bom_staleness.md` captures the model.

## BOM upload — auto-detect adapter — SHIPPED 2026-05-13

Adds `auto` as the default option in BOM upload form. Calls
`bom_adapters.parse_with_fallback()` with filename stem as
`root_code` hint; first adapter producing non-empty rows wins. Skips
mapping page; lands on `/bom/preview/<id>` with
`proposed_by='parser_auto:<adapter>'`. Friendly Vietnamese 400 when
all 5 adapters fail. Manual override preserved.

## Manual_flat 4-shape model — SHIPPED 2026-05-13

`bom_shape()` returns `'manual_flat'` for `manual_flat_as_provided`
strategy (was conflated with `'shallow'`). `BomShape` Literal
extended to 4 values. Memory `project_bom_3_shapes.md` updated.

## UI rename "tombstone" → friendly Vietnamese — SHIPPED 2026-05-13

UI/template/i18n only — code/DB/API stay `tombstone`. Mapping:
catalog material → "đã loại"; BOM artifact lineage / replace → "đã
thay thế"; preset retract → "thu hồi". 9 files edited.

## BCCT by-codes lookup — SHIPPED 2026-05-13 (soak test pending → C.1.a)

`GET /v1/hub/clients/{client_id}/bcct/by-codes?codes=A,B,C` per CO API
request `barry-CO-main/.ai/api-requests/2026-05-13-bcct-by-codes-lookup.md`.
Row shape mirrors `/v1/hub/bcct`; case-insensitive exact match against
`customs_code`; max 100 codes/request; same auth model + `hub:read` scope.

Motivation: CO's substitute-stock derivation needed to paginate the
full 65k Johnson BCCT (~30s) just to derive stock for ~20 candidate
codes. Splitting "Data Hub returns BCCT slice" + "CO applies its own
`allocation_code`/`lot_policy` rules" keeps CO config out of Data Hub
(consistent with the 2026-05-02 `/co-config → /client-config` rename).

`app/routes/api.py` (+ `_parse_codes_param` helper). 19 provider tests
in `tests/test_bcct_by_codes_api.py`. `docs/API_CONTRACT.md` +
`docs/API_CHANGELOG.md` updated.

**Soak test pending — see C.1.a.** Provider tests cover the contract,
but real-load behaviour from CO (concurrent requests, long-history
codes, `include_material_identity` on large slices, EXPLAIN ANALYZE
under prod-shaped data) has not been validated. CO consumer not yet
shipped — awaiting their consumer PR per their CLAUDE.md rule (Data
Hub provider tests + changelog must land first; both done).

## Bearer-aware substitute API mirror — SHIPPED 2026-05-13

Triggered by CO blocker report: `GET /api/v1/clients/{c}/materials/{m}/substitutes`
returned 401 for any Bearer token. That route used cookie-only
`auth.require_user`; sister-app server-to-server can't carry the cookie.

New mirror at `/v1/hub/clients/{c}/materials/{m}/substitutes`
(`app/routes/api.py`). Uses existing `_require_token` +
`_require_can_view_client` (user JWT or service token with `hub:read`,
`client_ids` whitelist honored). Same response shape. Cookie route
preserved for in-app catalog detail page. 7 tests. Sister-app note:
`.ai/sister-app-notes/2026-05-13-substitute-api-bearer-available.md`.
Commit `ae3373b`.

Partial unblock of C.1 (sister-app cutover) — other cookie-only routes
under `/api/v1/...` may need the same mirroring as CO usage expands.

## A.7 BOM parser — extract "Object description" — SHIPPED 2026-05-13

`_DESCRIPTION_ALIASES` constant added in `sap_indented_walk.py` covering
EN ("Object description", "Description", "Material description"), VI
("tên hàng", "mô tả"), and ZH ("物料描述", "物料名称"). Both the leaf-emit
adapter (`SapIndentedWalkAdapter.parse`) and the raw-edge parser
(`parse_sap_indented_raw_edges` in `bom_edges.py`) capture description.
Raw path stores into `bom_edges.payload->>'description'` (jsonb,
no schema mig). `catalog_candidates._backfill_sample_from_bom` added
as fallback after `_backfill_sample_from_bcct`: picks most-recent alive
artifact's description for BOM-only candidates. +5 tests. Re-ingest
Johnson BOM still pending to backfill descriptions for existing rows.

## Johnson programmatic bulk re-ingest — SHIPPED 2026-05-11

Originally captured here as F.1 (programmatic plan, ~1 week). Shipped
in session 2026-05-11 via 4 existing scripts rather than a single
`bulk_reingest_johnson.py` tool. Commits `11ea9bd` + `dcc6216` +
`cac2bcb` + `e7578bf`. Session log:
`.ai/sessions/2026-05-11-johnson-onboarding-ship.md`.

**What landed:**
- Wipe: `scripts/setup_clients_for_reingest.py` — cascade DELETE from
  `hub.clients`, recreated client row.
- BCCT ingest: `scripts/ingest_johnson_real.py` →
  NK 60,173 + XK 5,673 = 65,846 rows / 37s.
- BOM ingest: `scripts/ingest_technical_raw_batch.py` — 106
  SAP-exploded XLSX → 27,848 raw edges across 106 TP raw_graphs.
- Post-BOM catalog fixup:
  `scripts/fixup_johnson_btp_sx_after_bom.py` — inserted 2,615
  missing BTP_SX (`source='bom_observed'`) + reclassified 416
  `nvl→btp_sx`.
- Post-ingest hooks (`derive_btp_shallows` + `materialize_shapes`)
  ran via adapter registry.

**Bugs caught + fixed during verification:**
- BTP artifact bloat (8,837 → 3,337, 2.6× reduction): BTP slice
  edges preserved TP-context fields (`level`, `node_path`,
  `source_row_no`, `sheet_name`) so identical slices under different
  parents produced different `normalized_edges_hash` → no dedup. Fix
  in `derive_btp_shallows._subtree_edges`. Also passed
  `parent_artifact_id=None` to bypass per-TP dedup fragmentation.
- UI hook resolution gap: `parse_raw_edges_with_fallback` returned
  adapter names (`sap_indented_raw`, `growatt_factory_technical`)
  not registered in `bom_adapters._REGISTRY`. Fixed via
  `_LEGACY_ALIASES` mapping → silent no-op hooks now fire.

## Growatt programmatic bulk re-ingest — SHIPPED 2026-05-28 + 2026-05-29

Closes open F.1. Same playbook as Johnson, run via existing per-step
scripts (no single `bulk_reingest.py` tool).

- **BCCT** — onboard session 2026-05-28, commit `ccbb3ad`
  (`docs(handoff): Growatt 2026-05 onboarding + volume bug fix + backup
  pipeline session`). Incremental ingest.
- **BOM** — wipe + re-ingest 2026-05-29, commit `03e9c4b`. 57 TP raws /
  3 source batches → 212 BTP raw_graphs derived → 269 raw_graphs × 3
  shapes = 807 published + 16 manual_flat restored from snapshot
  (`agency_rescued_only_gom` + `TEST_TP_DRIFT`, no XLSX to replay) = 823
  artifacts on local + demo. Johnson dedup fix (`7552c64`) already in
  place → clean BTP count (212 vs old 427). 1260 tests pass. Session log:
  `.ai/sessions/2026-05-29-growatt-bom-wipe-reingest.md`. Memory:
  `project_reingest_pending.md` (Growatt marked SHIPPED),
  `feedback_wipe_enumerate_unreplayable.md` (lesson on enumerating
  unreplayable buckets pre-wipe).

---

# Notes

The previously-tracked items below have all shipped (verified in HEAD
as of 2026-05-02 PM):

- Pre-commit upload preview at all stages → `359ebec` Phase 2.
- Catalog multi-source provenance + auto-derive from BCCT → `6141d1e` A4.
- BCCT (and all 4 tab) staleness metadata → `53da49b` A3.
- Parser bugs A/B/C/D from 2026-05-02 real-data smoke → `338be91` Phase 1.
- BCCT confirm-on-update gate + history page → `b3a59d6` + `91d2ca7`.
- LLM smart parser → `175d1f8` (BCCT) + `5d44b60` (BOM/BQD).
- /rev cache `use_count` overcount + `Path(stored_path).read_bytes()`
  FileNotFoundError → `2e8cd05`.
- Apply confirm-gate pattern to catalog/bqd/bom (was a cross-cut from
  prior /rev) → `359ebec` Phase 2.
- Service-account JWTs → migration 020, `app/jwt_issuer.py:make_service_token`,
  `scripts/mint_service_token.py`, `tests/test_service_account_jwts.py`
  (13 new tests, 232 total).

These were removed from this file on 2026-05-02 PM. See git history of
`.ai/BACKLOG.md` for the original entries.
