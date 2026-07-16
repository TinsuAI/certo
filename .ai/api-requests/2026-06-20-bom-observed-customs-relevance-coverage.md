# Data Hub API Request: `customs_relevance` coverage for the `bom_observed` group (DC1)

**Date:** 2026-06-20 · **From:** CO (`barry-CO-main`) · **To:** Data Hub (mig 078 / Material Group ingest owner)
**Supersedes / generalizes:** `2026-06-09-johnson-bom-material-group-gap.md` (a hand-list of 25
Johnson codes). This request reframes that gap as a **systemic coverage ask** — do **not**
hand-map individual codes; re-ingest Material Group for the whole group.
**Related:** `.ai/sister-app-notes/2026-06-09-co-consumer-spec-declarability.md` (the spec CO
implemented), backlog DC1/DC3.

## Use Case
CO trusts DH's per-material `customs_relevance` to decide what appears on the bảng kê C/O export
and what is auto-excluded as rác (drawings / documents / labels). CO keeps **no** local heuristic:
a material DH leaves `null` / `review` / field-absent is **KEPT** (`app/origin_material_filters.py:11-16`).
That conservative default is correct, but it means **DH classification completeness is the only
lever** for the auto-clean feature. Where DH coverage is incomplete, rác stays on the sheet and the
operator must delete it by hand.

## Existing Endpoint Gap
- No endpoint to change — CO already reads `customs_relevance` off the BOM/material rows it receives
  (`is_bom_technical_noise` / `is_declarable_unmatched`, `app/origin_material_filters.py:11-22`;
  excluded at export in `app/bang_ke_renderer.py:259`, `app/workbook_io.py:617`,
  `app/bang_ke_xml_generator.py:391`).
- The gap is **data completeness**, not contract. The adapter ingest
  (`sap_indented_walk.py`, per the DH leaf-declarability brief) kept level/qty/unit/description but
  **dropped the SAP `Material Group` column + `Phantom`/`Bulk` flags**. `customs_relevance` is derived
  from Material Group, so every material that exists **only in the technical BOM source** (DH group
  `bom_observed`) comes back `customs_relevance=null`.
- mig 078 re-ingested Material Group but **did not cover the `bom_observed`-only set** for Johnson.
  Symptom: on `MFW0509-39`, 25 of 26 real non-declarable/unmatched rows are `null` → they reappear
  on every Johnson bảng kê export. growatt is 100% `null` for this group too — which is exactly why
  CO removed its Johnson-fitted heuristic (it would have dropped 94% of growatt).

## Proposed Contract
This is a **backfill + coverage-visibility** request, not a new mutation endpoint.

1. **Backfill (primary ask):** Re-run Material Group ingest so the `bom_observed` group is decoded
   for **all** CO-eligible clients (Johnson + Growatt + any client CO files C/O for), assigning each
   material a `customs_relevance` from its decoded Material Group:
   - `excluded_non_material` — RD07 drawings, RD08 documents, RD12 labels (true rác)
   - `declarable` / `declarable_unmatched` — real physical materials (metal RD21, plastic/adhesive
     RD09, packaging) that belong on the bảng kê once matched to a BCCT import
   - `review` — genuinely ambiguous (phantom/assembly sets); CO keeps these visible, never auto-drops
2. **Coverage visibility (so CO and you can both see the gap close):** add a per-client classification
   coverage block to the existing `GET /v1/hub/dncxs/{client_id}/source-summary` response
   (`app/data_hub_client.py:447`, consumed via `DataHubClient.source_summary`):

   ```json
   "customs_relevance_coverage": {
     "total_materials": 1207,
     "classified": 1180,
     "null_or_review": 27,
     "coverage_pct": 97.8,
     "by_group": {
       "bom_observed": { "total": 1207, "classified": 1180, "null": 27 },
       "bcct_matched":  { "total": 842,  "classified": 842,  "null": 0 }
     }
   }
   ```

Query parameters: none new.
Request body: none.
Response body: as above — additive field on `source-summary`; all existing fields unchanged.
Error cases: unchanged (`401`/`403`/`404` per existing `source-summary`).

## Auth
Required scope: `hub:read` (same as existing `source-summary`).
Client scoping rule: unchanged — token's `client_ids` whitelist / JWT claim must allow `client_id`.
Token type: user JWT or service token (unchanged). **No mutation scope needed** — backfill is a
DH-side data job, not a CO-driven write.

## Data Semantics
Source of truth: DH `hub.client_material_group_map` (SAP Material Group → `item_category` →
`customs_relevance`). CO never owns this — CO has no access to SAP Material Group.
Precision requirements: classification is categorical; CO needs the enum value only.
Pagination: n/a (coverage is a scalar block on `source-summary`).
Idempotency: backfill must be idempotent — re-running ingest must not flip an already-correct
classification. Coverage read is pure.
Versioning or pinning: none. CO reads whatever the latest classification is at render time.

Decision for DH to confirm: is the split **A=excluded / B=declarable / C=review** (from the
2026-06-09 note) the right policy for `bom_observed`? Critically — do **not** blanket-exclude the
whole group: that would drop real non-originating materials and **inflate LVC** (under-declare).
Group B must land as `declarable`/`declarable_unmatched`, not `excluded_non_material`.

## Tests Required In Data Hub
Provider tests:
- After backfill, `MFW0509-39` returns the 25 codes with the A/B/C classes from the 2026-06-09 note
  (drawings/docs/labels → `excluded_non_material`; steel/plastic/packaging → `declarable*`).
- `source-summary.customs_relevance_coverage.coverage_pct` reflects the post-backfill state and
  `by_group.bom_observed.null` drops toward 0.
- Idempotency: re-running ingest leaves an already-classified material unchanged.
Negative tests:
- A real material is **never** auto-classed `excluded_non_material` from a missing/ambiguous group
  (no false-rác → no LVC inflation).
Edge cases:
- growatt (100% `null` today) gets classified without over-fitting Johnson's pattern.
- `Cardboard;Blister use` (packaging) classifies `declarable`, not rác (packaging is KEPT).

## CO Consumer Plan
Adapter method to add in `app/data_hub_client.py`: none for classification (already consumed).
Optional: read `customs_relevance_coverage` off `source_summary` to render a "X% NVL đã phân loại
declarability" health badge on the client/co-stock page so operators see when a client is BOM-clean.
Call sites that will consume: `app/origin_material_filters.py` (unchanged — auto-exclude simply
starts working as coverage rises); optional badge in client/co-stock template.
Consumer tests: none required for the backfill (CO behavior already correct); add a render test if
the coverage badge is built.

## Approval
Data Hub contract owner:
Approval date:
Data Hub commit:
