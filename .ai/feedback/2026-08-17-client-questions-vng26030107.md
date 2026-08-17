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
| Q1 | `e00f174` | `co_stock.value_basis` = `taxable_vnd` (default) \| `invoice_native`: stock unit prices from `unit_price_nt`/`currency_nt`/`exchange_rate`, FOB from the export declaration's trị giá nguyên tệ, config-page control, DH `to_save` whitelist, new `lvc_mixed_currency` guard |

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

**Q1 is shipped but NOT switched on for anyone.** Every client stays on
`taxable_vnd`; johnson-vn needs the agency's decision first, because flipping the
basis re-derives the whole stock snapshot (`co_config_fingerprint` changes) and
existing locked bảng kê only show USD after mở lại → Tính lại.

**Q1 known limitation — mixed-currency materials.** 309 of johnson-vn's 10,393 import
codes have lines in both USD and VND, so under `invoice_native` one NVL can draw lots
in two currencies. Its native total is then undefined (`allocation_currency_summary`
returns "Nhiều tiền tệ", `material_value` is dropped) and the sheet is blocked. It is
blocked with the right label now (`lvc_mixed_currency` → "Cần xử lý: NVL hai loại
tiền") instead of the misleading "thiếu đơn giá", but there is no in-app way to file
such a sheet in nguyên tệ: the remedy is either splitting the row per declaration or
keeping that client on `taxable_vnd`. Deciding how a mixed-currency row should appear
on the legal bảng kê (one row in VND vs one row per declaration in its own currency)
is a product decision, not implemented.

## Reply to the client (Vietnamese, forwardable)

**1. Đơn giá đang hiện VND, muốn giữ theo USD**

Hệ thống không tự quy đổi. Trên tờ khai, mỗi dòng có hai cột giá: đơn giá nguyên tệ (USD) và
đơn giá tính thuế đã quy VND theo tỷ giá thanh toán. Phần dữ liệu BCCT bên Data Hub có đủ cả
hai (ví dụ tờ khai 107271797510 dòng 20: 0,735317 USD và 19.007,890150 VND, tỷ giá 25.850),
nhưng bên CO hiện chỉ lấy cột VND, nên bảng kê, đơn giá và cả trị giá FOB đều hiện VND. Con số
nhiều số thập phân (80.334,057473) chính là đơn giá tính thuế bằng VND của tờ khai.

Để bảng kê chạy theo USD, chúng tôi cần bổ sung việc đọc đơn giá nguyên tệ + tỷ giá vào phần
tính tồn, rồi tính lại tồn cho Johnson. Việc này ảnh hưởng tới các bảng kê đã chốt (phải mở
lại và tính lại mới hiện USD), nên anh/chị xác nhận trước khi chúng tôi làm: **muốn toàn bộ
bảng kê theo USD (nguyên tệ của tờ khai), hay chỉ những hồ sơ mới từ nay?**

**2. Lâu lâu có mã NVL đơn giá = 0 (và bảng kê xuất ra cũng 0)**

Đây là lỗi của chúng tôi và là lỗi nặng nhất trong 4 mục. Nguyên nhân: khi một mã NVL được trừ
lùi từ **hai lô nhập có đơn giá khác nhau**, ô đơn giá hiển thị dòng chữ "Nhiều đơn giá". Dòng
chữ đó bị lưu vào chính ô số đơn giá, nên lần **Tính bảng kê** sau, hệ thống đọc dòng chữ đó
như một con số, không đọc được và hiểu thành **0** — từ đó đơn giá và trị giá của mã đó thành 0
và không tự sửa được dù tính lại.

Chúng tôi đã đếm trên dữ liệu thật của Johnson: **34 dòng** đang bị 0 (thuộc 11 hồ sơ) và
**22 dòng** đang hiện "Nhiều đơn giá" (sẽ thành 0 nếu tính lại). Trong đó có các bảng kê **đã
chốt**, gồm cả hồ sơ VNG26030107 (MPL0109-39 2 dòng, MFW0588-39 1 dòng) và hồ sơ SCI26030014
(11 dòng). Vì các dòng này là NVL không xuất xứ, trị giá 0 làm **phần không xuất xứ bị thiếu →
tỷ lệ LVC/RVC bị cao hơn thực tế**. Anh/chị tạm thời chưa nộp các bảng kê có dòng đơn giá 0.

Chúng tôi sẽ sửa để: đơn giá lấy đúng theo lô nhập (không bị dòng chữ ghi đè), ô đơn giá không
bao giờ chứa chữ, và thêm chốt chặn không cho Chốt bảng kê nếu còn dòng có lô nhập mà đơn giá
bằng 0. Sau khi sửa, các hồ sơ nêu trên cần mở lại → Tính bảng kê lại → Chốt lại; chúng tôi sẽ
gửi danh sách cụ thể.

**3. Hệ thống tự chọn xét theo LVC hay CTC?**

Không có bước tự chọn. Hai sheet của anh/chị đang để tiêu chí theo khuyến nghị của CPTPP, và
nguyên văn tiêu chí đó gồm cả CTH lẫn RVC ("CTH; hoặc RVC không thấp hơn 30% trực tiếp / 40%
gián tiếp / 50% …"), nên thanh trên cùng hiện đồng thời hai ô tham khảo: LVC 53,70% so với
ngưỡng 30%, và CTC "Đạt CTH". Cả hai chỉ là tham khảo, không quyết định gì; nội dung ghi lên
C/O là tiêu chí anh/chị chọn.

Chỗ chọn tiêu chí đã có: trên từng bảng kê, bấm chip **⚙ Cấu hình** → mục **Tiêu chí** (WO, PE,
CC, CTH, CTSH, RVC, LVC, PSR, ô "Khác…" để gõ tay, các lựa chọn "hoặc", và Ngưỡng %) → Lưu →
Tính bảng kê lại. Nếu anh/chị muốn nó thành **một bước bắt buộc phải chọn trước khi tính** (thay
vì nằm trong cấu hình), chúng tôi làm được — anh/chị xác nhận là muốn bắt buộc chọn, hay chỉ cần
hiện rõ tiêu chí đang áp dụng ngay trên bảng kê.

**4. Xuất hồ sơ .zip chờ 30 phút không ra file**

File đã tạo xong, nhưng màn hình không cập nhật. Cụ thể hồ sơ VNG26030107: bấm xuất lúc 15:32,
file hoàn tất lúc 15:38 (21,3 MB, gồm cả tờ khai ghép 157 TKN), và anh/chị tải được lúc 16:11
sau khi tải lại trang. Trong khoảng đó trang vẫn hiện "Đang tạo hồ sơ .zip…" vì phần theo dõi
tiến độ chỉ chạy khi trang được tải mới (F5); khi anh/chị chuyển tab trong hồ sơ (và khi bấm
"Mở lại hồ sơ" lúc 15:34 rồi đóng lại), phần theo dõi không chạy nữa nên nút tải file không
xuất hiện.

Đây là lỗi của chúng tôi, đang sửa. Trong lúc chờ bản cập nhật: sau khi bấm **Xuất hồ sơ**, chờ
khoảng 5–7 phút với hồ sơ nhiều tờ khai rồi **F5 lại trang Review** — nút "Tải hồ sơ .zip" sẽ
hiện. File được lưu lại trên hệ thống nên rời trang cũng không mất.

Về thời gian: 5 phút 42 giây của lần xuất này chia làm hai phần — khoảng 2 phút là in/ghép 157
tờ khai nhập thành PDF, khoảng 3 phút 20 là hệ thống tính lại dữ liệu tồn/tờ khai của hồ sơ.
Chúng tôi sẽ rút ngắn phần thứ hai và ghi đúng thời gian dự kiến trên màn hình (hiện đang ghi
"~1 phút").
