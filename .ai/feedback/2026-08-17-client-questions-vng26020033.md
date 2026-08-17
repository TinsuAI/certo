# Client questions — johnson-vn / case VNG26020033 (2026-08-17)

Live evidence: prod `co-db-1` (schema `co`) + prod `data-hub-db-1` (schema `hub`), read-only.
Case = `co-case-6cb034e91cb7` (`CO-JOHNSON-VN-VNG26020033-6CB0`), rev 39, updated 2026-08-17 03:08Z.

## Measured state

| | MPL0108-39 | MFW0509-39 |
|---|---|---|
| persisted sheet status | `bom_loaded` | `stale` |
| materials (active) | 145 | 86 |
| `declarable` + `ready` (priced, lot-matched) | 82 | 62 |
| `declarable_unmatched` (no BCCT lot) | 35 | 19 |
| `excluded_non_material` (phi vật tư) | 28 | 5 |
| `valuation_status == missing_unit_value` | **0** | **0** |
| `lvc_missing_price` | true | true |
| `lvc_declarable_unmatched` | true | true |
| `lvc_allocation_shortage` | false | false |

Distinct unmatched codes in the case: **53**.

Data coverage (`hub.bcct_rows`, johnson-vn): import 84,231 rows / 10,393 distinct
`customs_code` / 2025-04-18 → 2026-08-05; export 8,742 rows. CO stock snapshot
(`co.co_stock_rows`) = 84,231 rows, refreshed 2026-08-17 03:25Z — 1:1 with DH, no filter loss.
`co.client_configs` johnson-vn: no declaration-type filter, `allocation_code.strategy =
same_as_customs_code`, `lot_policy = line_level`, **no `features` section → `bulk_delete_junk_rows`
is OFF**.

## Findings

**F1 — the 53 unmatched codes are absent from every declaration, not from the upload.**
0/53 appear in `hub.bcct_rows` for johnson-vn in either direction. All 53 exist in
`hub.materials` with `provenance = {"seen_in_bom_only": true}` and `name == material_code`
(no description). Matched codes carry `provenance.seen_in_bcct` with `decl_count` and a full
Vietnamese description (e.g. `0000096074`, 54 declarations). Client-wide: **3,822 / 14,527**
johnson-vn catalog materials are `seen_in_bom_only`. `hub.code_mappings` has **0 rows for
johnson-vn** (growatt-vn has 2,913) — so a BOM code that is not literally the declared customs
code can never match. Uploading more BCCT of the same declarations cannot change this.
Secondary: earliest import row is **2025-04-18**, so any Jan–mid-Apr 2025 declaration never landed.

**F2 — `lvc_missing_price` is wrong here (defect).** `app/web/co_case_context.py:3233`:

```python
enriched["lvc_missing_price"] = any(
    not material.get("deleted")
    and material.get("origin_status") == "non_origin"
    and (material.get("valuation_status") == "missing_unit_value" or material.get("unit_value_missing"))
    for material in materials
)
```

