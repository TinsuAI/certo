# 2026-05-10 PM — BOM vocab cleanup + 3-shape grouping + UoM ingest gate

**Commits**: `2ec028f` (Track A), `fbb910d` (Track B), `06026a2` (Track C),
`69407ea` (STATUS refresh).
**Tests**: 772 → 820 (+48). 0 fail, 15 skip.
**Brief**: `.ai/features/2026-05-10-bom-vocab-3shape-uom-gate/brief.md`.

## What Was Done

### Audit (start of session)

User opened by viewing `/clients/johnson-vn/bom` and asked 3 questions:

1. Why "variants" word still in UI — vocab supposed to be dropped post-mig-031.
2. Does BOM ingest handle UoM conflict between BOM file and catalog/BCCT?
3. Does UI reflect "1 phiên bản = 3 shape" model from glossary?

Audit found:
- `bom.html:108-109` badge "×N variants" actually counted distinct
  `flatten_strategy` (= shape distinction), not supplier batches.
  Misleading vocab + misleading semantic.
- `bom_artifacts.html`, `bom_artifact_detail.html`, `_bom_macros.html`,
  `bom_preview.html`, `bom_presets.html` all hardcoded `'default'` for
  null `bom_variant_id` instead of hiding.
- `i18n.py` had "version" / "variants" misuse in 12+ keys both VN/EN.
  `bom.bom_variant` VN was "Phiên bản BOM" — clashed directly with
  glossary "phiên bản" (logical tuple).
- UoM cross-source: `_uom_drift` warning only at view time
  (catalog detail) and flatten engine. **No ingest-time gate** at BOM
  raw upload or BCCT upload preview.
- 3-shape vs 1-version: schema had no first-class identifier for
  logical phiên bản (lineage tree root).

### `/discover` — feature brief

Mid-session user added Track D (dependency staleness concern). Brief
expanded to 4 tracks; A/B/C in-scope this session, D deferred to
BACKLOG. Brief at `.ai/features/2026-05-10-bom-vocab-3shape-uom-gate/brief.md`.

User answered the 4 open questions:
1. Track B trigger pattern → BEFORE INSERT (computed column can't
   reference parent row).
2. Track C ack checkbox → required ONLY on `warn_cross_family` severity.
3. Track A column rename → drop "v" letter entirely; badge `#{n}`.
4. Cadence → 3 commits same session, A → B → C sequential.

### Track A — vocab cleanup (`2ec028f`)

- Drop "v" badge → "#" everywhere (5 templates).
- Hide-when-default rule for `bom_variant_id`: 5 sites, conditional
  rendering only when value is non-default supplier batch.
- `app/stores/bom.py::list_products_with_bom`: drop the
  `n_dual_variants = n_strategies` rename — template uses
  `n_strategies` directly.
- `bom.html:108`: badge fires on `n_strategies > 2` (= true dual-source
  materialization, not standard 2-strategy shallow + full_flat).
- `app/i18n.py`: VN canonical → "bản lưu" / "shape" / "preset"; EN →
  "artifact" / "shape" / "preset".
- `bom.bom_variant` VN: "Phiên bản BOM" → "Đợt".
- Tests: `tests/test_bom_vocab_track_a.py` (21 — direct Jinja for
  macros + i18n.t() asserts + TestClient render).
- Screenshots: 4 PNG via `scripts/screenshot_track_a.py`.

### Track B — lineage_root_id (`fbb910d`)

- **Mig 052**: `bom_artifacts.lineage_root_id text NOT NULL` + BEFORE
  INSERT trigger + recursive-CTE backfill (852 rows / 2.5ms) + index.
- Trigger: parent NULL → self-root; else inherit parent's
  lineage_root_id; defensive fallback for orphans.
- `list_products_with_bom`: new fields `n_logical_versions`,
  `n_artifacts`, `latest_artifact_no` + compat aliases for old keys
  (`n_versions`, `latest_version`).
