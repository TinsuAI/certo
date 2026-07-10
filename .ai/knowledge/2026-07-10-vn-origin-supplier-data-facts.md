# VN-origin materials: what the data actually says

Verified 2026-07-10 against the local `data_hub` Postgres (`psql -d data_hub`, peer auth).
Companion to `2026-07-10-co-origin-cumulation-and-vn-origin-rules.md`, which covers the
legal side. This file records the **data** side, and kills three plausible theories that a
design would otherwise have been built on.

## The finding

Johnson is a DNCX. It buys raw materials from domestic Vietnamese suppliers via **on-spot
import** (nhập khẩu tại chỗ), so those purchases are already in `hub.bcct_rows` as ordinary
rows:

| field | value |
|---|---|
| `direction` | `import` |
| `declaration_type` | `E15` (4,870 rows) or `E13` (1,373) — both "từ nội địa"; 29 stray `E11` |
| `origin` | `VIETNAM` |
| `consignee_name` | the domestic supplier ("Tên đối tác") |

Totals: **6,272 rows / 1,252 distinct `customs_code` / 64 suppliers** for `johnson-vn`.
Growatt has 1,740 equivalent rows. (Beware: 1,019 is the E15-only material count, not the
total — an easy mis-read of the per-declaration-type breakdown.)

Of those 1,252 materials, **1,039 have VN lots only, and 213 have BOTH VN and non-VN lots.**
See "Origin is a property of the lot" below — this is the single most constraining fact.

`origin` is populated on **100% of all 65,846 Johnson rows**. It already reaches CO —
`app/data_hub_client.py:1164` maps it to `origin_country` — and is rendered in the bảng kê
"Xuất xứ" column (`app/bang_ke_renderer.py:287`). It has never influenced `origin_status`.

**The defect:** those 1,252 materials are currently counted as `non_origin` and summed into
VNM, so RVC is understated.

Worse, the bảng kê's "Xuất xứ" column is **blank for every row today**: the sheet's material
dict (`app/web/co_case_context.py:2415-2435`) never sets `origin_country`, so
`app/bang_ke_renderer.py:287` renders an empty string. The lot carries it
(`co_stock_derivation.py:65`); the material row drops it.

## Origin is a property of the lot, not the material

**213 material codes have both VN and non-VN lots.** A bảng kê row aggregates lots across
declarations (`allocation_import_lines`, `aggregate_co_stock_rows`), so one row's consumed
quantity can be drawn from a VN lot and a Chinese lot at once. Origin therefore cannot be
resolved at material grain and stamped on the row: it must be resolved **per lot** and the
row's value apportioned across the origin/non-origin columns — or the row split.

This is what makes "resolve to an originating *amount*, not a boolean" load-bearing rather
than merely future-proofing: it is required on day one, for VN origin, before cumulation
ever enters the picture.

## Three theories this disproves

1. **"Domestic purchases arrive as `Hướng = Nhà cung cấp` rows."** No. There are **zero**
   rows with `direction IS NULL` in the entire database, for any client. The branch at
   `data-hub/app/parsers/bcct.py:386-391` (and its test at `tests/test_parsers.py:245`) is
   a defensive guard against a cell value that real workbooks do not contain. No new
   `direction` vocabulary is needed.
2. **"Domestic materials sit in the `declarable_unmatched` review queue, silently dropped
   from the bảng kê."** No. They carry a `declaration_no` and `direction='import'`, so they
   pass every CO guard (`app/source_store.py:648-651`) and are already on the sheet — just
   in the wrong column.
3. **"CO needs a Data Hub API request to see supplier identity."** No. `/v1/hub/bcct`
   already selects `consignee_name` (`data-hub/app/routes/api.py:605`), and CO already
   reads it on the export side (`app/data_hub_client.py:1211`). The only break is that
   `co_stock_derivation.py:65` keeps `origin_country` but drops `consignee_name` when a
   BCCT row becomes a stock lot. That is a one-field CO-side fix.

## Two constraints any design must absorb

**`origin` is free text, not ISO.** Observed values across Johnson + Growatt: `VIETNAM`,
`CHINA`, `U.S.A.`, `UNKNOWN` (1,060 Johnson rows), `TAIWAN`, `GERMANY`, `JAPAN`,
`SWITZLD`, `HG.KONG`, `THAILND`, `U KING`, `INDNSIA`, `KHONG XAC DINH`. A normalization
map is mandatory. `UNKNOWN` must stay `non_origin`.

**There is no counterparty tax code.** Not a column, not in `payload` (whose only keys are
`STT`, `Ghi chú`, and tax-rate leftovers). `exporter_tax_code` is the *declarant* — constant
`2301309437` on all 6,272 rows. So the supplier key is the free-text `consignee_name`, and
name normalization is the only available identity.

Normalizing whitespace alone (collapse runs, insert a space before `(`) collapses **136 raw
names → 132 suppliers** and moves 2 suppliers out of the "VN-only" bucket:
`MYS GROUP (VIET NAM)` vs `MYS GROUP(VIET NAM)` are one company; `TNHH␣␣NIPPON` only looked
VN-only because it had split off from `TNHH␣NIPPON`, which carries 5 CHINA rows. Branches
(`... MESSER HAI PHONG - CHI NHANH HAI DUONG`) are still unmerged from their parents.

## Why the supplier flag cannot stand alone

**24 of the 64 VN-capable suppliers sell mixed-origin goods.**

