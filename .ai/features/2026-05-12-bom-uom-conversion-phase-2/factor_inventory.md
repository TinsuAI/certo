# Factor inventory — pre-Phase-2 audit

Walk source XLSX (Johnson 06.05.2026 update) + current Growatt DB state
to inventory cross-family UoM pairs that will need explicit factors in
`hub.client_uom_overrides` BEFORE the reset + bulk re-ingest run.

Generated 2026-05-12 from:
- `/mnt/p/Downloads/Johnson-20260507T123554Z-3-001/Johnson/TECHNICAL BOM - JOHNSON/*.XLSX` (106 files, 27,848 rows, 5,118 codes)
- `/mnt/p/Downloads/Johnson-20260507T123554Z-3-001/Johnson/BaoCaoHangChiTietNK.xls` (60,177 rows)
- `/mnt/p/Downloads/Johnson-20260507T123554Z-3-001/Johnson/BaoCaoHangChiTietXK.xls` (5,673 rows)
- Current `data_hub` Postgres state for Growatt (post-2026-05-11 ingest).

## Johnson — overlap stats

| Set | Codes |
|---|---|
| BCCT codes (NK ∪ XK) | 9,310 |
| BOM codes (component_number across 106 files) | 5,118 |
| Shared (BCCT ∩ BOM) | 1,296 |
| BOM-only | 3,822 |
| BCCT-only | 8,014 |

## Johnson — BOM ↔ BCCT cross-family pairs (THE inventory)

These are the codes where the BOM file declares one UoM family and BCCT
declares another for the same `material_code`. After auto-deriving
catalog UoM from BCCT, these become the codes whose ingest will need
explicit factor rows.

| BOM UoM | BCCT UoM | Family Δ | Codes affected | Action |
|---|---|---|---|---|
| `EA` (count) | `SETS` (assembly) | count → assembly | **176** | Per-code factor: how many EA per SET |
| `EA` (count) | `CAY` (count_packaging) | count → packaging | **41** | Per-code factor: EA per CAY (rod/stick) |
| `EA` (count) | `KILO-GRAMMES` (mass) | count → mass | **2** | Per-code factor: EA per KG (weight per piece) |
| `EA` (count) | `METRIC-TONS` (mass) | count → mass | **1** | Per-code factor: EA per MT |
| **Total cross-family** | | | **220** | |

Same-family auto-convertible (handled by `uom_canonical` precedence,
no manual factor needed): **0 pairs** — Johnson's structured UoMs
already canonicalise cleanly.

## Johnson — BOM intra-file cross-family (Component vs Base)

Within Johnson BOM rows, `Component unit` (per-row) vs `Base Unit of
Measure` (catalog-side from SAP) sometimes disagree:

| Component | Base | Codes | Note |
|---|---|---|---|
| `KG` | `EA` | 55 | Material registered as count, BOM consumed in mass |
| `EA` | `KG` | 1 | Inverse |

These 56 codes are a **second-order signal** — the SAP source itself
already shows drift. Same factors as table above will resolve them
once normalised to one canonical side.

## Johnson — unknown UoM tokens (need `uom_aliases` entries)

| Token | Source | n | Best guess canonical | Action |
|---|---|---|---|---|
| `FT` | BOM only (2 codes Steel Rope, BTP-internal, not in BCCT) | 50 | `ft` (length, 0.3048m) | **System-side**: add canonical + alias |
| `CV` | BOM base only (1 code PE Membrane, BTP-internal, not in BCCT) | 26 | likely carton ~16 kg | **System-side**: mark `has_uom_drift`, optional low-confidence factor |
| `SQUARE METRES` | BCCT NK | 10 | `m2` (already canonical) | Add alias only |
| `Kiện/Hộp/Bao/Gói` | BCCT NK | 16 | multi-meaning Vietnamese token | **System-side**: `client_parser_rules` split per row context (HS code / goods_name heuristic) |
| `Chai/ Lọ/ Tuýp` | BCCT NK | 11 | bottle/jar/tube | **System-side**: same split pattern |
| `Thanh/Mảnh/Miếng` | BCCT NK | 8 | rod/sheet/piece | **System-side** |
| `Viên/Hạt` | BCCT NK | 8 | pellet/grain | **System-side** |
| `SOI` | BCCT NK | 6 | likely "sợi" (thread/strand) | **System-side** |

## Growatt

**Deferred from Phase 2.** User scope decision 2026-05-12: focus
Johnson only. Apply same flow to Growatt after Johnson invariants hold.

## EA↔SETS volume signal (Johnson)

For 180 codes that appear in both Johnson BOM (`Component unit='EA'`)
and BCCT (`Đơn vị tính='SETS'`):

- BOM `Component quantity` (col 10) = "EA per parent assembly" — small
  numbers (1, 2, 4, 7...). Sum across files reflects assembly demand.
- BCCT `Lượng` (col 26) = total SETS imported across all declarations
  — large numbers (100, 1000, 6800...).

The two columns measure **different things** (assembly demand vs
imported volume) and cannot be divided to derive a real conversion
factor. They share only the constraint that conversion is per-code.

**Useful conclusion:** the 180 codes' BOM_total / BCCT_total ratio
spans 0.0005 → 2.0 (4000× spread). No single rule covers them. Each
code needs its own factor row; **per-code lookup is the correct
model**. CSV import path becomes attractive vs 220 form-fill (Phase 2
nice-to-have or Phase 3).