- `bom.html` column "Versions" → "Phiên bản" sortable on
  `n_logical_versions`. Cell: badge `n_logical_versions` + meta
  "· N bản lưu · N non-flat".
- `BOM_SORT_WHITELIST` accepts both old + new sort keys.
- Tests: `tests/test_bom_lineage_root.py` (12 — schema + trigger +
  backfill + grandchild-chain + 2 separate roots + store).

### Track C — UoM ingest-time gate (`06026a2`)

- New helper `app/stores/uom_drift.py::compute_uom_drifts(client_id, rows)`.
- 3-tier severity:
  - `warn_cross_family` (mass vs count) — banner red, ack required.
  - `info_family` (gam ↔ kg) — display only.
  - `info_unknown` (alias not in `hub.uom_aliases`) — display only.
  - `info_alias` (PCS == PIECE) — display only.
- `has_blocking_drift(drifts)` returns True iff any
  `warn_cross_family`.
- Wired into `app/routes/bom.py::preview_view` (flattens nested
  `products` → row list) and `app/routes/bcct.py::upload_preview_view`
  (maps BCCT `customs_code`/`unit` → helper expected shape).
- Reusable banner template `app/templates/clients/_uom_drift_banner.html`,
  included via `{% include %}` from `_upload_preview.html` (BOM) +
  `bcct_upload_preview.html`.
- Inline JS disables primary submit button until ack checkbox checked.
- **Non-mutating**: surface only, flatten engine still converts at
  materialize time via `uom_canonical.base_factor`.
- i18n keys `uom_drift.*` for both VN + EN.
- Tests: `tests/test_uom_ingest_drift.py` (15 — 11 helper + 4 route
  integration).
- Live verified: Growatt PV01.0105100 (PIECES) + 001.0001100 (ST)
  with file UoM kg/g → 2 warn rows + ack required + screenshot.

### Track D — DEFERRED to BACKLOG

Captured `.ai/BACKLOG.md` entry "BOM dependency staleness" with:
- 8 dimensions of external-state change that silently stale BOM
  artifacts (catalog category, BTP BOM appearance, accept candidate,
  code mappings, parser rules, UoM aliases, materials.uom edit,
  btp_sourcing flip).
- 4 design options (staleness flag / eager cascade / lazy compute /
  event-sourced ledger).
- Preliminary recommendation: option 1 MVP → option 4 post-MVP.
- Cross-links 3 existing entries that overlap dimension.

## Decisions Made

1. **3 commits split, same session, sequential**. Rejected bundle
   (uncoupled scopes — critic-rejection risk). Rejected multi-session
   (10-13h fits 1 working block).
2. **Track A drops "v" letter entirely** (not just rename column).
   Badge `#{n}` matches BCCT row_index pattern; "v" letter contradicts
   glossary regardless of column header.
3. **Track A keeps `bom_variant_id` schema unchanged.** 852 production
   rows have non-default values (Growatt agency_2026-04-23-btp etc.) —
   legitimate supplier-batch concept. Hide-when-default is UI rule, not
   schema rule.
4. **Track B option 2** (stored column + trigger) over option 1 (CTE
   per pageview). Backfill 2.5ms — well within 60s budget. Recursive
   CTE per pageview wouldn't scale at customer count.
5. **Track B keeps backwards-compat aliases** (`n_versions`,
   `latest_version`) on store dict. Templates not yet migrated still
   work; eventual cleanup deferred until consumer migration.
6. **Track C non-mutating principle**. Flatten engine converts
   deterministically via `uom_canonical.base_factor`. Auto-converting
   at ingest would lose provenance + idempotency. Gate only surfaces.
7. **Track C ack required only on `warn_cross_family`.** Same-family
   drift (gam ↔ kg) is routine convertible — gate would be noise.
   Cross-family is red-flag → require explicit ack.
8. **Track D deferred from session.** Scope >> A+B+C combined; needs
   own discovery + dependency-edge audit. Captured concretely so it
   doesn't get lost.

## What Didn't Work

