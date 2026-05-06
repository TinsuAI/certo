# Session 2026-05-06 — BOM version UI: human parent labels + Lineage panel

Short focused session. Started as "smoke-test the v3 UI we shipped
yesterday on real Growatt + Johnson data" and turned into a UX fix
when the user noticed the parent column was rendering opaque
`bv_TpkPzPfhs…` UUIDs.

## What Was Done

### 1. Dev server bring-up

Stopped the docker-compose stack (was running with its own internal
DB volume, not v3 schema) and started uvicorn natively on port 8754
pointing at the local v3 Postgres. `DATA_HUB_AUTO_SEED_DEMO=0` so the
auto-seed cleanup script doesn't touch real client data. Background
task `bxx7b797v`, log at `/tmp/data-hub-dev.log`.

### 2. UI smoke harness — verify v3 ship is healthy

Wrote `.ai/features/2026-05-06-bom-v3-ui-smoke/ui_smoke.py` (playwright
headless). Targets:
- `growatt-vn / SD00.0010600` (the 130-vs-484 product from yesterday's
  investigation — has 6 alive versions across multiple variants/shapes)
- `johnson-vn / MFW0502-571` (single supplier batch, 3 versions)

For each: captures BOM list page → versions list → version detail
(full page + viewport-top). Screenshots committed under
`screenshots/`. UI rendered correctly: variant/shape/source columns
present, Provenance panel populated.

### 3. UX issue — opaque parent UUIDs

User flagged: "cái cột parent hiển thị `bv_TpkPzPfhs…` thì user làm
sao tra cứu được?" Recommend three options:

- **Option 1**: replace UUID prefix with parent's human label
  (`v#·shape·variant`), make whole cell clickable.
- **Option 2**: drop the parent column from list view entirely.
- **Option 3**: add a Lineage graph section to the detail view.

User picked **1 + 3**.

### 4. Implementation (single commit `2d9dbfb`)

**Store layer (`app/stores/bom.py`):**
- `list_versions_for_product` self-joins `hub.bom_versions` to fetch
  parent's `version_no`, `bom_variant_id`, `flatten_status`,
  `flatten_strategy`. Derives `parent_shape` via `bom_shape()` helper.
- New `get_lineage_for_version(version_id, max_depth=12)` walks the
  parent chain (cycle-safe via `seen` set seeded with starting
  version_id) and fetches direct descendants. Returns
  `{ancestors, descendants, truncated, missing_parent_id}`.

**Route layer (`app/routes/bom.py`):**
- Imports `bom_shape` and `get_lineage_for_version`.
- Detail route derives `version["bom_shape"]` once, calls lineage
  helper, passes both into template.

**Templates:**
- `clients/_bom_macros.html` (new) — `shape_badge(shape)` and
  `lineage_node(node, current_id, client_id)` macros, shared.
- `clients/bom_versions.html` — parent column renders
  `[v#] [shape_badge] · variant`-link; falls through to `(deleted)`
  when parent row is gone.
- `clients/bom_version_detail.html` — "forked from" header uses human
  label; new Lineage panel below Provenance shows ancestors → THIS
  (highlighted with `▸` prefix and blue border) → descendants
  (indented). Renders `(deleted parent: …)` marker when chain breaks
  and "older ancestors hidden" marker when `truncated=True`.

**CSS (`app/static/css/app.css`):**
- `.badge-shape-raw-graph`, `.badge-shape-shallow`,
  `.badge-shape-full-flat` — extracted from inline styles.
- `.lineage-panel`, `.lineage-chain`, `.lineage-arrow`,
  `.lineage-truncated`, `.lineage-deleted`, `.lineage-descendants`,
  `.lineage-node`, `.lineage-node--current`,
  `.lineage-node--tombstoned`, `.lineage-node-current-marker`,
  `.lineage-node-meta`, `.lineage-node-variant` — full set of
  classes for the Lineage panel.

### 5. /rev → 7 fixes in same commit

After initial implementation, ran `/rev`. Findings:

