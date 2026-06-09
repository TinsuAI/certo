# Discovery: declarability of "only-in-technical-BOM" leaf NVL (johnson-vn)

> ## ⚠ STATUS 2026-06-09 — IMPLEMENTED, **NOT YET REVIEWED** (review before prod / CO adoption)
>
> Built on branch `feat/bom-material-group-declarability` (commits feat/test/docs/perf),
> full suite green (1454 passed), backfill applied to **local dev DB only**. The
> owner is not yet confident — **needs a `/rev` pass before pushing to prod, before
> applying the backfill to demo/prod, and before CO flips `exclude_non_declarable` on.**
>
> Reviewer should specifically scrutinise:
> 1. **Classification correctness** — is RD12 `label` → rác the right call? Is the
>    rác set {RD07,RD08,RD12,phantom} complete + not over-broad? Spot-check the
>    `client_material_group_map` seed against real items.
> 2. **`declarable_unmatched` handling** — confirm these are never silently dropped
>    (steel/welding variants must stay visible for reconciliation). Validate the
>    CO consumer spec's export-exclude-but-flag behavior is actually safe.
> 3. **Inline CASE duplication** — `customs_relevance` is computed inline in
>    `api.py` + `catalog.py` AND in the `v_material_classification` view. Drift risk.
>    Consider a parity test (like `test_has_drift_remaining_parity`) locking
>    inline ⇔ view.
> 4. **Backfill data mutation** — ~8,150 live johnson rows soft-excluded; re-verify
>    counts + that no real material was wrongly excluded before running on demo/prod.
> 5. **Cross-client safety** — verified Growatt = all-null/no-op; re-confirm after review.
> 6. **Coverage gap** — only `sap_indented_walk` emits `material_group`; other
>    adapters → null/no-op (no benefit). Acceptable? Or extend.
>
> Tracked in `.ai/BACKLOG.md` (A.x — declarability review).

**Date:** 2026-06-08 · **Type:** investigation / API-contract scoping (no code shipped)
**Driver:** CO consumes flattened BOM artifacts and turns each row into a
candidate line on the customs origin sheet (bảng kê). ~26/86 rows per product
are *not* declarable materials (no HS, no import declaration, no CIF). CO needs
a reliable Data-Hub signal to separate a **declarable imported material** from a
**technical/process node** that must NOT appear on the bảng kê.

Scope was narrowed by the user to **leaf NVL only** (`category='nvl'`); BTP_SX is
out of scope (self-produced, not imported).

## TL;DR

1. The clean discriminator already in the DB is **`hub.materials.source`**:
   `bcct_observed` (seen on a customs declaration → has HS, declarable) vs
   `bom_observed` (only seen in a BOM → no HS, not on any tờ khai). For
   johnson-vn the target population is **1,207 leaf NVL** that are
   `bom_observed` + no HS + absent from BCCT.
2. **`source='bom_observed'` is NOT safe as an "exclude" signal.** Quantified
   against the SAP source, only **388 / 1,207 (32%)** are genuinely
   non-declarable (drawings/documents/phantom sets). **428 / 1,207 (35%)** are
   *declarable-class physical materials* (steel, fasteners, plastic, consumables)
   that DH simply failed to match to an import — silently dropping them
   **under-declares non-originating content**. The rest are labels (211, borderline)
   and packaging (180).
3. The field that cleanly separates these — SAP **`Material Group`** (RD07
   drawing, RD12 label, RD08 doc, RD21 steel, RD02 fastener, …) plus the
   **Phantom** / **Bulk** flags — **is read by the parser but thrown away at
   ingest**. Re-ingesting it is the cheap root fix.
4. There is **no reliable code→code lookup** that rescues these into declarable
   for Johnson: `code_mappings` is empty (identity mode), and
   `material_substitutes` edges are similarity noise (embeddings were built on
   the *code string*, since `materials.name` = the code).

## Method / evidence