- **First test fixture for `bom_artifacts` insert** used
  `source_channel='staff_upload'` — failed `chk_source_channel` constraint.
  Valid values: `agency_upload, staff_form, co_proposal, migration, seed`.
  Fixed to `staff_form`.
- **BCCT test fixture missing required columns**: `quantity` (not
  `qty`); `year` is generated column → must set `registration_date`
  instead.
- **Initial `bom.html` badge condition** `n_strategies > 1`: every
  Johnson product would trigger because typical = 2 (shallow +
  full_flat). Changed to `> 2` so badge fires only on real dual-source
  materializations.
- **Wrong template Edit position**: Track D inserted between B and C
  by accident (Edit anchored on "### Track C" header). Moved with
  follow-up edit. Reminder: when prepending sections, anchor on
  preceding section's end-marker, not the next section's header.
- **Dev server died mid-session** between Track B and Track C smoke
  tests. Restarted. Hot-reload picks up changes; long-running sessions
  occasionally need uvicorn restart.

## Open Items

### Now (next session)
- **Track D — BOM dependency staleness**: 1-2d discovery + design
  before implement. Preliminary recommendation in BACKLOG entry. Likely
  trigger: customer demo surfaces stale full_flat after catalog edit.
- **STATUS.md** has `.ai/sessions/2026-05-10-ma-cho-duyet-and-uom-standards.md`
  untracked from morning session — should commit when convenient.

### Later (per BACKLOG priority)
- v_material_roles paren-aware (~1-1.5d) — proper fix for
  `material_observations.py` workaround.
- UoM admin UI polish (deferred 2026-05-10 AM session).
- Phase 2 catalog (`roles[]` + drop `category`).
- Wipe + re-ingest fresh Growatt + Johnson — pre-MVP one-shot reset.

### Architecture LOCKED — don't relitigate
- Drop "v" letter from artifact_no badges everywhere; use `#{n}`.
- Hide `bom_variant_id` when `'default'` or NULL across all 5 sites.
- `lineage_root_id` is the logical-phiên-bản key; trigger maintains
  invariant on insert.
- UoM drift gate is non-mutating; flatten engine handles convert.
- Cross-family drift requires explicit staff ack; same-family is
  info-only.

### Files written (full list)

```
NEW:
  .ai/features/2026-05-10-bom-vocab-3shape-uom-gate/brief.md
  .ai/features/2026-05-10-bom-vocab-3shape-uom-gate/screenshots/01..05_*.png
  db/migrations/052_bom_lineage_root_id.sql
  app/stores/uom_drift.py
  app/templates/clients/_uom_drift_banner.html
  scripts/screenshot_track_a.py
  scripts/screenshot_track_c.py
  tests/test_bom_vocab_track_a.py
  tests/test_bom_lineage_root.py
  tests/test_uom_ingest_drift.py

MODIFIED:
  .ai/BACKLOG.md          (Track D entry)
  .ai/STATUS.md           (refresh)
  app/i18n.py             (VN/EN vocab + UoM drift keys + new col labels)
  app/routes/bcct.py      (UoM drift wired into preview view)
  app/routes/bom.py       (UoM drift wired + sort whitelist accepts new keys)
  app/stores/bom.py       (n_logical_versions + n_artifacts + compat aliases)
  app/templates/clients/_bom_macros.html         (#-badge, hide-default)
  app/templates/clients/_upload_preview.html     (banner include)
  app/templates/clients/bcct_upload_preview.html (form id + banner include)
  app/templates/clients/bom.html                 (new col + #-badge + n_strategies)
  app/templates/clients/bom_artifact_detail.html (#-badge, hide-default Variant row)
  app/templates/clients/bom_artifacts.html       (#-badge, conditional variant col)
  app/templates/clients/bom_presets.html         (#-option, hide-default)
  app/templates/clients/bom_preview.html         (conditional variant col)

MEMORY:
  feedback_bom_vocab.md (extended with Track A enforcement rules)
  project_bom_lineage_root.md (NEW)
  project_uom_drift_gate.md (NEW)
  MEMORY.md (index updated)
```
