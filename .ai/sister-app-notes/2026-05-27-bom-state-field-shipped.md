# Notes for CO + BCQT — BOM `state` field shipped

**Provider:** Data Hub · **Consumers:** CO, BCQT · **Date:** 2026-05-27

Posted from Data Hub side. **Optional but recommended** read for any code that renders BOM artifact status badges or warns users about stale/drift data.

## What changed in Data Hub

`hub.bom_artifacts` gains a new generated column `state` (mig 068) — a
4-state summary derived from the existing `is_stale` + `has_uom_drift`
flags + their reasons JSONB. The column auto-maintains via Postgres
GENERATED ALWAYS AS, so no trigger drift.

### Why

Audit 2026-05-27 found the UI was unusable at scale: Johnson dev DB
showed 1,336 "stale or drifting" rows under 8 dims × 3 categories.
99% were not actionable (`/bom/stale` listed every catalog edit
side-effect as a separate row, with no bulk action and no
human-readable cause label). Conditional triggers (mig 069+071) +
auto-reconcile on edits (A5) + state column condense this to ~20
actionable rows clustered by root cause on the new
`/clients/{cid}/bom/needs-action` page.

### Values

- `clean` — BOM aligned with current catalog. Most artifacts.
- `needs_refresh` — auto-fixable: catalog dependency moved, Refresh
  re-derives. UI binds a single "Refresh" button per artifact or
  cluster.
- `needs_input` — staff decision required: factor missing,
  catalog uom missing, unconfirmed 1:1 default, raw_graph drift
  (no auto-fix path because edges are immutable).
- `broken` — reserved (not yet emitted). Will be used for unrecoverable
  state like missing raw ancestor.

### Mig changes (067–071)

- **067** — clear `is_stale` + `has_uom_drift` when artifact is
  tombstoned. Cleans up 2,719 dead Johnson rows on apply.
- **068** — adds the `state` generated column + partial index
  `(client_id, state) WHERE state <> 'clean'`.
- **069** — `hub.is_uom_aligned(a, b)` helper + conditional D7/D9
  triggers: skip the flag when new catalog uom alias-aligns with the
  BOM row's uom.
- **070** — backfill: clear flag on alias-aligned existing rows.
- **071** — `hub.has_drift_remaining(client_id, code, bom_uom)` helper
  + trigger refactor that ALSO consults `hub.client_uom_overrides`.
  Cleared the residual 919 Johnson raw_graph false-positives where
  override resolves cross-family pairs (EA→CAY etc.).

## API contract — additive

### `GET /v1/hub/products/{p}/bom?artifact_id=…`
### `GET /v1/hub/products/{p}/bom/artifacts`

Response `artifact` dict (or each item in `items`) now includes:

```json
{
  ...existing fields,
  "is_stale": true,
  "stale_reasons": [...],
  "has_uom_drift": false,
  "uom_drift_reasons": [],
  "state": "needs_refresh"
}
```

`is_stale` + `has_uom_drift` + reasons are **retained** for backward
compatibility — sister apps can ignore the new field if they want. No
breaking change.

### Recommended migration for consumer UIs

Replace any custom logic that derives a UI state from
`(is_stale, has_uom_drift, reasons)` with a single switch on `state`:

```python
state_to_badge = {
    "clean":         ("OK",         "success"),
    "needs_refresh": ("Cập nhật",   "info"),
    "needs_input":   ("Cần xác nhận","warning"),
    "broken":        ("Lỗi",        "danger"),
}
```

Vietnamese labels live in Data Hub's `app/i18n.py` under the
`bom.state.*` keys; sister apps can copy or look up.

### Reasons taxonomy (unchanged but now mapped via state)

| dim | dim category | drives state | UI cause label key |
|---|---|---|---|
| `catalog_category` | dependency | `needs_refresh` | `bom.cause.catalog_category` |
| `materials_uom` | uom | `needs_refresh` (derived) / `needs_input` (raw_graph) | `bom.cause.materials_uom` |
| `btp_sourcing` | dependency | `needs_refresh` | `bom.cause.btp_sourcing` |
| `btp_bom_added` | btp_bom | `needs_refresh` | `bom.cause.btp_bom_added` |
| `btp_bom_tombstoned` | btp_bom | `needs_refresh` | `bom.cause.btp_bom_tombstoned` |
| `catalog_inserted` | uom | `needs_refresh` / `needs_input` | `bom.cause.catalog_inserted` |
| `derive_hook_failed` | dependency | `needs_refresh` | `bom.cause.derive_hook_failed` |
| `factor_missing` | uom | `needs_input` (blocking) | `bom.cause.factor_missing` |
| `unconfirmed_default_1to1` | uom | `needs_input` | `bom.cause.unconfirmed_default_1to1` |
| `catalog_uom_missing` | uom | `needs_input` | `bom.cause.catalog_uom_missing` |

`factor_missing` + `catalog_uom_missing` are **blocking** — engine
returned raw qty/uom unchanged. `unconfirmed_default_1to1` is
**informational** — engine applied factor=1.0; data was converted but
no per-material override row confirms the synonym.

## Consumer-side action items (not blocking)

1. **CO/BCQT badge rendering**: switch to `state` for cleaner UX. Old
   `is_stale`-based logic still works, but maps poorly to the 4-state
   model (e.g., manual_flat with uom drift now correctly shows
   `needs_refresh`, not "permanently broken").

2. **No need to call `/bom/needs-action`** from sister apps. It's a
   Data Hub admin/agency page; agencies handle their own catalog
   hygiene there.

3. **Watch for `state="needs_input"` in calculation paths.** Such
   artifacts have applied_uom_factor=NULL on at least one row → qty
   is in raw uom, not catalog uom. Best-practice: refuse to use them
   for settlement output, surface a warning. Most consumers already
   refuse `flatten_status='non_flattened'`; treat `needs_input`
   similarly.

4. **Backward compat window:** unlimited. The legacy
   `is_stale` + `has_uom_drift` fields are not deprecated; no plan to
   remove. Adding `state` is the lightweight, non-breaking upgrade.

## How to verify

Data Hub side:
```bash
psql -d data_hub -c "select state, count(*) from hub.bom_artifacts
                     where client_id='johnson-vn' and tombstoned_at is null
                     group by 1"
```

API side:
```bash
curl -H "Authorization: Bearer $TOKEN" \
  "https://ttdatahub.tinsu.ai/v1/hub/products/<P>/bom?client_id=johnson-vn" \
  | jq '.artifact.state'
```

## Cross-link

- Audit conversation that drove this: see `.ai/sessions/2026-05-27-*` (forthcoming).
- Tests:
  - `tests/test_bom_state_and_conditional_triggers.py` (36 tests)
  - `tests/test_bom_staleness_api_ui.py` extensions
