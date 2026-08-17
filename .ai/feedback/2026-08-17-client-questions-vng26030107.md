# Client questions — johnson-vn / case VNG26030107 (2026-08-17, batch 2)

Operator (Thanh Tâm, Johnson VN) sent 4 questions with screenshots on
`CO-JOHNSON-VN-VNG26030107-ECEB` = `co-case-ecebf50044b9` (5 sheets, all `locked`,
case `completed`, dossier already exported). All evidence below is measured read-only on
live prod: `co-db-1` (schema `co`), `data-hub-db-1` (schema `hub`), `docker logs co-app-1`
+ `data-hub-app-1`.

Case state: MPL0109-39 (208 NVL), MFW0588-39 (107), MFW0525-571 (121), MFW0506-39 (88),
MFW0502-571 (86). Every product: `fob_currency = VND`, `origin_sheet_currency_mode = native`,
`criteria_override` empty (recommended CPTPP criteria).

---

## Q1 — "đã quy đổi hết trong BCCT từ USD sang VND? để nguyên theo USD giúp em"

**CO does not convert anything. It reads the VND column of the declaration and never
ingests the foreign-currency unit price.**

- Every one of johnson-vn's 84,231 `co.co_stock_rows` carries
  `value_currency = "VND"`, `exchange_rate_to_vnd = "1"`, `exchange_rate_source = "vnd_native"`,
  `unit_value_source = "bcct_taxable_unit_price"`.
- `hub.bcct_rows` carries **both** currencies per line. Example (decl `107271797510` line 20,
  code `1000495386`): `unit_price = 19007.890150` (VND), `total_value = 380157.803` (VND),
  `unit_price_nt = 0.735317`, `total_value_nt = 14.7063`, `currency_nt = USD`,
  `exchange_rate = 25850`. johnson-vn import rows: **74,987 USD** (74,945 with a native unit
  price) + 9,244 VND. Export: 6,860 USD, 1,497 EUR, 243 JPY, 142 VND.
- The CO adapter maps only the VND side (`app/data_hub_client.py:1265-1276`):
  `taxable_unit_price ← row.unit_price` and
  `value_currency = "VND" if customs_value else …` — `customs_value ← total_value` (VND) is
  always present, so every row is stamped VND regardless of `currency_nt`.
  `foreign_currency_value ← total_value_nt` is mapped, but there is **no `unit_price_nt`
  mapping** — CO has the native line total, never the native unit price.
- Result: `native` currency mode resolves to `product.fob_currency`, which is also VND
  (`fob_vnd = 77,792,075.84` on MPL0109-39), so the whole sheet, the FOB and the export
  render VND. The 6-decimal prices (`80334.057473`) are the customs taxable unit price in
  VND — the conversion was done by the declaration itself at the payment rate, upstream of
  both CO and Data Hub.

**Fix is CO-side only — no Data Hub request needed; implemented as `co_stock.value_basis` (`e00f174`, default off).** `GET /v1/hub/clients/{id}/bcct/rows`
already returns `unit_price_nt, total_value_nt, currency_nt, exchange_rate`
(`data-hub/app/routes/api.py:617`). Work needed:
1. adapter: map `unit_price_nt` + keep `currency_nt`/`exchange_rate`;
2. `app/co_stock_derivation.py`: emit `unit_value` in native currency +
   `unit_value_vnd` + real `exchange_rate_to_vnd` instead of forcing VND
   (`:114-127` `value_currency = "VND" if customs_value or taxable_unit_price`);
3. `co_config_fingerprint` bump → full stock re-derivation for the client;
4. FOB: derive `fob_currency`/FOB from the export declaration's `currency_nt`/`total_value_nt`.

Display and export already support dual currency (`unit_value_native` / `unit_value_vnd`,
`_pick_currency_value`, `origin_sheet_currency_mode`), so the change is at ingest + derivation.
**Risk to state before doing it:** re-deriving stock for a live client with locked sheets,
closed cases and stock claims. Existing bảng kê would show USD only after mở lại → Tính lại.

---

