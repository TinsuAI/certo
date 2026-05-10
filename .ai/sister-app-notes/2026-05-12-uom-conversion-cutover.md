# Notes for CO + BCQT — Phase 2 UoM conversion shipped

**Provider:** Data Hub  ·  **Consumers:** CO, BCQT  ·  **Date:** 2026-05-12

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
list** for forensics. Existing endpoints (`/v1/hub/products/{p}/bom/*`)
do not yet surface these columns; future endpoint expansion will.

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
(`flatten_strategy in ('manual_flat_as_provided', 'no_strategy')`)
which cannot be re-derived. Semantic = "Re-upload BOM" rather than
"Refresh".

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

Data Hub already shipped Phase 2 mig 055-058 + code (commits
`99953e8`, `fc09725`, `2677cc4`, `2ecb6f4`, `04cf077`, `2c7f409`).
Sister apps:

1. Confirm tests still pass against Data Hub dev DB after mig 055-058.
2. Update consumer code per "API contract changes" above.
3. After Phase 2 step 7 admin UI ships + Johnson factor table is
   populated (220 rows from `agency_qa_johnson.xlsx`), run reset +
   re-ingest dry on staging. Sister apps verify they consume the
   new state correctly.

## Drift / staleness UI surfaces

- `is_stale` — derived artifacts; clearable by Refresh.
- `has_uom_drift` — source artifacts; clearable by Re-upload BOM
  OR catalog UoM edit (D7 trigger fires `uom_drift_resolved_at`
  workflow — TODO: not yet implemented; Phase 2 step 5 UI work).

Both flags are advisory — consumers MAY honor them (skip artifacts
with active drift in critical reports, or surface a warning) but
MUST NOT treat them as hard-block. Tombstoned artifacts are
hard-block (don't surface in any consumer-facing output).

## Cross-references

- Brief: `.ai/features/2026-05-12-bom-uom-conversion-phase-2/brief.md`
- Memory: `project_uom_drift_gate.md`, `project_bom_staleness.md`,
  `project_ingest_order_invariance.md`,
  `project_bom_immutable_principle.md`.
- Migrations: 053, 054, 055, 056, 057, 058.
- Test harness: `tests/test_ingest_order_invariance.py`.
