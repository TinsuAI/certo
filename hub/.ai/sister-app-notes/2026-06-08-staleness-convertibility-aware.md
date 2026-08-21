# Staleness flags are convertibility-aware (mig 077) — no action needed

**Date:** 2026-06-08
**Affects:** CO + BCQT — informational; **no code change required**
**Data Hub:** mig 077; brief `.ai/features/2026-06-08-bom-staleness-fingerprint/`;
decision `.ai/DECISIONS.md → 2026-06-08`.

## What changed

The Track D staleness check (`is_stale` / `has_uom_drift` / `state` /
`stale_count`) now flags a BOM-vs-catalog UoM difference **only when the units
are genuinely incompatible** (no conversion factor). Convertible pairs are
accepted silently:

- same canonical (alias, e.g. `PIECES` ≡ `EA`),
- same-family `base_factor` (e.g. `g` ↔ `kg`),
- a client override (`client_uom_overrides`, either direction),
- tier-A 1:1 (count / count_packaging / assembly).

This retires a long-standing false-positive class (the leak mig 069/070/071
chased by hand).

## Effect on you

- **Fewer flagged BOMs.** `stale_count` (source-summary `bom` block) and
  per-artifact `state` show lower numbers. CO's "N mã BOM cũ" note
  (`app/web/client_context.py`) just gets more accurate. Strictly an improvement.
- **No code change required.** Verified Data-Hub-side: CO does not gate
  certificate computation on Data Hub staleness flags, and already reads each
  BOM row's own `uom`.

## Standing-contract reminder (now more pertinent)

A *convertible* catalog UoM edit (e.g. `kg→g`) no longer re-derives
already-published BOM rows — they keep their materialize-time unit. A row may
read `2.5 kg` while the catalog now says `g`; both are physically correct
(`2.5 kg == 2500 g`). **Always read the row's own `uom`; never assume
`row.uom == the catalog's current uom`.** Published BOM rows are
self-describing.