- DB: `data_hub` (local socket). Tables: `hub.materials`, `hub.bcct_rows`,
  `hub.catalog_candidates`, `hub.material_substitutes`, `hub.code_mappings`,
  `hub.bom_artifact_rows`, `hub.v_material_roles`.
- Source ground truth: **106 SAP technical-BOM workbooks** under
  `data/source_inventory/johnson-vn/2026-05-07-updated/Johnson/TECHNICAL BOM - JOHNSON/`.
  Parsed all 106 → 5,118 distinct codes, `Material Group` consistent per code
  (0 conflicts). Cache: `/tmp/johnson_mg.json`.
- Parser audited: `app/parsers/bom_adapters/sap_indented_walk.py`,
  flatten engine `app/flatten/{engine,classify,types}.py`.

## Finding 1 — the discriminator is `materials.source`

johnson-vn materials = 13,132, exactly two provenance sources:

| category | source | n | has HS | in BCCT | meaning |
|---|---|--:|:--:|:--:|---|
| nvl | `bcct_observed` | 8,244 | ✅ | ✅ | declarable imported NVL |
| **nvl** | **`bom_observed`** | **1,207** | ❌ | ❌ | **only-in-technical-BOM ← this report** |
| btp_sx | `bom_observed` | 2,615 | ❌ | ❌ | self-produced semi (out of scope) |
| btp_sx | `bcct_observed` | 416 | ✅ | ✅ | imported semi |
| tp | `bcct_observed` | 650 | ✅ | ✅ | finished product (export) |

`provenance` of the 1,207 is literally `{"seen_in_bom_only": true}`.
**`hq_registered` is NULL for all 13,132 rows** — that column is not populated
for Johnson and must not be used as a signal. The usable signal is `source`.

## Finding 2 — names & info (answers "do they have tên tuổi?")

- **Material master (`hub.materials`) is a bare stub:** `name` = the code itself
  (e.g. `name='1000439883'`), `hs_code` empty, `supplier_hint` /
  `production_source` / `btp_sourcing` empty, `uom='EA'` (default),
  `category='nvl'` (auto-assigned, unreliable).
- **The real descriptive name lives only in `hub.catalog_candidates.sample_text`**
  (1,207/1,207 present, `sources={bom}`, `bom_role='nvl_leaf'`). This is the SAP
  **"Object description"** column captured at ingest, e.g.
  `Tube;Round;45#;φ75.6x□40.5x40.5x2200;;精抽`.
- **The published flattened rows carry no name:** `hub.bom_artifact_rows.payload`
  is `{}` for every one of these. So if CO is displaying these names, it is not
  getting them from the flattened-row payload — worth confirming on the CO side.
- The SAP source carries **far more** than DH kept. The adapter reads only
  level / component-number / qty / unit / **description** and discards
  **Material Group, Phantom item, Bulk Material, Component-vs-Base unit, Vendor,
  ECO/Change number**. (`provenance ILIKE '%material_group%'` → 0 rows.)

## Finding 3 — the dropped SAP signals (the root cause)

`sap_indented_walk.py` does leaf-detection **purely structurally** (a row is a
leaf iff no deeper-level row follows it) and tags every emitted leaf
`explicit_context='do_not_explode'`. Consequences:

- Phantom "Semi-Assy"/"Set" nodes with no children in that workbook become
  "leaves".
- All item-type information is lost → everything collapses to `category='nvl'`.

The discarded **`Material Group`** is a deterministic SAP item-type key. Decoded
from the data (per-group BCCT-match rate over all 2,087 leaf codes — the
empirical anchor):

| MG | n leaves | % in BCCT | nature |
|---|--:|--:|---|
| RD07 | 288 | **0%** | drawings (Rendering/Blueprint/Diagram/Ergonomics) |
| RD08 | 105 | **7%** | documents (Checklist/Manual) |
| RD12 | 352 | 40% | labels (EN/Warning/Barcode/Serial) |
| RD06 | 380 | 52% | packaging (Carton/Cardboard/Pallet) |
| RD02 | 287 | 63% | fasteners (Screw/Washer/Nut) |
| RD21 | 264 | **20%** | metal raw (Round Steel/Tube/Iron plate) — bulk-decomposed |
| RD09/RD10/RD04 | 260 | 77–88% | plastic/rubber/foam parts |
| RD28/RD22/RD11/RD24 | ~45 | 73–100% | bearings/bushings/springs/cables |
| CO01/CO03/CO04 | ~17 | 33–81% | consumables (welding rod/PE/paint) |

