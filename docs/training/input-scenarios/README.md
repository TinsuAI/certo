# Training Input Scenarios

Bộ file này dùng để demo các tình huống nhập liệu đa dạng hơn bộ demo chính. File nằm cùng thư mục này để trainer có thể chọn trực tiếp từ file picker khi mở browser.

Regenerate:

```bash
uv run python scripts/generate_training_input_scenarios.py
```

## Nhóm Danh Mục

| File | Upload vào | Tình huống demo | Kết quả mong đợi |
|---|---|---|---|
| `01_catalog_vi_hq_registered.xlsx` | `/clients/<id>/catalog/upload` | File chuẩn tiếng Việt, tick HQ registered | 5 row hợp lệ |
| `02_catalog_english_headers.xlsx` | `/clients/<id>/catalog/upload` | Header tiếng Anh, kiểm tra flexible parser/mapping | 2 row hợp lệ |
| `03_catalog_with_skipped_rows.xlsx` | `/clients/<id>/catalog/upload` | Một dòng thiếu cả Mã HQ và Mã NB | 2 row hợp lệ, 1 skipped row trên preview |

## Nhóm BQD

| File | Upload vào | Tình huống demo | Kết quả mong đợi |
|---|---|---|---|
| `04_bqd_identity.xlsx` | `/clients/<id>/bqd/upload` | Mapping identity cho client một hệ mã | 4 cặp mapping |
| `05_bqd_dual_code_one_to_many.xlsx` | `/clients/<id>/bqd/upload` | Một mã nội bộ map ra nhiều mã HQ | Preview cho thấy 4 cặp, dùng để giải thích 1-N |

## Nhóm BCCT

| File | Upload vào | Tình huống demo | Kết quả mong đợi |
|---|---|---|---|
| `06_bcct_full_co_fields.xlsx` | `/clients/<id>/bcct/upload` | BCCT có đủ trường C/O: invoice, partner, incoterms, package, transport | 4 row hợp lệ |
| `07_bcct_header_row_5.xlsx` | `/clients/<id>/bcct/upload` | Header nằm ở dòng 5, có phần tiêu đề phía trên | 2 row hợp lệ |
| `08_bcct_update_baseline.xlsx` | `/clients/<id>/bcct/upload` | Baseline trước khi demo update diff | 3 row mới |
| `09_bcct_update_changed.xlsx` | `/clients/<id>/bcct/upload` | Upload sau baseline: 1 changed, 1 noop, 1 new, 1 orphan | Preview diff/update gate |
| `10_wrong_file_bom_uploaded_as_bcct.xlsx` | `/clients/<id>/bcct/upload` | Người dùng upload nhầm file BOM vào BCCT | Parser từ chối, không ingest rác |

## Nhóm BOM

| File | Upload vào | Profile | Tình huống demo | Kết quả mong đợi |
|---|---|---|---|---|
| `11_bom_manual_flat.xlsx` | `/clients/<id>/bom/upload` | `manual_flat` | BOM phẳng sẵn | 2 product, 3 component rows |
| `12_bom_technical_multilevel.xlsx` | `/clients/<id>/bom/upload` | `technical_flatten` | BOM đa cấp có BTP trung gian | Flatten preview trước confirm |
| `13_bom_sap_style_english.xlsx` | `/clients/<id>/bom/upload` | `sap_exploded_levels` hoặc `auto` | SAP exploded level format | 1 root product, 4 parsed rows |

## Cách dùng trong buổi training

1. Dùng bộ demo chính trước để tạo narrative end-to-end.
2. Sau đó chọn 3-5 tình huống phụ tùy audience:
   - Nhân sự nhập liệu: `03_catalog_with_skipped_rows.xlsx`, `07_bcct_header_row_5.xlsx`, `10_wrong_file_bom_uploaded_as_bcct.xlsx`.
   - Quản lý nghiệp vụ: `09_bcct_update_changed.xlsx`, `12_bom_technical_multilevel.xlsx`.
   - Tích hợp C/O: `06_bcct_full_co_fields.xlsx`, `13_bom_sap_style_english.xlsx`.
3. Với cặp update BCCT, luôn upload `08_bcct_update_baseline.xlsx` trước, rồi mới upload `09_bcct_update_changed.xlsx`.