| Supplier | VN rows | non-VN rows | origins seen |
|---|---:|---:|---|
| CONG NGHE JOHNSON HEALTH (VIET NAM) | 1,399 | 1,611 | CHINA, GERMANY, TAIWAN, UNKNOWN, VIETNAM |
| ACE MINH NAM | 222 | 286 | CHINA, TAIWAN, THAILND, VIETNAM |
| GUOYUAN VIET NAM | 254 | 43 | CHINA, JAPAN, TAIWAN, VIETNAM |
| ZHENKUNHANG (VIET NAM) | 71 | 63 | CHINA, VIETNAM |

Flipping a whole supplier to originating would promote 1,611 Chinese-origin rows on the
first line alone. This matches the legal finding: a Vietnamese seller's nationality does not
confer Vietnamese origin — the goods must meet the origin rules (NĐ 31/2018 Điều 15.1.g).

After normalization: **38 VN-only, 24 mixed, 70 no-VN.** The VN-only set carries only
3,541 of the 6,272 VN rows — 44% of the benefit sits with the mixed suppliers, so the
VN-only list is a triage convenience, **not a whitelist**.

## The rule this implies

> A material row counts as **originating** iff the row's own `origin` normalizes to VN
> **AND** its supplier is flagged as one that supplies C/O or Phụ lục X. Everything else
> keeps the conservative `non_origin` default.

BCCT asserts *the goods are Vietnamese*; the supplier flag asserts *we can prove it*.
Neither half suffices. Note the flag's semantics: it is about **evidence availability**, not
about the supplier being Vietnamese.

## Design decisions taken

- **Phase 1 lives entirely in CO.** No Data Hub work: both inputs already reach CO. The
  flag is ~132 rows × one boolean, keyed on the normalized supplier name. Storing it in Data
  Hub would mean asking DH to create a supplier entity it does not have, for one consumer.
  (The `client_material_group_map` precedent does not transfer: that map classifies
  *materials*, an entity DH already models.)
- **Data Hub becomes the right home later**, when any of these arrive: stored evidence
  documents with validity + the 5-year retention duty; lot-level overrides; a second
  consumer; or supplier-name merging becoming a real problem. Because the decision is
  evaluated **per row** (`row.origin AND supplier_flag`) and never written onto the material,
  that migration only changes where the flag is read from.
- **Resolve to an originating *amount*, not a boolean.** `origin_value` / `non_origin_value`
  are already money columns (`app/bang_ke_renderer.py:272-273`). Today the resolver returns
  the full value or zero. ATIGA partial cumulation (Form D, Art. 30(2)) later changes only
  the number, not the type. Costs nothing now; saves a rewrite.
- **Snapshot the resolved origin into the case at *Tính*.** The bảng kê export is a pure
  renderer of the web grid; origin resolution round-trips through the form exactly as
  `customs_relevance` does. Without the snapshot, editing a supplier flag would retroactively
  change the RVC of dossiers already locked and filed.
- **Supplier-level only for now.** Lot-level deferred by the client: a supplier who has
  once provided PL X / C/O is expected to keep doing so.

## Open

- Is the client's "Phụ lục X" the same instrument as the "Bản khai báo xuất xứ" of
  NĐ 31/2018 Điều 15.1.g / TT 33/2023 Điều 6.1.c? Unconfirmed.
- CO models only Forms B, AI, CPTPP, EUR.1 (`app/co_forms.py:9-40`). **Form D and AK — the
  two forms the in-bloc phase targets — do not exist in the code yet.**
- Supplier-name normalization beyond whitespace: branch vs parent entity.

## Reproducing

`scripts/` has nothing for this; the throwaway export used for the client list was
`export_ncc.py` in the session scratchpad. The queries above are plain SELECTs against
`hub.bcct_rows` grouped by `consignee_name` and `trim(origin)`.

---

## Addendum 2026-07-11 — agency staff facts + Growatt data (grill part 2)

**Staff statement (via user, 2026-07-11):**
- **Growatt: exactly 2 fixed Phụ lục X suppliers — "công ty Mingjie" and "công ty Minghui".**
- **Johnson: NO supplier provides C/O or Phụ lục X; all imported NVL are non-origin.**

Consequences that correct this file's framing:
- Johnson's 1,252 VN-origin material codes **legally stay `non_origin`** — the current
  all-VNM treatment is the CORRECT answer for Johnson, not an understatement defect.
  The "RVC is understated" claim above holds only where evidence exists. Day-one
  beneficiary of the VN-origin feature = **Growatt only**.
- The 38-VN-only/24-mixed Johnson supplier analysis stays useful as a curation-screen
  data view, but seeds **zero** flags.

**Growatt data (verified `psql -d data_hub`, 2026-07-11):**
- On-spot VN-origin rows live under client_id **`growatt-vn`**: **E13 = 1,444 rows,
  E15 = 296** (E13 = 83% of on-spot volume — the reverse of Johnson's mix).
- `CONG TY TNHH MINGJIE VIET NAM` — E15 only, 81 rows. `CONG TY TNHH MINGHUI VIET NAM`
  — E15 only, 61 rows. Both active under `growatt-vn`'s no-filter config.
- **Name trap:** `MINGJIE INDUSTRIAL (HK) LIMITED` (1 E13 row) is a **different legal
  entity** (Hong Kong) and must NOT be flagged — first real-data validation of the
  no-auto-merge normalization decision.

**Live `eligible_import_declaration_types` configs (2026-07-11):** `growatt-vn`,
`johnson-vn`, `johnson`, `hub-only` = `[]` (= NO filter, all types active —
`co_stock_derivation.py:150-151`); `growatt` (demo) = dncx `["E11","E15"]`;
`do-thanh` = manual `["E11","E15"]`. The dncx preset E13 gap and its fix are in
DECISIONS.md 2026-07-11.