## Q2 — "lâu lâu đơn giá mã NVL đang để là 0, xuất bảng kê cũng 0" (DEFECT, highest severity)

**Root cause chain — a display label round-trips into a numeric field and is then coerced to 0.**

1. A material covered by **two lots with different unit prices** gets
   `unit_value = "Nhiều đơn giá"` (`allocation_unit_value_summary`,
   `app/web/co_case_context.py:3100-3106`). The per-lot prices and `material_value` are still
   correct at this point.
2. The grid round-trips that field: hidden input
   `product_N_material_M_unit_value` (`co_case.html:1707`) → saved into `material.unit_value`.
3. `sheet_edit_bom_rows` (`app/routers/co_case.py:763`) copies it into the next calculation's
   BOM row: `row["unit_value"] = material.get("unit_value", "")`.
4. `stock_allocation_line` gives that carried field **top priority over the customs lot price**
   (`co_case_context.py:2962-2970`: `("bom", bom_row.get("unit_value"))` before
   `("co_stock", stock.get("unit_value"))`), and `first_decimal_source` treats any non-empty
   string as present (`:3542`), then `decimal_value` swallows the `InvalidOperation` and
   returns **`Decimal("0")`** (`:3547-3551`).
5. Every lot line gets `unit_value = 0`, `material_value = 0` → material `unit_value = "0"`,
   `material_value = "0"` → 0 in the grid, 0 in the bảng kê export.
   `valuation_status` stays `ready`, so no belt/flag fires.
6. **Sticky:** the 0 is carried back as a "BOM price" on every later Tính lại, so
   recalculating never repairs it.

Evidence (prod): the two lots of `1000495386` on MPL0109-39 are
`import-row-d7ce4a46e8602b2d` / `…ba44e662670d8739`, both with
`payload.unit_value = 19007.89015` in `co_stock_rows` (indexed 2026-08-17 02:26Z, i.e. before
the 08:2x calculation), yet both allocation lines persist `unit_value = "0"`,
`valuation_source = "bom"`. The same code in case VNG26020033 (single lot) prices correctly at
19,007.89. Same pattern for `005062-00` (2 lots → 0; 1 lot → 217.98) and `1000108800`.
No `material_overrides` entry exists for these rows (override keys are row-index based).

**Blast radius (prod, all cases):** johnson-vn **34 rows** with `unit_value = "0"` while lots
are allocated, across **11 cases**, plus **22 rows** currently showing `"Nhiều đơn giá"` (they
turn into 0 at the next Tính lại). growatt-vn: 0 rows. Affected sheets include locked and
already-exported ones: `SCI26030014-999F` (MFW0506-39 2, MFW0525-571 4, VGM0121-05 1,
VGM0125-05 4 — all `locked`), `VNG26010020-DE40` (MFW0525-39 1, `locked`),
`VNG26030107-ECEB` (MPL0109-39 2, MFW0588-39 1 — `locked`, case `completed`, dossier exported).

**Consequence:** those rows are `non_origin` with `material_value = 0`, so the VNM/non-origin
numerator is understated and **LVC/RVC is overstated** on sheets that are already locked and
filed (MPL0109-39 shows LVC 53.70% / 30%).

**Fix (implemented — `9b63bd8`):**
- never write a non-numeric label into `unit_value`: keep the numeric field empty when lots
  disagree and carry the "Nhiều đơn giá" text in a separate display field;
- `first_decimal_source` must skip non-numeric text instead of coercing to 0 (and
  `decimal_value` should not silently return 0 on `InvalidOperation` in this path);
- stop treating a CO-computed value as a BOM input: when the row has allocated lots, the lot
  price wins; the carried value is a fallback only (or drop the carry entirely for rows with lots);
- belt: a row with lots, `valuation_status = ready` and `unit_value = 0` must block lock.
- repair: after the fix, affected sheets need mở lại → Tính lại → Chốt; the 34 rows must be
  re-priced and their LVC re-checked.

---

## Q3 — "nó tự auto chọn xét theo LVC hoặc CTC? em muốn thêm 1 bước chọn tiêu chí"

