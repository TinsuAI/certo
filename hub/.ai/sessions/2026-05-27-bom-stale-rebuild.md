# BOM stale-UX rebuild + Johnson drift audit

**Date:** 2026-05-27
**Branch:** `main` → `5cdf7fe` (3 commits this session)
**Scope:** Local DB + code + tests + UI + docs. Demo not yet synced.

## What was done

### 1. Johnson stale audit (continuation of 2026-05-25 session)

Started with "Cac van de stale cua Johnson hien tai da giai quyet duoc
chua?" — Johnson dev DB had 1,336 actionable rows on `/bom/stale`.

- Inventoried the 39 (turned out 21) genuinely unresolved drift codes
  from the 2026-05-25 STATUS.md note.
- Inserted 21 per-material overrides on local DB:
  - 20 × EA→SETS=1.0 (residual btp_sx codes not in the 156-batch).
  - 1 × EA→Chai/Lọ/Tuýp=1.0 for `1000202688` (dầu bôi trơn 20ml/chai).
- Catalog fix: `1000430256` uom `G → EA` (btp_sx auto-capture bug
  same root cause as 2026-05-25 440-batch — Component unit canonical).
- 2 materialize cleanup-stale passes → active stale 2,812 → 11.

### 2. Provenance name backfill gap (forward-only patch)

User asked: why do many BOM-only codes have no name? Audit:
- 9,310 Johnson codes have `name` from BCCT (`goods_name`).
- 3,822 codes (btp_sx + nvl `bom_only`) have `name = material_code`
  (placeholder) because BOM XLS has no description column.
- The bom_only set is **disjoint** from BCCT-visible set; no backfill
  source on local DB.
- Forward fix: `derive_from_bcct` on-conflict path now fills `name`
  when current value is placeholder (NULL / empty / = material_code).
  Future BCCT ingest will populate these rows.

Commit `99abbec`.

### 3. /bom/stale UX audit → rebuild

User feedback prompted a full audit. Documented in `/audit lai cai
logic stale di xem hop ly khong` + `tao thay no phien qua, tao ra
rat nhieu thu can giai quyet tren UI ma user khong hieu gi ca`.

Diagnosis (full version in
`.ai/features/2026-05-27-bom-stale-rebuild/brief.md`):

- Page mixed action-queue + audit-log semantics.
- Triggers fire unconditionally → false positives accumulate.
- 8 dim labels in engineer jargon (tombstone, hook, derive…).
- No bulk action, no pagination, no self-healing.
- `_primary_action` showed "Reupload" for manual_flat (bug — refresh
  path works).
- 2,719 tombstoned artifacts retained `is_stale=true`.

Rebuild path A (vá nhỏ) + B (tái thiết kế) requested as a single push.

### 4. Migrations 067–071 (commit `637046e`)

- **067** Clear flags on tombstone (trigger + backfill).
- **068** `state` generated column ∈ {clean, needs_refresh,
  needs_input, broken}. Stored, auto-maintained via Postgres GENERATED
  ALWAYS AS, partial index on non-clean.
- **069** `hub.is_uom_aligned(a, b)` + conditional D7/D9. Triggers
  skip flagging when NEW.uom alias-aligns with BOM row uom.
- **070** Backfill round 1: clear alias-aligned false-positives.
- **071** `hub.has_drift_remaining(client, code, bom_uom)` (extends
  alignment with override lookup) + trigger refactor + backfill round 2.
  Cleared 919 raw_graph false-positives (override-resolved cross-family
  pairs: EA→CAY, EA→METRIC-TONS, EA→KILO-GRAMMES, EA→SETS, EA→Chai/Lọ/Tuýp).

Johnson result: 1,336 → 20 needs_input artifacts. Growatt: 1.

### 5. Self-healing reconcile + UI rebuild (commit `5cdf7fe`)

- `reconcile_for_material(client_id, material_code, cap=50)` in
  `bom_staleness.py`. After catalog edit / override CRUD, walks
  affected NON-clean artifacts and refreshes derived/manual_flat,
  re-checks raw_graph alignment via `has_drift_remaining`. Returns
  counts (refreshed, cleared, deferred, errors).
- Wired into:
  - `app/routes/catalog.py::edit_material_submit`
  - `app/stores/client_uom_overrides.py::{create,update,delete}_factor`
- `/clients/{cid}/bom/needs-action` — cluster page by
  (cause × related_code). Bulk refresh button per cluster. Pagination.
  3 state tabs.
- `/clients/{cid}/bom/audit-log` — forensic event log.
- `POST /clients/{cid}/bom/refresh-cluster` — bulk refresh up to 200
  artifact_ids in one POST.
- Legacy `/bom/stale` removed (308 redirect → /needs-action so
  bookmarks land). Template + dead helpers + dead i18n keys pruned.
- i18n: bom.stale.* (8 dim labels + tab labels + action labels) →
  bom.state.* / bom.cause.* / bom.action.* in plain Vietnamese.
  EN parity. Inline-badge keys (badge/heading/tooltip/refresh) kept.
- API: `artifact.state` field exposed additively in
  `/v1/hub/products/{p}/bom` + `/bom/artifacts`. Documented in
  `docs/API_CONTRACT.md`. Sister-app notes at
  `.ai/sister-app-notes/2026-05-27-bom-state-field-shipped.md`.
