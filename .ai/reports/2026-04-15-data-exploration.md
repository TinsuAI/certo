# Data Exploration Report

## Summary
- Source archive processed: `data/CO-20260415T035524Z-3-001.zip`
- ZIP extraction completed
- RAR extraction completed with `scripts/extract-rars.mjs`
- Current extracted root: `data/extracted/CO`
- Inventory after extraction: `1620` non-archive documents, `16` preserved archives, `1636` files total

## Top-Level Structure
- `CHỨNG TỪ ĐẦU VÀO GROWATT GUS28825K061-1E`
  Contains a large input-document set for one dossier, including a `TKN` subtree with hundreds of customs declaration spreadsheets.
- `CHỨNG TỪ XIN CO GROWATT GUS28825K061-1E`
  Contains a smaller assembled CO request pack with draft CO output and a `DINH CO` subfolder.
- `Chưa hoàn thiện`
  Main in-progress bucket. This is the largest status area after extraction.
- `Đã hoàn thiện`
  Completed dossiers. Smaller than `Chưa hoàn thiện`, but still contains several named cases and preserved archives.
- `CTU DAU VAO XIN CO SL14.SFB.XM144 DO THANH`
  Standalone dossier extracted from nested archives.
- `CTU XIN CO SL14.SFB.XM144 DO THANH`
  Smaller standalone submission dossier.
- `Quy trình xin CO + file chạy dữ liệu CO`
  Workflow and business-rule artifacts, including the only `.xlsm` workbook.

## File Type Mix
- `1278` `.xls`
- `258` `.pdf`
- `79` `.xlsx`
- `9` `.rar`
- `7` `.zip`
- `2` `.doc`
- `1` `.docx`
- `1` `.xlsm`
- `1` `.jpg`

## Volume by Top-Level Folder
- `Chưa hoàn thiện`: `793` documents, `6` archives
- `CHỨNG TỪ ĐẦU VÀO GROWATT GUS28825K061-1E`: `633` documents, `1` archive
- `CTU DAU VAO XIN CO SL14.SFB.XM144 DO THANH`: `97` documents, `0` archives
- `Đã hoàn thiện`: `78` documents, `5` archives
- `CTU XIN CO SL14.SFB.XM144 DO THANH`: `8` documents, `0` archives
- `CHỨNG TỪ XIN CO GROWATT GUS28825K061-1E`: `8` documents, `0` archives
- `Quy trình xin CO + file chạy dữ liệu CO`: `3` documents, `0` archives

## Major Case Buckets
- `Chưa hoàn thiện/CHỨNG TỪ ĐẦU VÀO XIN CO GIN01425L031`: `641` documents
- `Chưa hoàn thiện/CTU DAU VAO XIN CO Y26-MQDT-SL01.HLN 156HC DO THANH`: `101` documents
- `Đã hoàn thiện/CTU XIN CO HAWH-20260108 HONG AN`: `34` documents
- `Chưa hoàn thiện/CTU DAU VAO XIN CO HAWH-20251230 HONG AN`: `18` documents
- `Chưa hoàn thiện/CTU DAU VAO XIN CO HAWH-20260108 HONG AN`: `17` documents
- `Chưa hoàn thiện/CTU DAU VAO XIN CO HAWH-20251103 HONG AN`: `16` documents
- `Đã hoàn thiện/CTU XIN CO HAWH-20251230 HONG AN`: `14` documents
- `Đã hoàn thiện/CTU XIN CO HAWH-20251103 HONG AN`: `13` documents
- `Đã hoàn thiện/CTU XIN CO GIN01425L031 XUẤT ẤN - GROWATT`: `9` documents
- `Đã hoàn thiện/CTU XIN CO Y26-MQDT-SL01.HLN 156HC DO THANH`: `8` documents

## Likely Business-Rule Sources
- `data/extracted/CO/Quy trình xin CO + file chạy dữ liệu CO/tru lui CO final  SXXK - 2025 commercial-MAC - Huyền đúng.xlsm`
  This is the only macro-enabled workbook found. Sheet names suggest rule and calculation domains: `NK`, `NK2`, `XK`, `DM`, `Xuat`, `X-N`, `Save`, `Tru lui`, `Chiphi`, `LVC`, `RVC`, `EUR1`, `CTH`, `CTSH`, `WOIII`, `FORM B`, `FORM X`, `PTN`.
