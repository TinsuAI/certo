# Legacy Workbook Output Sheet Structure

This note preserves the output-sheet structure from the legacy `tru lui CO final ...xlsm` workbook so the application can later generate `bang ke` sheets and export Excel files with the same layout.

## Source And Export Behavior

Primary legacy macro: [`RunUpgrade.bas`](../.ai/extracted-vba/tru-lui-co-final-2025-commercial-mac/RunUpgrade.bas).

The current macro exports five output templates:

| Macro | Source sheet | Saved filename prefix | Copied value range | Print area |
|---|---|---:|---:|---:|
| `runUpgradeLVC` | `LVC` | `LVC` + `Q9` | `A1:AA1626` | `A1:N1623` |
| `runUpgradeRVC` | `RVC` | `RVC` + `Q9` | `A1:AA1626` | `A1:N1623` |
| `runUpgradeCTH` | `CTH` | `CTH` + `Q9` | `A1:AA1626` | `A1:N1623` |
| `runUpgradeCTSH` | `CTSH` | `CTSH` + `Q9` | `A1:AA1626` | `A1:N1623` |
| `runUpgradeEUR1` | `EUR1` | `EUR1` + `Q9` | `A1:AA1623` | `A1:N1623` |

Export loop behavior:

1. Create a new workbook with `Workbooks.Add`.
2. Loop through products from row `16` to the last row in source column `W`.
3. Fill the selected output template from `XK`, `DM`, `Save`, and derived lookup data.
4. Hide empty body rows from the first blank `A` cell through row `1585`.
5. Hide helper columns `O:Y`.
6. Copy the active output sheet into the new workbook.
7. Paste values over the copied range, preserving template formats, merged cells, column widths, row heights, page setup, and hidden states.
8. Rename the copied output tab to `so & P7`, for example `1PV02.0229300`.
9. Restore the source template by clearing `A16:U1585`, unhiding rows `16:1585`, and unhiding columns `O:Y`.

Important implementation rule: do not rebuild the final Excel styling from scratch if exact parity matters. Keep a workbook/template sheet and copy it, then write values into the cells, matching the macro approach.

## Workbook Sheet Roles

| Sheet | Visible title in `A3` | Primary role | Visible conclusion |
|---|---|---|---|
| `LVC` | `BẢNG KÊ KHAI HÀNG HÓA XUẤT KHẨU ĐẠT TIÊU CHÍ "LVC"` | Local/regional value content table | Row `1611`; current sample text still says `RVC <percent> + CTSH` |
| `RVC` | `BẢNG KÊ KHAI HÀNG HÓA XUẤT KHẨU ĐẠT TIÊU CHÍ "RVC"` | Regional value content table | Row `1611`; `RVC <percent> + CTSH` |
| `EUR1` | `BẢNG KÊ KHAI HÀNG HÓA XUẤT KHẨU ĐẠT TIÊU CHÍ "PSR"` | EUR.1 / PSR table with extra EXW conversion block | Row `1617`; `PSR` conclusion |
| `CTH` | `BẢNG KÊ KHAI HÀNG HÓA XUẤT KHẨU ĐẠT TIÊU CHÍ "CTC"` | Change in Tariff Heading | Row `1611`; `CTH` conclusion |
| `CTSH` | `BẢNG KÊ KHAI HÀNG HÓA XUẤT KHẨU ĐẠT TIÊU CHÍ "CTC"` | Change in Tariff Subheading | Row `1611`; `CTSH` conclusion |

The workbook also contains hidden/form sheets such as `WOIII`, `FORM B`, `FORM X`, and `PTN`. They are not exported by the current `RunUpgrade.bas` flow.

## Page And Format Metadata

For the five output sheets:

