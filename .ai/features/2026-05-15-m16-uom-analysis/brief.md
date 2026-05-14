# Feature brief — Mẫu 16 UoM drift evidence analysis (Johnson)

**Date:** 2026-05-15
**Owner:** dennis (this session)
**Status:** Round-3 final — 29 verified overrides + 58 codes deferred with drift signal

## Background

Mẫu 16/2025 cho Johnson được ingest 2026-05-13 (commit `69b9da0`). Khi
re-ingest với UoM conversion enabled (commit `b4665f6`, mig 056/057
Phase 2), engine phát hiện 358 rows / 88 codes có cross-family drift
giữa raw_uom của Mẫu 16 và catalog uom của materials:

- 85 codes: M16 raw `SETS` vs catalog `PIECES` (assembly vs count)
- 2 codes: M16 raw `ROLL` vs catalog `PIECES` (count_packaging vs count)
- 1 code: M16 raw `Chai/ Lọ/ Tuýp` vs catalog cùng token nhưng alias thiếu

Lần đầu tôi insert client-wide override `(SETS, PIECES, 1.0)` + `(ROLL,
PIECES, 1.0)` (commit overrides 2026-05-14). User pushback hợp lý — chưa
verify factor thực sự là 1:1.

## Evidence collection methodology

### 1. BCCT yearly UoM choice (cross-check 1)

Verify catalog UoM đúng vs Mẫu 16 UoM đúng bằng cách so sánh với BCCT
declarations cùng material:

| Bucket | # codes | Ý nghĩa |
|---|---|---|
| `BCCT 2025 = M16, catalog WRONG` | 85 | BCCT 2025 và M16 cùng dùng SETS; catalog ghi PIECES từ bootstrap |
| `BCCT 2025 has both` | 3 | Mơ hồ |
| `BCCT 2026 confirms catalog` | 78 (out of 87) | Năm 2026 chuyển sang PIECES |

→ Có shift convention giữa 2025 → 2026: Johnson đổi từ khai báo SETS
sang PIECES cho cùng những material codes. Catalog bootstrap mode value
bị 2026 dominate → catalog = PIECES.

**Kết luận**: catalog không hẳn sai, M16 không hẳn sai — là chuyển đổi
convention thực địa của Johnson.

### 2. Direct qty comparison tech_flat vs M16 (cross-check 2)

So sánh qty giữa SAP tech_flat (raw EA) và M16 (raw SETS/CAY) cho cùng
(product, material):

| | Rows |
|---|---|
| Matched pairs | 486 |
| Exact 1:1 (qty_tf == qty_m16) | 315 (65%) |
| Different ratio | 171 (35%) |

Sample non-1:1: material `1000461274` qua nhiều product có ratio
1.75-2.56. Material `1000307959`: ratio 2.0 cho MFW0503-490, 2.56 cho
MFW0503-510. Cùng material, factor khác nhau theo product.

→ SAP technical BOM ≠ M16 declared BOM về QUANTITY (không chỉ UoM).
SAP là định mức lý thuyết, M16 là định mức thực tế đã trừ hao hụt/yield.

### 3. BCCT dual-unit declarations (cross-check 3 — ĐÂY LÀ EVIDENCE MẠNH NHẤT)

BCCT có 2 cột `unit`/`quantity` + `unit_2`/`quantity_2` — broker khai
2 đơn vị trên CÙNG dòng tờ khai (theo quy định VNACCS yêu cầu trade
unit + tax unit).

Filter dual-unit rows where `(unit, unit_2) = (m16_uom, catalog_uom)`:

| Pair | # rows | # codes | Vai trò |
|---|---|---|---|
| `SETS / PIECES` | 259 | 27 | Direct factor — primary M16 raw, secondary catalog |
| `ROLL / PIECES` | 40 | 2 | Direct factor |
| `SETS / KILO-GRAMMES` | 498 | 58 | KG = tax weight unit, KHÔNG phải count factor |
| `PIECES / KILO-GRAMMES` | 249 | 58 | Same 58 codes, năm khác |

→ **29 codes có direct (raw, catalog) dual-unit evidence** = factor đo
được. **58 codes chỉ có SETS/KG** = không đo được factor (KG là cân
nặng/SET, không phải SETS→PIECES ratio).

### 4. Mode factor per code (refined verification)

Đối với 29 codes có direct evidence, tính mode factor (most common
declaration ratio):

| Mode factor | # codes |
|---|---|
| `1.0` | 28 |
| `2.0` | 1 (`1000454182`) |

**Note**: trong số 28 codes mode=1.0, `1000104388` có 28/30 dòng factor
1.0 + **2/30 dòng factor 4.0** (outlier shipping with bundle packaging).
Mode đại diện convention thường, không bảo đảm 100% mọi declaration.

## Decision (chốt 2026-05-15)