- **Important #1**: List view didn't handle orphan `parent_version_id`
  (LEFT JOIN returns NULL fields → empty `v` badge + empty shape
  badge). 0 orphans currently in DB but BOM-immutable rule has pre-
  MVP exceptions — could happen.
- **Important #2**: `get_lineage_for_version` double-fetched every
  ancestor (once as `current`, once as `parent_id` lookup, then
  re-fetched as `current` next iter). 12-deep walk = 25 queries
  instead of 13.
- **Important #3**: Shape derivation duplicated between Python
  `bom_shape()` and template inline `{% set shape = ... %}` — DRY
  violation, divergence risk.
- **Minor #4**: `seen` not seeded with starting version_id → self-
  loop edge case appends version to its own ancestors.
- **Minor #5**: `max_depth` truncation silent — no signal to UI.
- **Minor #6**: Inline styles bloating templates.
- **Minor #7**: `cur.description` reused across queries (defensive).

User said: "fix hết luôn đi" → all 7 landed in same commit.

### 6. Verification

- 57/57 BOM-related tests pass (`pytest -k bom`, 4.2s).
- Re-ran UI smoke; rendered HTML confirmed presence of new classes
  (`badge-shape-raw-graph`, `lineage-panel`, `lineage-node`,
  `lineage-node--current`, `lineage-node-current-marker`,
  `lineage-node-meta`, `lineage-node-variant`, `lineage-arrow`,
  `lineage-chain`, `badge-shape-full-flat`).
- Visual inspection of viewport-only screenshots: list view shows
  parent badges correctly; detail shows Provenance + Lineage panels
  side-stacked.

## Decisions Made

- **Option 1 + 3, not Option 2**: preserving info while making it
  legible beats hiding it. "Lineage as a first-class section" gives
  the v3 3-shape model concrete provenance UX.
- **Variant on parent column only when different from current row's
  variant**: avoid noise. Within-variant parents don't need to repeat
  the variant string.
- **`max_depth=12` for lineage walk**: deeper than any current chain
  (current chains are 2-3 deep) but bounded for safety. Future
  resolver+profiles work in Phase 3 may produce longer chains.
- **`(deleted)` marker, not silent removal**: surfaces information
  loss to user. Tooltip preserves the dangling UUID for power users.
- **Macros in shared partial (`_bom_macros.html`)**: matches the
  existing `_pagination.html`, `_client_nav.html` pattern. Keeps
  templates DRY.
- **Bundle all `/rev` fixes in same commit**: user explicitly preferred
  this. Treat bundled-fix as default unless findings are large enough
  to warrant separate PRs.

## What Didn't Work

- **First pass on `get_lineage_for_version` was wasteful** — fetched
  each ancestor twice. Caught by `/rev`. Fixed by reusing the parent
  row as next iteration's `current` view.
- **Inline `{% set shape = ... %}` in detail template** — was a
  Round-1 implementation shortcut that survived through Round-2
  initial smoke. `/rev` flagged the duplication with Python
  `bom_shape()`. Fixed by deriving in route once, passing
  `version.bom_shape` to template.
- **Default `seen = set()`** — self-loop edge case bug. Fixed with
  `seen = {version_id}`.

## Open Items

These are all carry-overs from prior sessions, not introduced today:

1. **Push `2d9dbfb` to origin** — pending. Will let CI/CD deploy
   the UI polish to demo.
2. **Demo data parity** — still the #1 product priority. Demo at
   ttdatahub.tinsu.ai has v3 schema+code but old synthetic data.
   Pick `pg_dump → scp → restore` (~30 min) for pre-MVP demo.
3. **Phase 3** — resolver + profile CRUD + sourcing_choice intent +
   auto-rule + UI integration. ~25-35h per critic.
4. **`detect_dual_source_btps.py`** — small script.
5. **Restore `bom_proposal_mode='auto'`** for Growatt + Johnson.
6. **24 stale `mapping_pending` file_uploads** — cosmetic cleanup.
7. **Multi-role schema improvement** (Phase 3+).