The 0%/7% groups are never imported (correctly excluded). The 60–100% groups
are clearly importable physical materials (the unmatched minority = coverage
gaps). RD21 at 20% is the special bulk-decomposition case (see Finding 5).

## Finding 4 — the 1,207 quantified by item-type (key result)

Each of the 1,207 codes mapped back to its SAP `Material Group` (1,207/1,207
found in source; 0 missing), rolled into semantic buckets:

| bucket (Material Group) | n | % | classification |
|---|--:|--:|---|
| drawing (RD07) | 287 | 24% | **SAFE-EXCLUDE** |
| document (RD08) | 97 | 8% | **SAFE-EXCLUDE** |
| phantom_set | 4 | — | **SAFE-EXCLUDE** |
| label (RD12) | 211 | 17% | **BORDERLINE** (40% of RD12 *do* match BCCT) |
| packaging (RD06) | 180 | 15% | **PACKAGING** (per-client policy) |
| metal cut/bulk (RD21/RD24) | 213 | 18% | **DECLARABLE-CLASS** |
| physical hardware (RD02/16/27/28/22/11…) | 157 | 13% | **DECLARABLE-CLASS** |
| physical plastic (RD09/10/04) | 51 | 4% | **DECLARABLE-CLASS** |
| consumable + other (CO*/magnet) | 7 | — | **DECLARABLE-CLASS** |

**Safe-exclude = 388 (32%). Declarable-class-but-unmatched = 428 (35%).**
Labels 211 + packaging 180 are policy calls. This is why a boolean
`is_declarable=false` keyed on `source`/`hs_code`/`has_imports` is wrong: it
drops the 428.

## Finding 5 — the declarable-class subset has two distinct "gap" natures

Both mean "do not silently exclude":

1. **Variant / period coverage gap (identity holds).** Welding rod
   `K60000905` (0.9 mm) is `bom_observed`/unmatched, but **9 of 10**
   `K600009xx` siblings are in BCCT under the *same SAP code* —
   `K60000900` ("Dây hàn ER70S-6", HS 83113091, unit CAY) is a real import line.
   The 0.9 mm variant is genuinely importable; it just has no matched
   declaration in the loaded BCCT window. Excluding it = wrong.

2. **Bulk decomposition / internal cut-piece.** All **25** `Round Steel;Round;20#;…`
   codes are `bom_observed`/unmatched, each a different cut dimension
   (Φ20×105L, φ18, φ50…), **Component unit = KG**, **Bulk = X**. The physical
   steel is imported as **bulk bar by weight under a consolidated customs code**
   (Vietnamese description, unit CAY/PIECES); the per-dimension SAP codes never
   cross the border individually. The cut-piece code is not directly declarable,
   but the imported steel content still belongs on the bảng kê aggregated under
   the bulk parent → needs cut-piece→bulk mapping.

Matching either nature requires **cross-language, cross-granularity**
reconciliation (English SAP per-dim code ↔ Vietnamese consolidated customs line)
which DH cannot do automatically today.

## Finding 6 — can a BOM code be looked up to other codes? (answers Q2)

Three mechanisms exist; **none rescues declarability for Johnson**:

- **`hub.code_mappings`** (authoritative internal↔customs map) — **0 rows for
  johnson-vn** (identity mode: `substitute_rules.p2_same_customs_diff_internal=false`).
