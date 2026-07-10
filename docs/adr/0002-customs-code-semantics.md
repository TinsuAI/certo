# ADR-0002: What a `customs_code` means — buckets, placeholders, and registration

**Date:** 2026-07-10 · **Status:** Accepted

## Context

`hub.bcct_rows.customs_code` is the code filed on a customs declaration line. Three
questions about it were unresolved and were being answered inconsistently across the
codebase. All three were settled by the domain owner on 2026-07-10, against data.

## Decision

### 1. HQ bucket codes are materials

For clients running two code systems, `customs_code` is frequently a **grouping code**, not
a part number. Growatt: 520 HQ codes cover 2,846 internal (NB) codes; 141 of them fan out to
more than one. `LK-DAY2` groups 158 NB codes, `DAUNOI` 134, `DIENTRO` 131.

These stay in `hub.materials`. They are legitimate materials at declaration granularity.

**Consequence, and the reason this matters:** BCCT observation signals must **never** be
bridged from an HQ code to its NB children through `hub.code_mappings`. Doing so would
attribute `LK-DAY2`'s entire declaration history to each of its 158 children. The
paren-extraction of NB codes from `goods_name` exists precisely to give per-line
attribution, and cannot be replaced by that join.

### 2. `customs_code = '.'` marks a fixed-asset line and must be excluded

Growatt: 3,509 such rows, 100% `direction=import`, `declaration_type=E13`; the goods are BYD
forklifts and storage racks. Johnson: 13 rows.

- `derive_from_bcct` (`app/stores/provenance.py:33`) filters `customs_code <> ''` but not
  `'.'`, and has created one junk material named `.` per client.
- Those lines also yield **218 NB codes, of which 210 appear only on fixed-asset lines** —
  forklift and rack parts. None has reached `hub.materials`. The other 8 also appear on
  production lines and are real materials.
- **`declaration_type` is not the discriminator.** Growatt has 102 `E13` rows carrying real
  codes; Johnson has 4,260. The discriminator is the placeholder string.
- The placeholder set is **per-client configuration**, not a literal in shared code. Different
  enterprises use different conventions.

Machinery codes are **marked, not dropped**: `customs_relevance='excluded_non_material'`,
still visible, excluded from bulk approval by default. The 8 shared codes are not marked.
CO already consumes and trusts `customs_relevance` (`app/origin_material_filters.py:3`), so
this reaches consumers with no API contract change. Growatt has no SAP `material_group` at
all, so this also gives it a declarability signal it currently lacks.

### 3. `hq_registered` is for tracking only

Appearing on a customs declaration is **not** the same as being registered with customs. The
column exists (mig 042) but only 4 of 13,631 rows set it, two of which are demo seeds.
`app/routes/api.py` never emits it; CO has never seen it. Declarability is assessed
separately through `customs_relevance`.

**Do not gate behaviour on `hq_registered`.**

## Consequences

- One placeholder predicate, read by `_is_missing_hq`, `derive_from_bcct`,
  `_bcct_paren_pairs_for_nb`, and `_co_occurring_codes`.
- Machinery marking depends on `hub.bcct_nb_codes` (ADR-0001): deciding that a code appears
  *only* on placeholder lines needs per-row attribution, which for NB codes is not a column.
- The catalog's contents currently depend on how a BCCT file was ingested: 694 distinct
  `customs_code` for Growatt, only 302 became materials, because `derive_from_bcct` runs in
  the route (`app/routes/bcct.py:767`) and part of the data was loaded by
  `scripts/ingest_curated_xlsx_direct.py`, which bypasses it. Unreconciled; separate call.

## References

- Brief: `.ai/features/2026-07-10-catalog-candidates-merge/brief.md`
- Session: `.ai/sessions/2026-07-10-catalog-flow-review.md`
- Related: ADR-0001; `.ai/features/2026-06-08-leaf-nvl-declarability/` (mig 078/079).
