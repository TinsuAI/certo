# CO → DH request: classify Johnson BOM-only codes (material_group gap)

**Date:** 2026-06-09 · **From:** CO (`barry-CO-main`) · **To:** Data Hub (mig 078 owner)
**Related:** `data-hub/.ai/sister-app-notes/2026-06-09-co-consumer-spec-declarability.md`
(the spec CO just implemented), `.ai/sessions/2026-06-09-*` (CO side).

## Context

CO adopted the rich `customs_relevance` path and **removed its Johnson-derived
heuristic** (it over-fit: it would have dropped 94% of growatt — growatt is 100%
`null`). CO now trusts DH's per-material classification and KEEPS anything DH
leaves `null`/`review` (never silently drops).

**Consequence:** DH's classification for Johnson is **incomplete**. On product
`MFW0509-39`, 25 of the 26 real non-declarable / unmatched rows come back as
`customs_relevance=null` because their `material_group` is null — these codes only
appear in the technical BOM source, so the SAP Material Group ingestion never tagged
them. Result: those rows **reappear in the Johnson bảng kê export** until DH maps
them. Operators can still bulk-delete them by hand ("Chọn dòng không có tồn/BCCT"),
but the right fix is DH-side classification.

## Ask

Assign `material_group` (→ `item_category` / `customs_relevance`) for the 25 codes
below so they classify correctly. Two groups:

**A) True rác → should become `excluded_non_material`** (drawings RD07, documents
RD08, labels RD12):

| code | name | nature |
|---|---|---|
| 1000439883 | Rendering;Semi-Assy;FW334 | drawing |
| 1000439884 | Blueprint;Semi-Assy;FW334 | drawing |
| 1000439885 | Ergonomics dimension drawing;Semi-Assy | drawing |
| 1000439886 | Fabricate Drawing;Semi-Assy;FW334 | drawing |
| 1000439887 | Container Diagram;Semi-Assy;FW334 | drawing |
| 1000478896 | Explosive Diagram;Semi-Assy;FW511 | drawing |
| 1000478558 | Checklist;;A;FW511 | document |
| 1000478559 | Checklist;;B;FW511 | document |
| 1000478533 | EN LABEL;FW511 | label |
| 1000478560 | Bar Code Label;FW511 | label |
| 1000478561 | Serial No Sticker;FW511 | label |
| 1000503975 | LABEL;Seat and Back Pad | label |

**B) Real physical materials → need a `material_group` so they classify as
`declarable` / `declarable_unmatched`** (NOT rác — they belong on the bảng kê once
matched to a BCCT import; today they're unmatched):

| code | name | suggested group |
|---|---|---|
| 1000468701 | Round Steel;Round;20#;φ12 | RD21 metal |
| 1000468706 | Round Steel;Round;20CrMo;φ26 | RD21 metal |
| 1000478157 | Round Steel;Round;Φ35.6;AL6061 | RD21 metal |
| 1000478158 | Round Steel;Round;Φ35.6xΦ26.2;AL6061 | RD21 metal |
| 1000478517 | Tube;Round;45#;φ75.6x□40.5x40.5x2200 | RD21 metal |
| 1000478527 | Round Steel;Square;20#;□40x40x2000 | RD21 metal |
| 1000490901 | Tube;Round;STK41;Φ78x4.0Tx5800 | RD21 metal |
| 1000095594 | Cap;Leg Pad;ABS;Deep Grey;GM42 | RD09 plastic |
| 1000111365 | 3MGlue;4475;liquid glue | RD09 plastic/adhesive |
| 1000463364 | Membrance;PVC;With adhesive | RD09 plastic |
| 1000544472 | Leg Pad;PU,Vesicant;Obsidian Black;GM42 | RD09 plastic |

**C) Ambiguous — DH to decide:**

| code | name | note |
|---|---|---|
| 1000439901 | Screw set;Semi-Assy;FW334 | phantom/assembly set? → review or excluded |
| 1000479690 | Cardboard;360X250;Blister use;FW511 | packaging → spec says packaging is KEPT (declarable) |

## Notes

- The split (A vs B) matters: do NOT blanket-exclude group B — that would
  **under-declare** real non-originating materials and inflate LVC. They should
  surface in CO's `declarable_unmatched` review queue (real material, no import
  match yet), not as rác.
- This is `MFW0509-39` only; `MFW0502-571` (and other Johnson products) have the
  same `Semi-Assy`/drawing/checklist pattern — fixing the `material_group` map for
  these codes should cover them client-wide.
- No CO code change needed once DH classifies: CO already reads `customs_relevance`.
