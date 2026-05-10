# Notes for CO + BCQT — Phase 2 UoM conversion + Phase 3 G refresh-preview shipped

**Provider:** Data Hub  ·  **Consumers:** CO, BCQT
**Date:** 2026-05-12 (Phase 2) + amended 2026-05-13 (Phase 3 G + Round 3 manual_flat refresh)

Required reading before CO/BCQT consumers next read BOM derived rows
from Data Hub. Phase 2 changes how `hub.bom_artifact_rows.uom` and
`qty_per_unit` are computed for derived shapes (`flatten_strategy in
('technical_exploded', 'purchased_btp_as_leaf',
 'self_produced_btp_exploded', 'mixed_confirmed')`).

This is a **breaking change** for consumers that assumed derived row
UoM matches raw BOM row UoM. **Ship-fast / accept-breakage stance**:
Data Hub flips behaviour without per-client gate; sister apps catch
up async on their own schedule. Dev phase reset path
(`project_reingest_pending.md`) means no in-flight production data
to migrate.

**This note is amended** with Phase 3 G changes shipped 2026-05-13.
See "Phase 3 G addendum" at the bottom for the delta. The body below
is the authoritative current state.

## What changed in Data Hub

### Behaviour: Refresh now converts UoM (Phase 2 step 2b)

Previously, `_rederive_shape` (refresh path) walked `bom_edges` raw
SQL and copied `e.uom` directly. Derived rows shipped with raw UoM
even when `materials.uom` (catalog) declared a different canonical.
Settlement / origin-cert calculations using BCQT/CO were quietly
inconsistent across raw vs catalog UoM.

After Phase 2: each derived row is converted to `materials.uom` at
refresh time via `convert_qty + make_uom_lookup` (precedence stack:
`client_uom_overrides` → `uom_canonical` family → alias → tier-A
default). Output rows ship with `uom = catalog.uom` (or raw UoM if
factor missing — see drift handling below).

### 3-tier conversion policy (Phase 2 step 2a)

When source ↔ target are cross-family canonicals:

- **Tier A** — both families ∈ `{count, count_packaging, assembly}`
  (e.g. EA → SETS, EA → CAY, SETS → CAY): factor defaults to 1.0,
  source = `'unconfirmed_default'`. Derived artifact gets
  `is_stale=true` reason `unconfirmed_default_1to1`. Used as
  warning-with-result while staff confirms factor.
- **Tier B** — count ↔ mass / mass ↔ length / etc.: returns None →
  `uom_conversion_missing`. Refresh keeps RAW qty + RAW uom (no
  silent corruption); derived artifact stays stale with reason
  `factor_missing`. Staff must populate `client_uom_overrides`
  factor row before refresh succeeds.
- **Tier C** — same family different canonical (gam → kg):
  auto-converts via `uom_canonical.base_factor`, no flag.

### Refresh = mint new + supersede old (Phase 2 step 3)

Different-hash refresh result tombstones the original artifact:
`tombstoned_at = now()`, `tombstone_reason =
'superseded_by_refresh:<new_id>'`. Lineage preserved via existing
`parent_artifact_id`. Same-hash refresh just clears the stale flag.

Consumers that **track artifact_id** (BCQT settlement project ledger,
CO certificate refs) MUST handle tombstoned-since-last-read case:
artifact may now be tombstoned with a successor pointed to by
`tombstone_reason`. Pattern: follow the chain to the latest
non-tombstoned descendant, or use the pre-existing
`/v1/hub/products/{p}/bom/latest` endpoint which always returns the
live one.

### Schema additions

#### `hub.client_uom_overrides` (mig 055)

Existing table extended:

- `is_cross_family boolean NOT NULL DEFAULT false` — auto-computed
  via trigger. Read-only for staff (trigger always recomputes).
- `notes text` — staff annotation.
- `source` enum extended: `+supplier_data, packaging_spec,
  derived_average, imported`.

API impact: `client_uom_overrides` is internal to Data Hub — no
sister-app endpoint exposes it. Consumers don't read this directly.

#### `hub.bom_artifact_rows` (mig 056) — UoM audit columns

```
source_uom         text       -- raw uom row started with
applied_uom_factor numeric    -- factor multiplied
applied_uom_source text       -- 'alias' | 'global' |
                                  'client_specific' | 'client_wide' |
                                  'unconfirmed_default'
```

CHECK constraint on `applied_uom_source` enum.

API impact: if BCQT/CO consume `bom_artifact_rows` directly via DB
read (not via `/v1/hub` endpoints), **add these to your projection
list** for forensics.

Per-row audit columns (`source_uom`, `applied_uom_factor`,
`applied_uom_source`) are NOT yet surfaced on the per-row API
response. The artifact-level drift fields ARE — see "Drift fields
on API responses" below.

Pre-Phase-2 rows have NULLs in these columns (no backfill — data
wasn't tracked at write time).

#### `hub.bom_artifacts` (mig 057) — manual_flat UoM drift

```
has_uom_drift          boolean NOT NULL DEFAULT false
uom_drift_reasons      jsonb   NOT NULL DEFAULT '[]'
uom_drift_first_at     timestamptz
uom_drift_resolved_at  timestamptz
```

Distinct from `is_stale` (mig 053): applies to **source** artifacts
(`flatten_strategy in ('manual_flat_as_provided', 'no_strategy')`).

**Updated 2026-05-13 (Round 3):** `manual_flat_as_provided` artifacts
ARE now refresh-able. Refresh reconstructs originals from the audit
columns (`source_uom` + `applied_uom_factor`) and re-applies UoM
conversion using current catalog + override state. The original
"Re-upload BOM" UX was reversed — both stale and drift use the same
"Refresh" action. `raw_graph` artifacts still require re-upload
(edges-only model, no audit columns).

#### Triggers

- **D7 extension** (mig 057): `materials.uom` UPDATE now also marks
  source artifacts (manual_flat + raw_graph) with `has_uom_drift`,
  in addition to derived artifacts via `is_stale`.
- **D9** (mig 058, NEW): `materials` INSERT fires same staleness
  path. Closes order-independence gap when BOM artifacts reference
  codes that catalog gains LATER.

## API contract changes (sister-app action items)

### BCQT (settlement, Mẫu 15a)

1. Re-read `/v1/hub/products/{p}/bom/latest` for any project that
   queries Data Hub BOM. UoM in returned rows may now be different
   from previous snapshot — derived rows are now in catalog UoM.
2. Settlement output (Mẫu 15a NPL consumed) uses `qty_per_unit *
   bcct_imports`. Both sides must use canonical UoM. Check that
   BCCT-side aggregation joins by `customs_code` AND converts
   `bcct_rows.unit → catalog uom` before multiplying. Don't rely on
   "if BOM uom and BCCT unit happen to match string, no conversion
   needed" — catalog UoM is now the canonical.
3. Tombstoned artifacts: settlement project should detect via
   `bom_artifacts.tombstoned_at IS NOT NULL` and follow
   `tombstone_reason='superseded_by_refresh:<new_id>'` to the
   successor when surfacing artifact references in audit reports.

### CO (origin certificate, per-shipment)

1. CO certificates referencing specific `artifact_id` may need to
   refetch when those artifacts get superseded by refresh.
   `tombstone_reason` field gives the new id.
2. CO writes per-shipment BCCT via Data Hub API — no change to
   write contract, only to read.
3. Materials catalog UoM (`materials.uom`) may evolve as staff
   populates `client_uom_overrides`. CO certificate rendering should
   prefer real-time read of `bom_artifact_rows.uom` over caching.

## Migration order (recommended)

Data Hub shipped Phase 2 mig 055-058 + code (commits `99953e8`,
`fc09725`, `2677cc4`, `2ecb6f4`, `04cf077`, `2c7f409`) on 2026-05-12.
Phase 2 step 7 admin UI for `client_uom_overrides` shipped same day
(commit `29c1a25`).

Sister apps:

1. Confirm tests still pass against Data Hub dev DB after mig 055-058.
2. Update consumer code per "API contract changes" above.
3. Johnson factor table population pending (220 cross-family rows
   from `agency_qa_johnson.xlsx` — agency Q&A blocked). After
   population + reset + re-ingest, sister apps verify they consume
   the new state correctly.

## Drift / staleness UI surfaces

- `is_stale` — derived artifacts; clearable by Refresh action.
- `has_uom_drift` — source artifacts (manual_flat + raw_graph).
  Manual_flat clearable by Refresh (re-applies via audit columns,
  Round 3); raw_graph clearable by re-upload OR catalog UoM edit.
  D7 trigger updates `uom_drift_first_at` on entry; `_clear_stale`
  helper sets `uom_drift_resolved_at` when flags clear (mig 057
  workflow IS implemented).

Both flags are advisory — consumers MAY honor them (skip artifacts
with active drift in critical reports, or surface a warning) but
MUST NOT treat them as hard-block. Tombstoned artifacts are
hard-block (don't surface in any consumer-facing output).

## Drift fields on API responses

Single-artifact reads (`/v1/hub/products/{p}/bom/latest` and
`/v1/hub/products/{p}/bom?artifact_id=…`) include all four columns
on `artifact`:

- `is_stale`, `stale_reasons`, `stale_first_at`, `stale_resolved_at`
- `has_uom_drift`, `uom_drift_reasons`, `uom_drift_first_at`,
  `uom_drift_resolved_at`

List endpoint `/v1/hub/products/{p}/bom/artifacts` exposes
`is_stale`, `stale_reasons`, `has_uom_drift`, `uom_drift_reasons`
on each item (added 2026-05-13 in commit `1876dea` for sister-app
list-traversal use case).

Sister-app pattern: when displaying a BOM artifact in your UI, check
`is_stale || has_uom_drift` and show a warning badge linking to Data
Hub's artifact detail for staff to refresh / re-upload.

## Cross-references

- Brief: `.ai/features/2026-05-12-bom-uom-conversion-phase-2/brief.md`
- Memory: `project_uom_drift_gate.md`, `project_bom_staleness.md`,
  `project_ingest_order_invariance.md`,
  `project_bom_immutable_principle.md`.
- Migrations: 053, 054, 055, 056, 057, 058.
- Test harness: `tests/test_ingest_order_invariance.py`.

---

## Phase 3 G addendum (shipped 2026-05-13)

Refresh-time conversion preview shipped end-to-end. **No new migration
or schema change**. Sister-app impact is limited because the preview is
a UI flow; the API surface and audit trail are the only things sister
apps may interact with.

### What changed

1. **`refresh_artifact()` was refactored** into a thin wrapper around
   a new `commit_refresh()` (in `app/stores/bom_staleness.py`).
   Existing public signature unchanged; behaviour for callers who
   pass no extra params is identical.
2. **`commit_refresh()` accepts two new optional params** (only used
   from the new GET preview UI flow):
   - `skip=True` — write a `refresh.skipped` audit event and return
     without state change. Artifact stays as-is.
   - `edits=[{material_code, from_uom, to_uom, factor, source}]` —
     upsert these factor rows into `client_uom_overrides` BEFORE
     re-planning the refresh. Used by inline factor edit on the
     preview screen.
3. **Pure planner `plan_refresh()`** — re-walks SQL or reconstructs
   manual_flat originals, runs the conversion engine, returns a
   `RefreshPlan` with per-row plan + drift summary + would_be_hash.
   Pure (no DB writes). Used by GET preview render.

### Audit trail event type

Sister apps that read `hub.bom_audit_events` will see a new
`event_type` value:

```
event_type='refresh.skipped'
details = {
  blocking_count: int,                     -- rows the plan flagged blocked
  row_count: int,                          -- total rows in the plan
  skipped_reason_from_plan: text|null      -- if planner had its own skip reason
}
```

Existing event types (`version.created`, etc.) unchanged. No new
audit table — the existing `hub.bom_audit_events` shape (mig 006)
fits this event verbatim. Future "skip pattern" review queries can
filter on `event_type='refresh.skipped'`.

### URL surface

Two URL changes (UI-only, sister apps don't drive these):

1. **NEW** `GET /clients/{client_id}/bom/artifact/{artifact_id}/refresh/preview`
   — renders the conversion plan template. HTML response, requires
   session-cookie auth (not bearer). Sister apps don't call this.
2. **POST** `/clients/{client_id}/bom/artifact/{artifact_id}/refresh`
   accepts new optional form fields `skip=1`,
   `inline_factor_<i>_<key>`. Direct POST without these stays
   identical to before.

### Read-API impact

None new in Phase 3 G beyond the list-endpoint drift columns already
documented above. Tombstone-on-supersede semantics from Phase 2
unchanged.

### Manual_flat refresh — Round 3 reversal

Phase 2 step 6 originally implemented `has_uom_drift` for source
artifacts with the UX direction "Re-upload BOM, not Refresh". Round 3
(commit `1e495d7`) reversed this: manual_flat artifacts CAN now be
refreshed via audit columns. The drift block in artifact detail uses
the same Refresh button as the stale block. Sister-app implications:

- A manual_flat artifact you read today MAY be tombstoned tomorrow
  via refresh-supersede (same as derived). Follow `tombstone_reason`
  to the successor.
- The previous note "Re-upload BOM" in your UI badges should change
  to "Refresh" (or just "thay đổi") for parity with derived.

### Cross-references (Phase 3 G)

- Brief: `.ai/features/2026-05-13-bom-refresh-preview/brief.md`
- Memory: `feedback_reuse_audit_events.md` (why no new audit table)
- Commits: `8119e69` (refactor), `b694e81` (preview), `f7c82bd`
  (POST extensions), `de1beea` (UI swap), `ea750b7` (no-op tests),
  `3269d76` (close-out + screenshot).