**Nothing auto-selects.** `criteria_override` is empty on all 5 sheets, so the sheet runs the
recommended CPTPP criteria text: `"CTH; hoặc RVC không thấp hơn a) 30% theo công thức tính
trực tiếp; hoặc b) 40% … c) 50% …"`. That single text contains both a tariff-shift rule (CTH)
and RVC thresholds, so the header shows **both** previews at once: `LVC 53.70% / 30%` (threshold
parsed from the text) and `CTC Đạt CTH preview` (`tariff_shift_rule_from_criterion` →
`evaluate_tariff_shift`, HS of TP vs HS of non-origin NVL only). Neither preview decides
anything — what is filed is the criterion text the operator sets, and LVC failure does not
block Chốt.

Manual selection already exists per sheet: `⚙ Cấu hình` → **Tiêu chí** segments
WO/PE/CC/CTH/CTSH/RVC/LVC/PSR + "Khác…" free text + "hoặc" alternates + Ngưỡng %
(`co_case.html:1332-1381`) — same answer as the 2026-08-17 batch-1 F6, different case.
The request is UX: make criterion selection an explicit step in the flow instead of a chip in
a settings modal (e.g. a required pick before Tính, or surface the criterion in the sheet
toolbar with "chưa chọn" state). Product decision, not a defect.

---

## Q4 — "chờ 30 phút vẫn chưa xuất được file .zip" (DEFECT — UI never updates)

**The zip was finished after 5m42s and was downloadable; the page never stopped showing the
spinner.** Measured timeline (prod):

| time (UTC) | event |
|---|---|
| 08:32:53 | `POST export-dossier-zip` → job `running` |
| 08:33:07 → 08:34:29 | 16 status polls (2s timer + ~3s response) |
| 08:34:18 | operator clicks **Mở lại hồ sơ** → review page re-renders; case is no longer `completed`, so the export panel + its polling script are not rendered at all (`co_case.html:1960` `{% if _case_completed %}`) |
| 08:34:32 | **Đóng hồ sơ** again |
| 08:36:06 | `GET /review` **through the in-app shell swap** → server renders the spinner, **zero polls after this** |
| 08:36:16 | DH merged export PDF (1 TKX) completes |
| 08:38:24 | DH merged import PDF (157 TKN) completes (~128s) |
| 08:38:35 | zip written — 21,292,073 bytes, `status: done`, `stale: false`, `can_download: true` |
| 09:10:51 | session expired → SSO → **full page load** → download button appears |
| 09:11:02 | `GET …/download` → 200 (33 min after the file was ready) |

**Root cause:** the polling code is a page-level inline `<script>` inside the review section
(`co_case.html:1978-2011`). In-app navigation replaces the shell with
`currentShell.replaceWith(document.importNode(nextShell, true))`
(`co_case.html:2282`) — imported `<script>` nodes never execute — and
`refreshCaseShellInteractions` (`:6981-7003`) has no dossier-export initializer. So after any
tab switch or form action, the server-rendered spinner is frozen: it never polls, never
becomes the download button. Only F5 / a direct URL arms it.

Secondary defects in the same surface:
- **Reopen while running** removes the panel entirely (no state, no progress, no cancel).
- **Copy is wrong:** "Có thể mất tới ~1 phút" — this build took 5m42s (157 TKN). No elapsed
  time is shown.
- **Orphaned `running` state:** `_view` (`app/dossier_export_service.py:146-159`) never checks
  whether a live Future exists; only `_is_running` does, at submit. If the worker process dies
  mid-job (deploy/restart), the panel shows the spinner forever with **no button to retry** —
  the same dead end, permanently.
- **Poll gives up silently** when a response contains no `.dossier-export-state` (e.g. a
  session-expired login page returned with 200): `panel.innerHTML` is replaced and no new
  timer is scheduled.

**Where the 342s went** (answers "is it the TKN PDF?"): ~200s CO-side before the PDFs
(`co_case_source_context` heavy pull + `case_tkx_tkn_summary` over 84k stock rows +
supporting-file reads), then ~128s for the merged import PDF of 157 TKN. So the PDF render is
about a third — the pre-PDF recompute is the bigger half. A closed case could reuse the
persisted snapshot instead of re-pulling; follow-up, not part of the UI fix.