- Workbook sheet dimension is `A1:JA1624`, but the export only copies through `AA`.
- Printed/PDF area is `A1:N1623`.
- Page setup is landscape with scale `55`.
- Page margins in the inspected workbook are `left=0`, `right=0`, `top=0.23622047244094491`, `bottom=0`, `header=0`, `footer=0`.
- Common merged ranges in the printed area include `A3:N3`, `A4:N4`, `A12:A14`, `B12:B14`, `C12:C14`, `D12:D14`, `E12:E14`, `F12:I12`, `J12:J14`, `K12:L13`, `M12:N13`, `F13:F14`, `G13:G14`, and `H13:I13`.
- `CTH` and `CTSH` keep rows `1588:1609` hidden in the template because their visible result is a tariff-shift conclusion, not the RVC formula block.
- `EUR1` keeps rows `1606:1609` hidden in the template and adds an EXW/EUR.1 block at rows `1610:1615`.
- During export, the macro additionally hides helper columns `O:Y`.

## Row Structure

| Row range | Meaning | Notes |
|---:|---|---|
| `1` | Spacer/top margin | Keep from template. |
| `2` | Appendix label | `E2 = Phụ lục VII`. |
| `3` | Main title | Merged `A3:N3`; differs by output sheet. |
| `4` | Legal/template note | Merged `A4:N4`; references Circular 05/2018/TT-BCT. |
| `5` | Helper metadata | `O5 = SL mã dm`, `P5 = BOM/material row count`. |
| `6` | Merchant and criterion | `B6` merchant, `K6` criterion, `O6/P6` exchange rate. |
| `7` | Tax ID, product description, product code | `K7` product name/description, `P7` product code. |
| `8` | Export declaration label, product HS, incoterm/unit price | `K8` HS, `O8` incoterm, `P8` unit price. |
| `9` | Export declaration date and quantity | `K9` quantity, `L9` UOM, `P9` quantity, `Q9` export declaration key. |
| `10` | Declared total value | `K10 = P8 * P9`; label changes by incoterm. |
| `11` | FOB value | `K11` final FOB value used in calculation. |
| `12:15` | Material table headers | Printed columns `A:N`; helper columns start at `O`. |
| `16:1585` | Material/BOM body | Populated per material line; unused rows are hidden before export. |
| `1586:1588` | Material value totals | Origin and non-origin totals. |
| `1589:1593` | Direct labor cost block | Uses coefficient cells in column `P`. |
| `1594:1599` | Direct allocation cost block | Uses coefficient cells in column `P`. |
| `1600:1604` | Cost, EXW, other cost, FOB block | Builds price explanation. |
| `1606:1609` | Indirect RVC/LVC formula display | Hidden for `CTH`, `CTSH`, and `EUR1` in the inspected template. |
| `1610:1615` | Signature or EUR.1 extra block | Standard signature for `LVC/RVC/CTH/CTSH`; EUR.1 uses extra fields. |
| `1616:1624` | Notes and legal commitment | Row positions differ slightly by sheet. |

## Material Table Columns

Printed columns:

| Column | Header role |
|---:|---|
| `A` | `STT` |
| `B` | Material name. `EUR1` labels this as `Các loại chi phí`; `CTH/CTSH` label it as `Tên nguyên liệu`; `LVC/RVC` use bilingual `Tên nguyên phụ liệu`. |
| `C` | HS code, usually 6 digits. |
| `D` | Unit of measure. |
| `E` | Norm per product, including loss. |
| `F` | Required material quantity for the export lot. |
| `G` | CIF unit price. |
| `H` | Originating value. `LVC/RVC` label this as FTA-origin value. |
| `I` | Non-originating value. `LVC/RVC` label this as non-FTA-origin value. |
| `J` | Country of origin. |
| `K` | Import declaration or VAT invoice number. |
| `L` | Import declaration or VAT invoice date. |
| `M` | Import preferential C/O, producer declaration, or domestic supplier declaration number. |
| `N` | C/O/declaration date. |

Helper columns copied but not printed:

| Column | Legacy role |
|---:|---|
| `O` | Import declaration line. |
| `P` | Material code in body rows; coefficient cells in footer rows. |
| `Q` | Helper key, usually built from export declaration key plus material code. |
| `R` | Payment exchange rate. |
| `S` | Import declaration type. |
| `T` | Helper/count marker. |
| `U` | Helper value. |
| `V` | Helper product lookup key. |
| `W` | Product code. |
| `X` | Export declaration line. |
| `Y` | Quantity. |
| `Z:AA` | Included in copied range but not materially populated by `RunUpgrade.bas`. |