- `data/extracted/CO/CHỨNG TỪ ĐẦU VÀO GROWATT GUS28825K061-1E/BOM.xlsx`
  Contains `6` sheets: `PV00.0048500`, `PV01.0117600`, `PV01.0117400`, `PV02.0229100`, `PV02.0229200`, `PV02.0229300`.
- `data/extracted/CO/CHỨNG TỪ ĐẦU VÀO GROWATT GUS28825K061-1E/Bảng theo dõi lượng NVL 2026.xlsx`
  Contains `12` sheets and likely tracks material input volume over time.
- `data/extracted/CO/CHỨNG TỪ ĐẦU VÀO GROWATT GUS28825K061-1E/THEO DÕI TỒN CO-SXXK 2026.xlsx`
  Contains `12` sheets and likely tracks stock or running balances related to CO preparation.
- `data/extracted/CO/Quy trình xin CO + file chạy dữ liệu CO/QUY TRÌNH XIN CẤP CO.pdf`
  Likely procedural reference for the current manual workflow.
- `data/extracted/CO/Quy trình xin CO + file chạy dữ liệu CO/Lưu trình xin CO.jpg`
  Likely process/flow diagram.
- `data/extracted/CO/CHỨNG TỪ XIN CO GROWATT GUS28825K061-1E/DINH CO/6. Bang Tinh Ham Luong  LVC GUS28825K061-1E.xlsx`
  Likely a calculation workbook for local value content.
- `data/extracted/CO/Đã hoàn thiện/CTU XIN CO GIN01425L031 XUẤT ẤN - GROWATT/DINH ECOSYS L031/6. Bang RVC GIN01425L031.xlsx`
  Likely a regional value content workbook from a completed case.
- `data/extracted/CO/CHỨNG TỪ ĐẦU VÀO GROWATT GUS28825K061-1E/BẢNG THEO DÕI TỒN CO.xlsx`
  Appears to be a tracking workbook for CO inventory or case monitoring.

## Representative Files
- `data/extracted/CO/CHỨNG TỪ XIN CO GROWATT GUS28825K061-1E/DRAFT CO GUS28825K061-1E.pdf`
- `data/extracted/CO/CHỨNG TỪ XIN CO GROWATT GUS28825K061-1E/DINH CO/7. INV.pdf`
- `data/extracted/CO/CHỨNG TỪ ĐẦU VÀO GROWATT GUS28825K061-1E/BOM  SA00.0004000.XLSX`
- `data/extracted/CO/CHỨNG TỪ ĐẦU VÀO GROWATT GUS28825K061-1E/TKN/ToKhaiHQ7N_QDTQ_107101950210.xls`

## Data Quality and Modeling Risks
- Status and dossier types are mixed together in folder names. Example: `Chưa hoàn thiện` is a status bucket, while `CHỨNG TỪ ĐẦU VÀO ...` and `CTU ...` are dossier/document-set types.
- Naming is inconsistent across folders. There is a mix of Vietnamese with accents, uppercase ASCII, abbreviations, customer/product codes, and person/company names.
- Duplicate or near-duplicate filenames exist. Examples include `5.1. hoa don.pdf` appearing `7` times, `5.2` to `5.6` customs spreadsheets appearing `5` times each, and several `1C25...pdf` invoices appearing `4` times.
- Archives are preserved after extraction, so file inventory includes both extracted content and original bundles. Any ingestion workflow must avoid double counting.
- Path names contain spaces, accents, and long dossier titles. This matters for storage keys, import scripts, and any eventual cross-platform processing.
- Unicode normalization is mixed in some names, for example variants like `Hóa đơn định mức`, which can create cross-platform matching problems.
- Temporary Office files are present, for example `~$5.9. ToKhaiHQ7N_QDTQ_107778233840.xlsx`, and should be excluded from any ingestion pipeline.
- The dataset is heavily spreadsheet-driven. `1278` of `1620` documents are `.xls`, which suggests core data is still locked in legacy Excel formats.
- Large customs declaration subtrees such as `TKN` dominate volume and may need separate ingestion rules from the smaller curated submission packets.

## Immediate Implications
- The first product/domain model should likely separate:
  - case status
  - dossier type
  - product/customer code
  - supporting documents
  - calculation workbooks
  - customs declaration lines or bundles
- The `.xlsm` workbook and the calculation spreadsheets should be treated as primary discovery targets before UI design or database design.