**Fix (proposed):** move polling into `initDossierExportPolling(root)` called from
`refreshCaseShellInteractions` (guard against double-arming per panel); honest ETA + elapsed
timer; orphan detection in `_view` (consult `_FUTURES` like `_is_running`) so a dead job offers
"Xuất lại"; keep polling when a poll response is unusable.

---

## What was implemented (2026-08-17, batch 2)

| Q | Commit | Change |
|---|---|---|
| Q2 | `9b63bd8` | lot price outranks the carried value; non-numeric text is never a number; new `lvc_zero_lot_price` belt (calculate / lock gate / export blockers / attention chip) |
| Q4 | `7633ac2` + `51cc85e` | `initDossierExportPolling` armed from `refreshCaseShellInteractions`; panel survives reopen (without offering an export the closed-case gate would 409); honest ETA + elapsed; orphan detection in `_view`; poll survives unusable responses |
| Q3 | `3e41f24` | explicit "Tiêu chí" chip in the sheet strip + modal wording + review-list marker |
| Q1 | `e00f174` (superseded) → two-lane rework | **Reworked after review.** The ingest switch was the wrong lever; every lot now carries both money lanes and the choice of what to PRINT is the per-sheet `origin_sheet_currency_mode` that already existed. See "Q1 rework" below. |

**Q2 blast radius after deploy (measured on prod, read-only).** Nothing changes
retroactively — a persisted sheet keeps its numbers until someone runs Tính lại, and
the new belt only guards sheets calculated after the deploy: `lvc_zero_lot_price` is
read off the persisted product dict, which sheets locked earlier never carried. The
already-exported VNG26030107 dossier can still be re-exported as it is; fixing those
rows is an operator pass (mở lại → Tính lại → Chốt), after which the corrected LVC
must be re-checked against the 30% threshold before re-filing. On
that next Tính lại, **80 of 3,816** johnson-vn allocation lines get repriced to their
own lot's đơn giá: the 34 lines currently at 0 gain a real price (LVC on those sheets
drops), and lines like `VGM0121-05` / `1000535105` (persisted 328,491.42 vs its lot's
294,493) or `1000224684` (5,578.19 vs 5,580.66) stop carrying a price copied from a
different declaration. growatt-vn: 0 lines affected.

### Q1 rework — two lanes, per-sheet switch (replaces `co_stock.value_basis`)

The first cut put the choice at ingest: a per-client `value_basis` that re-derived the
whole stock snapshot. Two things were wrong with it.

1. **It computed LVC across two currencies.** Under `invoice_native` the FOB came from
   the export declaration's nguyên tệ while the lots stayed on their own currency —
   and johnson-vn files **209 of 1,304** export declarations in EUR/JPY/VND (EUR 102,
   JPY 44, VND 63) while 89% of its import lots are USD. `normalized_lvc_result`
   subtracts VNM from FOB with no currency check, so those cases would have produced a
   silently wrong ratio. Nothing was enabled in production, so no filed dossier was
   affected.
2. **It re-derived 84,231 rows to change a presentation choice**, and invalidated
   locked sheets, for something the operator should be able to flip per bảng kê.

What the rework does instead:

- **Every lot carries both lanes, always.** VND lane (`unit_value`, `customs_value`,
  `value_currency = "VND"`) is what every calculation reads; invoice lane
  (`unit_value_native`, `customs_value_native`, labelled by `native_currency`) is the
  declaration's own nguyên-tệ figures. `exchange_rate_to_vnd` is now resolved against
  the **invoice** currency (the declared tỷ giá thanh toán), not the always-VND
  calculation lane. `DERIVATION_SCHEMA_VERSION` 3 → 4 so existing snapshots re-derive
  once.
- **LVC/RVC always in VND** (`normalized_lvc_result` reads `fob_vnd` + `vnm_value_vnd`),
  which closes hole 1 permanently — the ratio can no longer mix currencies whatever the
  declaration says.