- **`hub.material_substitutes`** (trigram/embedding/same_hs/client_confirmed) —
  956/1,207 have an edge to a `bcct_observed` code, but the high-confidence
  (embedding ≥0.9) edges point to *other `bom_observed`* codes, and the
  declarable-target edges are low-score trigram (numerically adjacent SAP codes).
  Root issue: embeddings were built on `materials.name`, which **is the code
  string** for these stubs → similarity reflects digits, not meaning. Not an
  identity bridge; trusting it would create false declarations.
- **`bcct_material_identity` resolver** — resolves a BCCT line → catalog material
  (reverse direction); does not help a `bom_observed` code with no BCCT line.

## Finding 7 — what CO can see today, and why it's insufficient

The materials read API (`/v1/hub/materials`) exposes `category`, `hs_code`,
`status`, `uom`, and `v_material_roles` signals incl. **`has_imports`**
(`bool_or(direction='import')` on `bcct_rows.customs_code`). It does **not**
expose `source`.

For all 1,207: `has_imports=false` and `hs_code=''`. Both correctly flag
"no import match" but **conflate the 388 safe-exclude with the 428 declarable
unmatched** — exactly the distinction CO needs. So today CO has no field that
separates a drawing from an unmatched steel bar.

## Recommendation

**R1 — Root fix (cheap, highest leverage): re-ingest SAP `Material Group`
(+ Phantom, Bulk, Component unit).** The adapter already parses these columns;
persist them to `bom_artifact_rows.payload` and `materials.provenance`. This is
a deterministic item-type key — no ML, no guessing — and it is the only clean
way to split SAFE-EXCLUDE from DECLARABLE-CLASS at the source.

**R2 — Contract for CO: a typed enum, NOT a boolean.** Derive
`customs_relevance` from `item_category` (← Material Group) × BCCT match:

| value | derivation | CO behavior |
|---|---|---|
| `non_material` | MG ∈ {RD07, RD08, phantom-set} | exclude from bảng kê |
| `packaging` | MG = RD06 | exclude by default; per-client toggle |
| `label` | MG = RD12 | borderline; default exclude, surface for review |
| `declarable` | physical material **and** BCCT-matched | declare normally |
| `declarable_unmatched` | physical material **and** not matched | **surface for review — never auto-drop** |

Also expose raw `source` + `material_group` so operators can audit. CO files
this as an `.ai/api-requests/` contract artifact against DH.

**R3 — Phase 2: a reconciliation surface for `declarable_unmatched`** —
cross-language name/HS matching + cut-piece→bulk-parent mapping. Do **not** route
this through `material_substitutes`.

**Interim (before R1 ships):** CO must treat `source='bom_observed'` /
`has_imports=false` as **"needs review", not "exclude"**, because it mixes
drawings (excludable) with unmatched steel/welding rod (must be declared).

## Appendix A — the 6 example codes

| code | sample_text | Material Group | bucket | declare on bảng kê? |
|---|---|---|---|---|
| 1000439883 | Rendering;Semi-Assy;…;FW334 | RD07 | drawing | No |
| 1000478558 | Checklist;;A;;;FW511 | RD08 | document | No |
| 1000478533 | EN LABEL;;FW511 | RD12 | label | Borderline |
| 1000478560 | Bar Code Label;…;FW511 | RD12 | label | Borderline |
| 1000478517 | Tube;Round;45#;φ75.6x…;精抽 | RD21 | metal (bulk) | **Yes — needs reconciliation** |
| K60000905 | welding rod;;0.9 | CO01 | consumable | **Yes — variant gap; sibling K60000900 imported** |

## Appendix B — key queries / artifacts

- Per-MG coverage + 1,207 rollup: parse `TECHNICAL BOM - JOHNSON/*.XLSX` →
  `/tmp/johnson_mg.json`, join `hub.materials`/`hub.bcct_rows`.
- Population cross-tab: `hub.materials` group by `source`/`category`/has-HS/in-BCCT.
- Welding-rod family: `material_code LIKE 'K60000%'` vs `bcct_rows.customs_code`.
- Round-steel family: `catalog_candidates.sample_text ILIKE 'Round Steel;Round;20#%'`.
</content>
</invoke>