| Bucket | # codes | Action |
|---|---|---|
| Direct evidence, mode factor=1.0 | 28 | **Keep override `factor=1.0`** |
| Direct evidence, mode factor=2.0 | 1 (`1000454182`) | **UPDATE override → `factor=2.0`** |
| Không có direct evidence (chỉ SETS/KG) | 58 | **DELETE override** — fallback Tier-A `unconfirmed_default_1to1` drift, staff xem trong UI tab "UoM cần điền", hỏi Johnson factor cụ thể |
| `Chai/ Lọ/ Tuýp` slash-compound alias missing | 1 | **Keep alias `chai/ lọ/ tuýp → bottle`** (pure synonym, low risk) |

**Tổng:** 29 override (28 factor=1.0 + 1 factor=2.0) + 1 alias mới.
58 codes ship raw VNACCS qty + drift signal cho staff action.

## Root cause analysis

Bất nhất ĐVT giữa M16 2025 vs BCCT 2026 do **3 yếu tố nghiệp vụ**:

1. **VNACCS quy định khai 2 đơn vị** trên tờ NK: trade unit (theo
   invoice/packing list) + tax unit (theo HS code, thường là weight).
   Đó là quy định, không phải convention conversion. Đây là tại sao
   58 codes có dual-unit `SETS/KG` — KG là tax unit, không phải factor.

2. **Convention shift 2025 → 2026**: Johnson hoặc customs broker đổi
   trade unit primary từ `SETS` sang `PIECES`. Khả năng do:
   - Update theo VNACCS chuẩn (HS code yêu cầu đơn vị cụ thể)
   - Đổi broker hoặc cập nhật phong cách khai
   - Supplier đổi packaging (1 SET không còn = 1 PIECE)
   - Yêu cầu nội bộ Johnson chuẩn hóa với SAP (SAP dùng `EA`)

3. **Packaging shipment outliers**: cùng material có thể nhập theo 2
   form khác nhau (rời và bundle). Sample `1000104388`: 28/30 dòng khai
   `1 SET = 1 PIECE` (rời), 2/30 dòng `1 SET = 4 PIECES` (bundle 4).
   Mode đại diện trường hợp đa số.

## Why this approach (evidence-driven, not blanket)

Quy tắc rút ra:

- **Không bulk-assume factor=1.0 cho cross-family UoM drift**. Đoán
  không có evidence là silent corrupt qty.
- **BCCT dual-unit (quantity vs quantity_2) là evidence trực tiếp**
  cho factor — broker đã khai chính thức trên TỜ KHAI HẢI QUAN.
- **Filter điều kiện đúng**: chỉ accept evidence nếu `(unit, unit_2)`
  khớp `(raw_uom, catalog_uom)` của BOM. Pairs khác (vd `SETS/KG`)
  là tax-weight info, không phải count conversion.
- **Mode factor** (most common per code) là proxy reasonable cho
  convention thông thường, nhưng có thể sai cho minority shipments.
- **Bottle aliases (chai/ lọ/ tuýp → bottle)** là synonym thuần — same
  canonical, factor implicit 1.0 — low risk, accept.

## Risk + open items

- **R1: 58 codes không evidence**: hiện ship raw + drift signal. CO
  consumer (2026 dossier) sẽ thấy raw SETS thay vì PIECES → có thể không
  khớp BCCT 2026 declaration. Mitigation: staff per-material verify với
  Johnson, insert override khi có factor cụ thể.
- **R2: Mode factor không đại diện 100%**: vd `1000104388` mode=1.0
  nhưng 2/30 dòng=4.0. Những shipment bundle 4 sẽ store sai. Risk thấp
  (~7% rows misqty cho outlier-prone codes).
- **R3: 1000454182 factor=2.0** chỉ dựa 2/3 declarations. n nhỏ
  (3 rows total). Có thể cần verify thêm với Johnson trước khi trust.
- **R4: Tech_flat 2,543 stale (separate concern)**: SAP raw EA vs
  catalog SETS/CAY drift. Direct qty comparison (cross-check 2) cho
  thấy SAP qty ≠ M16 qty by 35% rows — SAP là lý thuyết, M16 là thực
  tế. Tech_flat NÊN STALE — đó là signal đúng "SAP ≠ M16 declared".

## Files

- `verified_codes.txt` — 29 codes có override với factor
- `unverified_codes.txt` — 58 codes ship raw + drift signal
- Database state: `hub.client_uom_overrides` (29 rows) + `hub.uom_aliases`
  (chai/ lọ/ tuýp → bottle)

## Backlog

1. **Ask Johnson** xác nhận factor SETS→PIECES cho 58 codes unverified.
2. **Ask Johnson** xác nhận `1000454182` factor=2.0 đúng (mode 2/3, n nhỏ).
3. **Future M16 ingest** (M16/2026 sang năm): áp dụng cùng methodology —
   query BCCT dual-unit mode factor before bulk override.
4. **Tech_flat 2,543 stale**: là legitimate signal "SAP lý thuyết ≠
   M16 thực tế". Không action — CO consumer ưu tiên manual_flat cho
   sản phẩm có Mẫu 16, fallback tech_flat khi không có.
5. **Bottle alias chai/ lọ/ tuýp**: pure synonym, safe. Keep.