- 4 screenshots committed under
  `.ai/features/2026-05-27-bom-stale-rebuild/screenshots/`.

## Final state

```
Johnson (local):
  clean:        10,255 artifacts
  needs_input:  20 (11 derived + 9 raw, all from 1000469803 open item)
  needs_refresh: 0

Growatt (local):
  clean:        606
  needs_input:  1
  needs_refresh: 0

Migrations: at 071.
Tests: 1,224 pass, 15 skip.
Demo box (ttdatahub.tinsu.ai): NOT synced.
```

## Decisions

1. **State column = stored generated, not trigger-maintained.** Postgres
   auto-maintains from `is_stale` + `has_uom_drift` + reasons jsonb.
   Aligns with `feedback_no_derived_in_source` carve-out documented in
   brief 2026-05-11 decision 7 (acceptable cache).

2. **Conditional triggers via SQL helper, not Python.** D7/D9 alignment
   check must run inside the trigger. Helper `hub.is_uom_aligned` +
   `hub.has_drift_remaining` are pure SQL/plpgsql, can be called from
   trigger body. Python `uom_lookup` not reachable from DB.

3. **B's "queue + worker" pattern dropped.** After mig 069+071 conditional
   triggers + A5 reconcile-on-edit, the self-healing goal is met without
   a new queue table. No async job runner exists yet; adding one for
   this alone would over-engineer.

4. **Removed /bom/stale entirely, not deprecation-banner.** Banner-then-redirect
   was the first attempt; user pushed back ("bỏ cái cũ đi cho đỡ confusing").
   Replaced with a 308 permanent redirect. Sister-app deeplinks still land.

5. **Cluster key = (cause × related_code).** Not (cause × artifact).
   Multi-cause artifacts span multiple cluster rows. Trade-off accepted:
   cluster page title shows N clusters while tab badges show artifact
   counts — slight inconsistency noted in brief Open items.

## What didn't work

- **First test of `_primary_action`** failed because I called the old
  signature without the new `source_bom_kind` arg. Fixed before commit.
- **`test_d9_marks_derived_artifact_stale_on_catalog_insert`** broke
  after mig 069 because it relied on unconditional flagging. Updated
  to use non-aligned uoms (EA vs kg, cross-family).
- **Reconcile cap logic** — first implementation fetched `cap + 1` rows
  and derived deferred from `len(affected) - cap`. With 60 affected and
  cap=50, this reported deferred=1 instead of 10. Switched to `COUNT(*)`
  query then separate `LIMIT cap` fetch.
- **`/refresh-all-stale`** route (planned in brief 2026-05-11) still
  not shipped — superseded by per-cluster bulk refresh. Considered
  cleaner; one button per cluster, no "do everything in 1 click" giant
  hammer.
- **State column attempted as `state ENUM`** first, switched to TEXT
  with CHECK constraint. ENUM in Postgres is rigid (ALTER TYPE requires
  outage-style management); TEXT + check is the project convention
  (see chk_actor, chk_intent in mig 066).

## Open items

1. **`1000469803`** (Johnson) — 11 derived + 9 raw artifacts still
   flagged. BOM has mixed EA/KG uoms across parents. Needs Johnson
   evidence (override or catalog correction).
2. **Demo box sync** — local DB + code at `5cdf7fe`; demo at `bc4fb3b`.
   Pending: push origin + scp+pg_restore the 5 new migrations + docker
   compose up app.
3. **3,822 placeholder-name codes** — patch covers future BCCT ingest
   but no backfill source available locally. If Johnson provides SAP
   master data sheet, bulk-fill.
4. **Header count discrepancy** on /needs-action — `total` (cluster
   count) vs tab badges (artifact count). Cosmetic; low priority.
5. **CO + BCQT consumer migration** — `state` field is additive, not
   blocking. Consumers can pick up at leisure. Sister-app notes posted.
6. **/bom/audit-log paging UX** — currently shows minute-bucketed
   events. May want hour or day grouping at scale (>10k events) — not
   yet needed.

## Files touched

3 commits, ~2,000 lines added:
- 5 migrations (`db/migrations/067-071*.sql`).
- 1 new store helper (`app/stores/bom_staleness.py::reconcile_for_material`).
- 2 new routes (`/bom/needs-action`, `/bom/audit-log`,
  `POST /bom/refresh-cluster`) + 1 redirect (`/bom/stale`).
- 2 new templates (`bom_needs_action.html`, `bom_audit_log.html`).
- 1 deleted template (`bom_stale.html`).
- i18n cleanup + new keys.
- Store wiring: catalog edit, override CRUD, provenance.
- Tests: 36-test new module + 8 added/updated.
- 4 screenshots + brief + sister-app note + API contract update.
- 1 screenshot script.

## Verification

- `uv run pytest tests/ -q` → 1,224 pass, 15 skip.
- SQL state check: `SELECT state, count(*) FROM hub.bom_artifacts WHERE
  client_id=...` → matches expected distribution.
- HTTP smoke: `curl /bom/stale → 308 → /bom/needs-action`.
- Live UI smoke captured in 4 screenshots.

## Next steps

1. Demo box sync (migrations + code + verify).
2. Memory updates (this session reinforced
   `feedback_no_derived_in_source`, `feedback_uom_factor_evidence_driven`,
   `project_bom_staleness` — should update the staleness memory).
3. Watch for `1000469803` resolution from Johnson.