- **The product carries the export declaration's invoice lane** (`invoice_currency`,
  `fob_invoice`, `fob_fx_rate` from its own `exchange_rate`), and that pair survives the
  product → match → product round trip a recalculation performs.
- **Display follows the per-sheet switch that already existed** (⚙ Cấu hình → Tiền tệ).
  When the lot's own declaration is in the target currency the exact declared figure is
  printed rather than a VND-divided approximation — both in the export
  (`_pick_currency_value`) and in the grid (`applyCurrencyMode`), which must agree.
  FOB is resolved the same way (`product_fob_in_target`), so the header can no longer
  print a VND amount under a USD label.
- **The mixed-currency blocker is gone.** With the VND lane authoritative, a material
  fed by a USD lot and a VND lot sums fine; only its nguyên-tệ figure is left blank
  (there is no single one). The 309 johnson codes with lines in both currencies no
  longer block anything.
- The FOB/VNM chips on the sheet strip stay in VND with a VND label (they are the LVC
  inputs); the declaration's nguyên-tệ FOB is in their tooltip.

Verified on real local johnson-vn data (`.ai/scripts/e2e_invoice_lane_display.py`):
the same sheet exported twice — nguyên tệ mode prints đơn giá **0.735317 USD** with a
USD label, VND mode prints **19,007.89015 VND** with a VND label, LVC identical (99.96)
in both, and no re-derivation between them.

