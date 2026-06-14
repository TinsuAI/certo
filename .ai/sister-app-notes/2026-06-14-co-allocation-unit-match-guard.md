# CO note — guard stock allocation against UoM mismatch (P4 of UoM review)

**Date:** 2026-06-14. From the system-wide UoM conversion review (Data Hub +
CO). This is the **only** CO-side action item; CO otherwise does no UoM math
and has no factor-direction bug (it consumes Data Hub's already-converted BOM
quantities at 1:1).

## The dependency (latent, not a bug today)

CO's BOM-consumption + stock allocation:

- `app/web/co_case_context.py::origin_material_from_bom_row` —
  `consumed_qty = export_quantity * qty_per`, where `qty_per` is Data Hub's
  **already-converted** BOM per-unit quantity in `row["uom"]` (the catalog
  canonical UoM).
- `allocate_material_stock(material_code, consumed_qty, stock_candidates, …)`
  then subtracts `consumed_qty` from each stock candidate's `available_qty`.
  Stock comes from **BCCT declared** `quantity` / `unit`.

The subtraction assumes `stock.unit == row["uom"]` for the same material code.
It is **never checked**. If Data Hub ever serves a BOM row whose canonical
`uom` differs from the BCCT-declared stock unit for that code (a Data Hub
UoM-drift escape), CO subtracts across incompatible units and mis-allocates —
surfaced only as a (wrong) shortage, never flagged as a unit problem.

Currently benign: Data Hub's ingest UoM-drift gate + the BOM flatten
conversion keep `uom` aligned to the declared unit in practice. This is a
dependency to make explicit, not a live corruption.

## Recommended CO-side guard (apply on a clean branch)

⚠️ Do **not** apply inline right now — `app/web/co_case_context.py` is mid
redesign on `feat/rd3-bangke-split` (co-flow-redesign-step1-2). Apply this
when that lands, on its own small branch.

In `allocate_material_stock` (or at the `consumed_qty`/allocation-context build
in `origin_material_from_bom_row`), compare the BOM-demand unit
(`allocation_context["material_uom"]` = `row["uom"]`) against each stock
candidate's unit. When they differ and are not alias-equivalent
(PCS/ST/EA → same canonical), **do not silently subtract**: attach a
`unit_mismatch` flag/warning to the allocation result so the operator sees
"demand in X, stock in Y" instead of a misleading shortage. CO's own principle
is **warn, do not convert** (see
`barry-CO-main/.ai/audits/2026-06-07-trului-not-a-logic-variable-audit.md`),
so a warning — not an auto-conversion — is the correct shape. The actual
conversion stays Data Hub's responsibility.

## Data Hub side (already covered by this review)

- Factor convention documented + clarified (UI hint, import template) — P1.
- Flatten override lookup made symmetric so panel/drift "convertible" verdict
  matches flatten — P2.
- Materialize WALK now warns on multi-canonical leaves before the
  sum()+max(uom) collapse — P3.

Full review: see the 2026-06-14 UoM review session / this branch
`fix/uom-factor-direction`.