## Footer Calculations

Common value fields:

| Cell | Meaning |
|---:|---|
| `H1588` / `C1586` | Total originating material value, `sumH`. |
| `I1588` / `C1587` | Total non-originating material value, `sumI`. |
| `K1606` | Non-originating material value used by the indirect RVC/LVC formula. |
| `J1606` / `J1609` | FOB display value. |
| `M1607` | Final indirect value-content percentage display. |

Cost explanation block:

| Cell | Formula logic |
|---:|---|
| `I1590` | `P1590 * K10`, salary/bonus. |
| `I1591` | `P1591 * K10`, medical/social benefit. |
| `I1593` | `I1590 + I1591`, total direct labor. |
| `I1595` | `P1595 * K10`, factory rent. |
| `I1596` | `P1596 * K10`, depreciation/insurance/maintenance. |
| `I1597` | `P1597 * K10`, electricity/water for production. |
| `I1599` | `I1595 + I1596 + I1597`, total direct allocation cost. |
| `I1600` | `sumH + sumI + I1593 + I1599`, factory cost. |
| `I1601` | `I1602 - I1600`, profit/difference. |
| `I1602` | EXW value after incoterm handling. |
| `I1603` | Other cost from factory to export/FOB. |
| `I1604` | FOB value. |

Indirect value-content formula used by the workbook:

```text
M1607 = Round((I1604 - K1606) / I1604 * 100, 2) & " %"
```

Incoterm handling:

| Incoterm group | Logic |
|---|---|
| `EXW`, `FCR` | `I1602 = K10`; `I1603 = (K10 / P10) * P1603`; `I1604 = K10 + I1603`; `I1601 = I1602 - I1600`. |
| `FOB` | `I1604 = K10`; `I1603 = (K10 / P10) * P1603`; `I1602 = I1604 - I1603`; `I1601 = I1602 - I1600`. |
| `CFR`, `CIF`, `DDU`, `DDP`, and other values | `freight = (K10 / P10) * P1604`; `I1604 = K10 - freight`; `I1603 = (K10 / P10) * P1603`; `I1602 = I1604 - I1603`; `I1601 = I1602 - I1600`. |

The coefficient cells `P1590`, `P1591`, `P1595`, `P1596`, and `P1597` are preset/input cells in the template. The macro reads them and does not derive them from BOM rows.

## Sheet-Specific Footer Differences

`LVC` and `RVC`:

- Rows `1586:1609` are visible.
- Row `1611` contains the value-content conclusion.
- `RVC` notes are at rows `1616:1620`; `LVC` notes are at rows `1620:1622`.

`CTH` and `CTSH`:

- Rows `1588:1609` are hidden in the template.
- The macro still calculates the cost/value footer, but the visible output is the tariff-shift conclusion at `B1611`.
- Visible notes start around rows `1620:1623`.

`EUR1`:

- Rows `1606:1609` are hidden in the template.
- Rows `1610:1615` contain EUR.1-specific fields:
  - `B1610`: lot mark.
  - `B1611:C1611`: total cost from company to export port.
  - `B1612:C1612`: total export-lot EXW value.
  - `B1613:C1613`: coefficient `K`.
  - `B1614:C1614`: unit EXW.
  - `B1615:C1615`: extra formula field.
- Row `1617` contains the `PSR` conclusion.

## Implementation Notes For Future Export

- Treat `LVC`, `RVC`, `CTH`, `CTSH`, and `EUR1` as template sheets, not as ordinary data tables.
- Preserve workbook formatting by copying the matching template sheet first, then filling values.
- Preserve print area `A1:N1623`; the copied range through `AA` exists to carry helper data and legacy compatibility.
- Hide unused material rows after the first blank `A` value through row `1585`.
- Hide helper columns `O:Y` before saving/exporting.
- Keep formulas out of exported output when matching the macro: copy/paste values over the export range.
- Name generated tabs as `<sequence><product_code>`, matching `so & P7`.
- Expect one output workbook per criterion/export declaration prefix, with one generated tab per product line in the loop.