True factor values (EA per SET per code) must come from agency Q&A
or supplier datasheet — not derivable from the data files alone.

## FT — system-side resolution (no agency Q&A)

- 25 row occurrences across 14 BOM files (MPL0108-*, VGM0117-* …
  VGM0123-05). Both `Component unit` AND `Base Unit of Measure`.
- **2 distinct codes**: `1000485239` (Steel Rope Φ4.8 × 2500Ft) +
  `1000491610` (Steel Rope Φ6.35 × 2500Ft).
- **Both codes verified NOT in BCCT** (3-pass scan: exact 'CV'/'FT'
  match, all distinct UoM in col 27, full substring) — BTP-internal
  only. Not in customs declarations → not in settlement output.
- Description carries "2500Ft" → FT = feet (length unit). Very high
  confidence.
- **Action:** add `uom_canonical('ft', 'length', 0.3048)` + alias
  `'FT' → 'ft'`. Same family as `m`/`cm`/`mm` → auto-convertible
  via existing precedence stack. ~10 min mig.

## CV — system-side resolution (no agency Q&A)

- 26 row occurrences across 16 BOM files (MFW0503-*, MFW0514-*,
  MFW0522-*). **`Base Unit of Measure` only**, never component unit.
- **1 distinct code**: `0000096095` (PE Membrane;;;;16公斤/box).
- Component unit on these rows = `KG`. Description says "16 kg/box".
- **Code verified NOT in BCCT** (3-pass full scan including substring
  for 'CV' across all 54 cols + 22 distinct UoM values in col 27 —
  the 11 substring hits are coincidental: "PVC", "Cu/PVC - CV 1x16"
  cable model, "SCVN..." invoice number).
- BTP-internal only → not in customs → not in settlement.
- **Action:** mark this 1 mã with `has_uom_drift` initially. Optional
  populate `client_uom_overrides` with low-confidence factor (1 CV ≈
  16 kg from description) as a hint for staff to confirm later. Does
  not block Phase 2 ship.
- Ingest impact: 0-1 factor row, low priority.

## Effort estimate (Johnson only)

| Activity | Effort |
|---|---|
| Add `uom_canonical` row for FT (1 ft = 0.3048 m, length family) | 0.5h |
| Add `uom_aliases` rows (FT, SQUARE METRES) | 0.5h |
| Build `client_parser_rules` to split multi-meaning Vietnamese tokens (Kiện/Hộp/Bao/Gói, Chai/Lọ/Tuýp, Thanh/Mảnh/Miếng, Viên/Hạt, SOI) using HS code or goods_name heuristic | 0.5 day |
| Send `agency_qa_johnson.xlsx` to Johnson; wait for response | async |
| Manual staff entry of 220 Johnson factors after agency response (via admin UI) | **1 day** |
| **Total prep before bulk re-ingest (excludes agency wait)** | **~1.5 days dev + agency response** |

## Risks surfaced

- **Cross-family count→assembly is dominant (176/220 codes).** EA→SETS
  is the bulk of Johnson factor work. Domain question: is it always
  "BOM tracks individual EA, BCCT bundles into SETS" with a fixed
  per-code conversion (e.g., 1 set = 4 EA for tile assemblies)? Likely
  yes per code, but factor varies code-to-code. Cannot derive from any
  global rule.
- **EA→KG (2 codes) and EA→MT (1 code) need physical weight data.**
  Likely from supplier datasheet or measurement. Not derivable from
  files alone.
- **Multi-meaning Vietnamese BCCT tokens** (`Kiện/Hộp/Bao/Gói`,
  `Chai/Lọ/Tuýp`) require row-level disambiguation — handled
  **system-side** via `client_parser_rules` (split per row context
  using HS code or goods_name heuristic). NOT an agency Q&A item.
- **Phase 2 admin UI ergonomics**: 220 manual factor entries via web
  form would be tedious. Consider CSV import path as nice-to-have
  (BACKLOG already has "bulk import from supplier sheet").
- **"FT" + "CV" client-specific**: if FT is always 1 ft = 0.3048 m
  conversion (length), straightforward. If "CV" is a Johnson-specific
  abbrev, agency needs to clarify.

## Recommendations for Phase 2 step 0 (this audit)

1. **Send `agency_qa_johnson.xlsx`** to Johnson (email draft at
   `agency_email_draft.md`). 220 cross-family + CV + FT in one file.
   Async — does not block Phase 2 dev.
2. **System-side**: build `client_parser_rules` to split multi-meaning
   Vietnamese BCCT tokens (Kiện/Hộp/Bao/Gói, Chai/Lọ/Tuýp,
   Thanh/Mảnh/Miếng, Viên/Hạt, SOI) using HS code / goods_name
   heuristic. Do NOT ask agency.
3. **Build admin UI factor-entry** (Phase 2 step 7) so that when
   agency returns the file, staff can populate 220 rows in one
   concentrated session.
4. **CSV import path** for `client_uom_overrides` — Phase 2 nice-to-have.
   Reads back the agency XLSX directly to avoid re-typing.

## Cross-reference

- BACKLOG entry "BOM UoM conversion engine" — ingest-time scope A.
- BACKLOG entry "Johnson programmatic bulk re-ingest plan" — depends on
  factor table populated.
- Memory: `project_uom_drift_gate.md`, `project_ingest_order_invariance.md`.
- Brief: `.ai/features/2026-05-12-bom-uom-conversion-phase-2/brief.md`.