**Live state after deploy (prod, verified):** johnson-vn's stock snapshot was
re-derived on 2026-08-17 16:55Z (`derivation_schema_version` 3 → 4, full, reason
`schema_version`, 35s): all 84,231 rows now carry the invoice lane — **74,952 USD**
(every one with the declaration's own rate, `bcct_declared`) + 9,279 VND — the VND lane
is unchanged (84,231 rows still priced), and all 1,621 stock claims of locked sheets
still resolve to their lots. Every johnson sheet already runs `currency_mode = native`
(142/142), so **no per-client default is needed**: a sheet comes out in the invoice
currency as soon as it is recalculated, because the product-level invoice lane is
attached when the sheet is rebuilt from the export declaration (0 of 157 existing
products carry it yet — they were calculated before the deploy).

Proven on prod read-only for MPL0109-39 of VNG26030107: its persisted match states
`currency = USD`, `customs_value = 38,896,037.92` VND and `foreign_currency_value =
1,488.16` USD → the rebuilt product resolves target currency **USD** and prints FOB
**1,488.16**.

That check also exposed a gap: DH's invoice-match rows carry **no `exchange_rate`**, so
`fob_fx_rate` was empty and a lot declared in the other currency (9,279 VND lines on a
USD sheet) would have printed its VND figure under a USD label. Fixed by deriving the
rate from the two totals the same declaration line states
(`customs_value / foreign_currency_value`, source `declaration_ratio`); a declared rate
still wins when present.

**Still open for the agency to decide:** whether johnson's sheets should default to
nguyên tệ (a per-client default for the sheet switch is not built yet — today it is
per sheet, defaulting to `native`, which resolves to the invoice currency only when the
export declaration states one).

### ĐVT (đơn vị tính) — convert at the line, or block Chốt

CO never compared the BOM's đơn vị tính with the unit on the customs lot it consumes:
the demand was subtracted from `remaining_qty` as if the two were the same unit. Data
Hub does align units when it builds a BOM artifact (`applied_uom_factor`,
`applied_uom_source` incl. `unconfirmed_default`), but that answers a different
question (BOM source unit → BOM unit), and CO read neither field.

Measured on prod johnson-vn: **226 of 3,816** allocated lines have BOM uom ≠ lot unit.
184 are spellings of the same unit (EA ↔ PIECES) and convert 1:1; **42 lines across 25
codes** cross quantities — EA ↔ SETS (35), EA ↔ CAY (2), EA ↔ KILO-GRAMMES (2),
KG ↔ PIECES (2), EA ↔ METRIC-TONS (1) — and were silently treated as 1:1.

Shipped:
- `app/uom_conversion.py` resolves a pair in three tiers: same unit / alias (incl.
  Vietnamese names) → factor 1; same physical family (KG↔G↔MT, M↔CM↔MM, L↔ML) → the
  arithmetic factor; anything else → `unconfirmed`.
- The allocator converts the demand into each lot's unit before subtracting, and the
  line carries both quantities (`allocated_qty` in lot units, `allocated_qty_bom_uom`
  in BOM units) plus `uom_factor` + `uom_factor_source`.
- An unconfirmed pair keeps today's 1:1 arithmetic (so Tính still works) but flags the
  row; the new `lvc_uom_unconfirmed` belt holds the sheet at `bom_loaded`, is re-checked
  at the lock gate and the export blockers, and gets its own attention chip
  ("Cần xử lý: ĐVT chưa khớp").
- The row shows `⇄ SETS?` — clicking it asks "1 SET = ? EA", saves the factor per client
  (optionally per material) with who confirmed it and when
  (`co_uom_factor` table + JSON fallback, `app/uom_factor_store.py`), then recalculates.

### Tiêu chí — chosen once per lô hàng, required before Chốt

Storage stays per sheet (the file prints it per product), but the decision is made once
for the case and inherited: **sheet override → case choice → engine recommendation**.
Prod data supports it: 34 johnson cases / 157 sheets, **no case with more than one HS**,
and only 1 of 157 sheets ever carried its own criterion.

- New case-level bar on the origin step: shows the criterion for the whole lô, "Dùng
  khuyến nghị" (one click, recorded as a human choice), "Chọn…", "Bỏ chọn"; warns how
  many sheets are still unchosen.
- The per-sheet chip now names the source ("theo lô hàng" / "riêng sheet này" /
  "chưa chọn").
- **Chốt requires a chosen criterion** (`criteria_source` ∈ {sheet, case}); Tính is
  never blocked by it. The gate sits after the data belts so the operator fixes data
  problems first.
- Criterion-aware header: `criterion_family()` classifies the effective text
  (value_content / tariff_shift / wholly_obtained / mixed). Under a pure CTC rule the
  LVC chip loses its threshold and pass/fail colouring and reads "tham khảo"; under a
  value rule the CTC chip does. "Phương pháp" is derived instead of the hardcoded
  "Build-down LVC/RVC".
- The threshold is re-derived from the criterion in force, so changing the criterion no
  longer leaves the previous 30% on screen.

**Two whitelists had to be widened for the case-level choice to exist at all:**
`update_case_record` and `case_from_record` copy a fixed key list, so `criteria_choice`
was silently dropped on write and invisible on read until both were extended — and
`origin_case_from_request`'s form branch rebuilds a case from form fields only, so it
now re-attaches case-level state or a form-based lock would see an unchosen criterion.

**Rollout note:** after deploy, every existing sheet reads "chưa chọn tiêu chí" and
cannot be Chốt until someone picks one — one click per case ("Dùng khuyến nghị")
covers a whole lô. Already-locked sheets and closed cases are untouched.

Verified end to end on real johnson-vn lots
(`.ai/scripts/e2e_uom_and_criteria.py`, code `1000485357` whose lots are all in SETS
against a BOM row in EA): the mismatch flags and blocks Chốt with the ĐVT reason → the
route confirms "1 SET = 5 EA" → 10 EA takes **2 SETS** off the lot and the flag clears →
Chốt then refuses for the criterion → choosing "CTH" for the lô makes every sheet
inherit it, drops the LVC threshold, switches the method label to "Chuyển đổi mã số
(CTC)", and clears the gate.

## Reply to the client (Vietnamese, forwardable)

Bản này viết sau khi đã sửa và deploy xong (prod + demo chạy `2c25147`), thay cho bản
nháp trước đó.

**1. Đơn giá đang hiện VND, anh/chị muốn giữ theo USD**

Hệ thống không tự quy đổi. Mỗi dòng tờ khai có hai cột giá: đơn giá nguyên tệ (USD) và
đơn giá tính thuế đã quy VND theo tỷ giá thanh toán. Trước đây bên CO chỉ đọc cột VND,
nên bảng kê, đơn giá và trị giá FOB đều hiện VND.

Đã sửa: mỗi lô tồn nay mang **cả hai** — số VND (dùng để tính LVC) và số nguyên tệ đúng
như tờ khai ghi, kèm tỷ giá thanh toán của chính tờ khai đó. Dữ liệu tồn của Johnson đã
được làm mới ngày 17/08: **84.231/84.231 dòng** có đủ hai cột (74.952 dòng USD, 9.279
dòng khai bằng VND — loại nhập tại chỗ/nội địa thì vẫn là VND, đúng bản chất).

Cách dùng: mở bảng kê → chip **⚙ Cấu hình** → **Tiền tệ = Nguyên tệ** (mặc định đã là
Nguyên tệ) → Lưu → **Tính bảng kê lại**. Sau bước tính lại, đơn giá in ra là đúng con số
USD trên tờ khai (ví dụ mã 0000096074: 3,0116 USD thay vì 80.334,057473 VND), FOB cũng
theo USD của tờ khai xuất. Đổi qua lại giữa VND và nguyên tệ chỉ là một lựa chọn trên
bảng kê, bấm là đổi, không phải tính lại tồn.

Một điểm quan trọng: **tỷ lệ LVC/RVC luôn được tính bằng VND** dù bảng kê in bằng USD.
Đây là chủ ý: trong dữ liệu của Johnson có 102 tờ khai xuất bằng EUR, 44 bằng JPY, trong
khi 89% lô nhập là USD; nếu lấy FOB một loại tiền trừ trị giá NVL loại tiền khác thì tỷ
lệ sẽ sai mà không có dấu hiệu gì. Tính bằng VND rồi in ra nguyên tệ là cách duy nhất
vừa đúng vừa cho phép in theo tiền hoá đơn.

**2. Lâu lâu có mã NVL đơn giá = 0 (và bảng kê xuất ra cũng 0)**

Đây là lỗi của chúng tôi, đã sửa. Nguyên nhân: khi một mã NVL được trừ lùi từ **hai lô
nhập có đơn giá khác nhau**, ô đơn giá hiển thị dòng chữ "Nhiều đơn giá"; dòng chữ đó bị
lưu vào chính ô số đơn giá, nên lần Tính bảng kê sau hệ thống đọc nó như một con số,
không đọc được và hiểu thành **0**. Từ đó đơn giá và trị giá của mã đó thành 0, và tính
lại cũng không tự khỏi.

Đo trên dữ liệu thật của Johnson: **34 dòng** đang bị 0 (thuộc 11 hồ sơ) và **22 dòng**
đang hiện "Nhiều đơn giá". Trong đó có bảng kê **đã chốt**, gồm hồ sơ VNG26030107
(MPL0109-39 2 dòng, MFW0588-39 1 dòng) và hồ sơ SCI26030014 (11 dòng). Vì các dòng này
là NVL không xuất xứ, trị giá 0 làm phần không xuất xứ bị thiếu → **tỷ lệ LVC/RVC cao
hơn thực tế**.

Từ nay đơn giá luôn lấy theo lô nhập đã khớp; ngoài ra hệ thống **chặn Chốt** nếu còn
dòng đã khớp lô mà đơn giá bằng 0. Việc cần làm với các hồ sơ trên: mở lại → **Tính bảng
kê lại** → kiểm tra lại LVC còn đạt ngưỡng không → Chốt lại. Chúng tôi có thể gửi danh
sách chi tiết từng hồ sơ/từng dòng nếu anh/chị cần.

**3. Chọn tiêu chí xuất xứ**

Hệ thống không tự chọn giữa LVC và CTC. Trước đây hai sheet của anh/chị để tiêu chí theo
khuyến nghị của CPTPP, mà nguyên văn tiêu chí đó gồm **cả** CTH **lẫn** RVC (30% trực
tiếp / 40% gián tiếp / 50% tập trung), nên thanh số liệu hiện đồng thời hai ô — đó là
hai phương án, đạt một trong hai là đủ.

Đã bổ sung:
- **Chọn tiêu chí cho cả lô hàng** ở đầu bước Bảng kê C/O: có nút "Dùng khuyến nghị"
  (một cú bấm), hoặc gõ tiêu chí khác. Mọi bảng kê trong lô thừa hưởng; bảng kê nào cần
  khác thì đặt riêng ở ⚙ Cấu hình → Tiêu chí.
- Chip **Tiêu chí** trên từng bảng kê nói rõ tiêu chí đang áp dụng và nguồn ("theo lô
  hàng" / "riêng sheet này" / "chưa chọn").
- Khi tiêu chí là chuyển đổi mã số (CC/CTH/CTSH), ô LVC **không còn chấm đạt/không đạt**
  và không hiện ngưỡng — chỉ để tham khảo, vì tiêu chí đó không xét hàm lượng giá trị.
  Nhãn "Phương pháp" cũng đổi theo tiêu chí thay vì luôn ghi "Build-down LVC/RVC".
- **Từ nay phải chọn tiêu chí trước khi Chốt.** Bước Tính bảng kê không bị chặn. Các
  bảng kê hiện có sẽ báo "chưa chọn tiêu chí" cho tới khi anh/chị bấm chọn — một cú bấm
  cho cả hồ sơ. Bảng kê đã chốt và hồ sơ đã đóng không bị ảnh hưởng.

**4. Xuất hồ sơ .zip chờ mãi không ra file**

File đã tạo xong, chỉ có màn hình không cập nhật. Hồ sơ VNG26030107: bấm xuất 15:32,
file hoàn tất 15:38 (21,3 MB, gồm tờ khai ghép 157 TKN), anh/chị tải được lúc 16:11 sau
khi tải lại trang. Lỗi ở phần theo dõi tiến độ: nó chỉ chạy khi trang được tải mới, nên
khi anh/chị chuyển tab trong hồ sơ (và khi bấm "Mở lại hồ sơ" lúc 15:34 rồi đóng lại)
thì nút tải file không hiện ra.

Đã sửa: phần theo dõi chạy cả khi chuyển tab; màn hình ghi đúng thời gian dự kiến (5–7
phút với hồ sơ nhiều tờ khai) kèm số phút đã chạy; nếu tiến trình bị dừng giữa (khởi
động lại hệ thống) thì hiện nút "Xuất lại" thay vì quay mãi. Về thời gian: 5 phút 42
giây của lần đó gồm khoảng 2 phút ghép 157 tờ khai nhập thành PDF và khoảng 3 phút 20
tính lại dữ liệu tồn/tờ khai — phần sau chúng tôi sẽ rút ngắn.

**5. Mới: đơn vị tính giữa BOM và tờ khai nhập**

Nhân rà soát mục 1–2 chúng tôi phát hiện một lỗi chưa ai báo: hệ thống **không so** đơn
vị tính trong BOM với đơn vị tính trên tờ khai nhập, cứ trừ tồn như thể hai đơn vị là
một. Trên dữ liệu Johnson có **226/3.816 dòng** lệch đơn vị; 184 dòng chỉ khác cách viết
(EA và PIECES — không sao), nhưng **42 dòng thuộc 25 mã** là khác đại lượng thật: EA với
SETS (35 dòng), EA với CAY, EA với KILO-GRAMMES, KG với PIECES, EA với METRIC-TONS. Với
những dòng này số lượng trừ tồn (và trị giá) đang dựa trên giả định 1:1 chưa ai kiểm.

Đã sửa: cặp đơn vị chỉ khác tên (kể cả tên Việt) hoặc cùng họ đo lường (kg↔g↔tấn,
m↔cm↔mm, l↔ml) thì hệ thống tự quy đổi. Cặp khác đại lượng thì **cần anh/chị xác nhận
hệ số** — trên dòng đó có nút `⇄`, bấm vào và trả lời "1 SET bằng mấy EA"; hệ số được
lưu cho công ty (ghi kèm ai xác nhận, lúc nào) và áp cho các hồ sơ sau. Trước khi xác
nhận, hệ thống vẫn tính tạm theo 1:1 nhưng **không cho Chốt** bảng kê đó.