New today (low priority):
- Lineage panel currently shows parent's `intent` + `actor` in the
  meta line. May want to add `created_at` to help users reason about
  ordering when version_no isn't enough. Defer until users complain.
- The "(N forks)" descendants header could link to a filter view if
  the count grows large. Currently fine — max 2-3 forks per node.

## Files Changed (cumulative this commit)

- `app/routes/bom.py` (+11 lines)
- `app/stores/bom.py` (+104 lines)
- `app/static/css/app.css` (+52 lines)
- `app/templates/clients/_bom_macros.html` (+31 lines, NEW)
- `app/templates/clients/bom_version_detail.html` (+59 / -34)
- `app/templates/clients/bom_versions.html` (+24 / -7)
- `.ai/features/2026-05-06-bom-v3-ui-smoke/ui_smoke.py` (+101, NEW)
- `.ai/features/2026-05-06-bom-v3-ui-smoke/screenshots/*.png` (8 files, NEW)

## Post-Commit Discussion (uncommitted artifacts)

After commit `2d9dbfb` and the first `/handoff`, conversation
continued into design clarification and triggered three additional
artifact updates (none code; all docs / memory / backlog).

### A. Refined memory `feedback_bundle_rev_fixes.md`

First version of this memory framed the rule as "treat AI's
structured output as a punch list to execute, not a menu to
negotiate." User pushed back: "nhưng chắc gì list đó đã certify là
việc cần làm?" Correct point — AI list isn't auto-certified. Refined
the rule to:

1. AI presents **all** findings, including weak ones, marked clearly
   (low-confidence, "may be wrong because X", edge case unlikely).
   Silent dropping = hiding info, conflicts with "never be a black
   box".
2. AI does **not self-defer** parts of its output (no "ship-ready
   after #1; the rest can wait"). User certifies which to fix.
3. Default proposal is **bundle-execute** — "I can fix all of these
   now". User decides if partial.

User declined adding to dotfiles knowledge — keep Claude-only.

### B. New memory `project_bom_3_shapes.md`

Triggered by user spotting AI repeatedly mis-stating the shallow
shape rule ("không xuống tới NVL"). Created canonical 3-shape
definition with worked example (the cây user provided —
`TP X → BTP A1 → BTP B1, B2 → NVL C1, C2, C4`) and side-by-side
comparison of what each shape produces. Key insight captured: shallow
walker is **depth-agnostic**, stops at first leaf which can be NVL
**or** BTP. Verified empirically on Johnson MFW0502-571 (10 BTP
boundaries + 8 NVL leaves + 5 unclassified).

### C. New backlog item: "Modular BOM ingest adapters"

Triggered by analyzing decomposability of BTP shallow leaves:

- Growatt: 144/147 BTP shallow leaves have own `bom_versions` row →
  shallow → full_flat composition feasible directly.
- Johnson: 0/342 BTP shallow leaves overlap with own-bom BTPs →
  composition NOT feasible from shallow alone today, BUT data exists
  in raw_graph and just needs derivation.

User correctly pointed out: this is an **ingestion gap**, not an
architectural difference. Both agencies converge on the same in-DB
model once `derive_btp_shallows.py` runs. Backlog item formalizes:

- Adapter interface (`detect`, `parse`, `post_ingest_hooks`).
- `derive_btp_shallows.py` post-ingest hook for deep-tree shapes.
- Registry under `app/parsers/bom/adapters/` with `growatt.py`,
  `johnson.py`, `default.py`.
- Phase 3 resolver consumes only the unified in-DB model.

Open decision (chốt vào Phase 3): `derive_btp_shallows.py` as
adapter-attached post-ingest hook vs standalone job that runs after
all adapters. Lean toward hook for automation; alternative is on-
demand derivation in resolver itself.

### D. Concept correction worth recording

The "0 decomposable for Johnson" empirical finding initially read
like an architectural problem. It is not. The two supplier shapes
converge on the same 3-shape data model — the divergence lives
entirely at parse time. This rewrites the Phase 3 resolver mental
model: it never needs to branch on agency-shape, only on data
presence (which the adapter pipeline guarantees).