No material on either sheet has `valuation_status == missing_unit_value`; the flag fires only
through the `or unit_value_missing` disjunct. A no-lot row gets `material_value = None` →
`unit_value_missing = True`, while `valuation_status` is deliberately set `partial_allocation`
(`co_case_context.py:2734-2740`, ADR 2026-07-11: "a no-lot line's defect is the missing DOCUMENT,
not a missing price"). The predicate also does not exclude `bom_technical_noise`, unlike its
sibling `lvc_allocation_shortage` (`:3255`), which is why shortage reads false while missing_price
reads true. Net effect: the operator is told to fix prices on rows that are all priced.
Candidate fix: add `and not material.get("bom_technical_noise")` to the predicate, mirroring the
shortage flag. NOT implemented — needs a decision.

**F3 — fixing F2 does not unblock the case.** `calculated_sheet_status`
(`app/routers/co_case.py:2202-2226`) also holds a sheet at `bom_loaded` on
`lvc_declarable_unmatched`, which is true by design (DC3c) from the 35/19 unmatched rows. The
28/5 phi-vật-tư rows are folded out of the bảng kê but are NOT soft-deleted, so they keep
tripping F2 until they are deleted. Removing/substituting the rác rows makes both sheets
lockable with no code change.

**F4 — the aggregate panel reports "có thể Chốt tất cả" while the case is blocked.**
`case_shortfall_rollup` (`co_case_context.py:2181-2284`) routes every all-noise material into
`folded_rac`, never into `materials`, so `material_count == 0` → the panel renders
"✓ Đủ tồn cho tất cả SP … có thể 'Chốt tất cả'" (`co_case.html:6393`). The `folded_rac` list is
then dropped client-side when the feature flag is off: `racItems = bulkEnabled ?
racItemsFromFolded(folded) : []` (`co_case.html:6368`), and `racPanelHtml([])` returns "". With
johnson-vn's flag OFF the operator sees no trace of the 53 rác codes. "Chốt tất cả" then skips
both sheets (`bom_loaded` + `stale`) → "Đã chốt 0 sheet · bỏ qua 2".

**F5 — the sheet-list badges are stale in-page.** Screenshot 2 shows both sheets "Đã tính" while
the persisted statuses were already `bom_loaded` / `stale`; F5 shows the correct chips. The
aggregate flow warns about child sheets ("Đã thay NVL ở server — các tab sheet con cập nhật khi
tải lại", `co_case.html:6382`) but does not repaint the status column.

**F6 — criterion selection exists.** Per-sheet `⚙ Cấu hình` chip → "Tiêu chí" segments
WO / PE / CC / CTH / CTSH / RVC / LVC / PSR + "Khác…" free text + "hoặc" alternates
(CTH / CTSH / RVC 40%) + "Ngưỡng %" (`co_case.html:1332-1381`), persisted as
`criteria_override` / `form_override` / `lvc_threshold_override` on the sheet state. The criterion
text drives the LVC threshold (`normalized_lvc_result:3486`) and the CTC preview
(`tariff_shift_rule_from_criterion:3441` → `evaluate_tariff_shift`, label "Đạt/Không đạt {rule}
preview", HS-of-TP vs HS-of-non-origin-NVL only). Both sheets currently run on empty
"(khuyến nghị)" criteria — hence "CTC —" and MPL0108's `partial_review` (no threshold).
LVC fail does not block lock; only the four guards in `calculated_sheet_status` do.

## What was done (2026-08-17)

- **Prod config:** `features.bulk_delete_junk_rows` ON for johnson-vn (`config_version` 1→2,
  `co_config_fingerprint` unchanged `17c95904c2712c54` → no stock re-derivation).
- **F2 fixed:** `lvc_missing_price` now excludes `bom_technical_noise`, mirroring
  `lvc_allocation_shortage` (`co_case_context.py:3233`).
- **F5 fixed:** `recalculate_origin_sheet_and_status` (`co_case.py`) replaces the hardcoded
  `"calculated"` at the two aggregate routes (bulk-substitute, bulk-delete-rác).
- **F4 fixed:** aggregate lists `folded_rac` read-only even when the flag is off, and stops
  inviting "Chốt tất cả" while `declarable_unmatched` remains.
- Suite 1035 pass / 17 skip; e2e on a real Johnson clone (flag on + off) and a synthetic
  zero-shortfall rollup. NOT deployed yet.

**Same defect class, left out of scope (needs a decision):** `co_case.py:3358` (per-sheet "Lưu
bảng kê") and `:3556` (mở chốt) also stamp `"calculated"` without re-deriving. Adjacent, not fixed:
VNM sums `non_origin_cif_value` over noise rows too (`co_case_context.py:2455-2460`, inert today —
noise rows carry no value), and the LVC "Tạm đạt/tạm tính" label still counts noise rows
(`:2461`), which is cosmetic and does not block lock.

## Reply to the client (Vietnamese, forwardable)

**1. BCCT đã tải lên nhưng bộ CO vẫn thiếu mã hàng**

Dữ liệu BCCT nhập của Johnson trên Data Hub hiện có 84.231 dòng, 10.393 mã, từ 18/04/2025 đến
05/08/2026, và bên CO đã đồng bộ đủ 84.231 dòng (làm mới tồn lúc 10:25 sáng nay). Không có dòng
nào bị lọc mất.

Trong hồ sơ VNG26020033 có 53 mã NVL không khớp được. Chúng tôi đã kiểm tra từng mã: **cả 53 mã
không xuất hiện trong bất kỳ tờ khai nào của Johnson** (cả nhập lẫn xuất) trong toàn bộ dữ liệu đã
tải lên. Trên Data Hub, 53 mã này chỉ tồn tại vì được nhìn thấy trong BOM, không có tên hàng, không
có tờ khai kèm theo — ví dụ 1000097110, 1000436344, K60000905, 004075-A2. Đối chiếu: mã khớp được
như 0000096074 có tên đầy đủ và 54 tờ khai nhập.

Vì vậy tải thêm BCCT của cùng những tờ khai đó sẽ không làm 53 mã này khớp. Cần kiểm tra ba khả năng:

- **Mã BOM khác mã khai hải quan.** Nếu nhà máy dùng mã nội bộ trong BOM còn tờ khai dùng mã khác
  thì phải khai báo bảng ánh xạ mã trên Data Hub. Hiện Johnson chưa có dòng ánh xạ nào (Growatt có
  2.913 dòng). Nhóm mã 10 chữ số bắt đầu bằng 1000… nghi ngờ thuộc trường hợp này.
- **NVL mua trong nước.** Nếu mua nội địa theo hoá đơn VAT thì không có tờ khai nhập; loại này phải
  xử lý bằng chứng từ khác, không thể khớp tồn nhập.
- **Nhập trước 18/04/2025.** Dữ liệu sớm nhất đang có là 18/04/2025. Nếu anh/chị đã tải từ tháng
  01/2025 thì phần tháng 1 đến giữa tháng 4 chưa lên hệ thống — kiểm tra lại các file đó.

Về "thay thế không đủ tồn": mã thay thế lấy từ đúng kho tồn đó, đã trừ phần các hồ sơ khác đã chốt,
và loại các lô nhập cách ngày tờ khai xuất dưới 2 ngày. Nếu mã thay thế cũng ít tồn thì kết quả là
không đủ.

**2. "Đủ tồn cho tất cả SP" nhưng "Đã chốt 0 sheet"**

Đây là lỗi hiển thị bên chúng tôi, không phải anh/chị thao tác sai. Panel "Tổng hợp NVL" chỉ đếm
NVL **thiếu tồn**; 63 dòng của MPL0108-39 và 24 dòng của MFW0509-39 thuộc nhóm "không có trong tờ
khai" nên bị gấp lại và không được đếm, vì thế panel báo "đủ tồn". Nhưng chính 63/24 dòng đó lại
đang chặn bước chốt. Trạng thái thật trên server lúc bấm là: MPL0108-39 = "cần xử lý", MFW0509-39 =
"cần tính lại" — không sheet nào ở trạng thái chốt được, nên "Chốt tất cả" bỏ qua cả 2.

Để chốt được, cần xử lý xong các dòng sau rồi Tính lại:

- MPL0108-39: 35 dòng "vật tư chưa khớp tờ khai" (thay mã hoặc xoá) + 28 dòng "phi vật tư" (xoá).
- MFW0509-39: 19 dòng chưa khớp + 5 dòng phi vật tư, sau đó bấm "Tính lại".

Công cụ chọn/xoá hàng loạt các dòng này đã có sẵn trong hệ thống nhưng trước đó đang tắt cho tài
khoản Johnson. **Chúng tôi đã bật (17/08/2026)** — anh/chị mở "Tổng hợp NVL", bấm "Tính tồn lại
(tất cả SP)", panel sẽ liệt kê các mã này kèm nút chọn theo nhóm, "Chọn mã thay thế…" cho nhóm chưa
khớp tờ khai, và "Xoá dòng đã chọn" cho nhóm phi vật tư. Xong thì Tính lại rồi Chốt.

**3 + 4. Báo "thiếu đơn giá" trong khi mọi dòng đều có đơn giá**

Anh/chị kiểm tra đúng. Chúng tôi đã đếm trên dữ liệu thật: **không có dòng nào thiếu đơn giá** —
82/82 dòng của MPL0108-39 và 62/62 dòng của MFW0509-39 đều đã khớp lô nhập và có đủ đơn giá.

Cảnh báo "thiếu đơn giá" đang bị bật nhầm bởi chính các dòng không khớp tờ khai (35 + 28 dòng). Các
dòng này không có lô nhập nên không có đơn giá, và hệ thống đang tính chúng vào cảnh báo giá thay vì
cảnh báo chứng từ. Đây là lỗi nhãn của chúng tôi. **Đã sửa xong, sẽ có trên hệ thống ở lần cập nhật
tới;** trong lúc chờ, anh/chị cứ bỏ qua dòng chữ "thiếu đơn giá" — việc cần làm là xử lý các mã chưa
khớp tờ khai ở mục 2, không phải nhập đơn giá.

Việc F5 mới thấy cảnh báo là do sau khi thay NVL ở màn hình tổng hợp, hệ thống ghi trạng thái sheet
là "đã tính" mà không kiểm lại các điều kiện chốt, nên danh sách hiện "Đã tính" còn bước Chốt thì từ
chối. **Đã sửa cùng đợt** — sau cập nhật, trạng thái hiện đúng ngay, không cần F5.

**5. Chọn tiêu chí PSR / CTH thay cho RVC, LVC**

Có. Trên từng bảng kê, bấm chip **⚙ Cấu hình** ở thanh trên cùng (chỗ đang hiện "khuyến nghị
(EUR.1)"). Trong đó có:

- **Hiệp định / Form** — chọn form khác form hệ thống khuyến nghị.
- **Tiêu chí** — các nút WO, PE, CC, CTH, CTSH, RVC, LVC, PSR; có ô "Khác…" để gõ tay tiêu chí đầy
  đủ (ví dụ "AIFTA 35% FOB + CTSH"), và các lựa chọn "hoặc" (CTH / CTSH / RVC 40%) cho tiêu chí có
  nhiều phương án.
- **Ngưỡng %** — đặt ngưỡng riêng nếu khác mặc định.

Chọn xong bấm **Lưu** rồi **Tính bảng kê** lại. Khi tiêu chí có CC/CTH/CTSH, hệ thống sẽ hiện kết
quả đối chiếu chuyển đổi mã số (ô "CTC" hiện đang là "—" vì hai sheet đang để tiêu chí mặc định
theo khuyến nghị, chưa chọn tiêu chí cụ thể). Lưu ý phần đối chiếu CTC hiện chỉ so mã HS của thành
phẩm với mã HS của NVL không xuất xứ để tham khảo, chưa thay thế việc tra Phụ lục PSR.
