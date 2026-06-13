# Sister-app note: SAP Material Group + non-declarable BOM-row exclusion (mig 078)

**Date:** 2026-06-09 · **Affects:** CO (primary), BCQT (additive only)
**Migration:** 078 · **Investigation:** `.ai/features/2026-06-08-leaf-nvl-declarability/brief.md`

## What changed

Data Hub now re-ingests the SAP **`Material Group`** (RD07 drawing, RD08
document, RD12 label, RD06 packaging, RD21 steel, RD02 fastener, RD09 plastic,
CO01 welding rod, …) plus `Phantom`/`Bulk` flags, which were previously parsed
then discarded. From these it derives, per material, an **`item_category`**
(physical nature) and a **`customs_relevance`** (single declarability axis), and
it can **soft-exclude non-declarable ("rác") rows** from the flattened BOM so
they don't become bảng kê candidate lines.

"Rác" for johnson-vn = drawings (RD07) + documents (RD08) + labels (RD12) +
phantom-set rows. Packaging and physical materials are kept. The
(material_group → item_category, is_declarable) map is per-client and
DB-configurable: `hub.client_material_group_map`.

## New fields

### `GET /v1/hub/materials` (and per-material) — additive, always present
- `material_group` — raw SAP code (e.g. `RD21`), or null if the code never
  appeared in a technical-BOM source.
- `item_category` — derived nature: `drawing|document|label|packaging|metal|
  hardware|plastic|consumable|assembly_set|finished|other`, or null.
- `customs_relevance` — one of:
  - `excluded_non_material` — drawing/document/label (rác); **exclude from bảng kê**.
  - `declarable` — physical material with a matching BCCT import; declare normally.
  - `declarable_unmatched` — physical material with **no** BCCT import match
    (e.g. welding-rod variant, bulk-decomposed steel cut-piece). **Do NOT
    silently drop** — it belongs on the bảng kê; flag for catalog↔customs
    reconciliation.
  - `review` — has a Material Group but no client map row (a gap; never
    silently treated as rác).
  - `null` — no Material Group (e.g. a code seen only in BCCT, never in a BOM).

### BOM rows — new opt-in filter
- **`POST /v1/hub/products/bom/artifacts:batch`**: body accepts
  `exclude_non_declarable: bool` (default **false**). When true, rows
  soft-excluded as rác are dropped from every artifact's `rows`. The choice is
  echoed in each envelope's `filter_applied.exclude_non_declarable` so the
  caller can detect server support and avoid double-filtering.
- **`GET /v1/hub/products/{product_code}/bom/artifacts/{artifact_id}`**: same
  via query param `?exclude_non_declarable=true`.
- Per-row payload now also carries `material_group`, `phantom`, `bulk`.

## Impact / migration

- **CO** (primary consumer): no code change needed to keep working — the new
  material fields are additive (tolerated by `normalize_material_row`), and the
  filter is **off by default**. To use it, pass `exclude_non_declarable: true`
  on the batch call. Recommended: also surface `customs_relevance ==
  'declarable_unmatched'` for operator review rather than auto-declaring.
- **BCQT**: consumes `/v1/hub/products/{p}/bom`, `/bom/artifacts`, and
  `/materials`. **No behavior change**: the exclusion filter is not wired into
  those endpoints, and the new `/materials` fields are additive. BCQT settlement
  norms are unaffected.
- The filter is **not** on `/v1/hub/products/{p}/bom` (pinned single read) or
  `/bom/artifacts` (list) — only batch + single-by-id. Add later if a consumer
  needs it.

## Rollout

The filter is default-off everywhere. Recommended sequence: deploy → verify CO
against `exclude_non_declarable: true` output for johnson-vn → then have CO flip
it on. Deploy-free rollback: stop passing the flag. Per-client behavior is
governed entirely by what's seeded in `hub.client_material_group_map`.
