# Data Exploration

## Summary
- Source archive processed: `data/CO-20260415T035524Z-3-001.zip`
- ZIP extraction completed
- RAR extraction completed with `scripts/extract-rars.mjs`
- Current extracted root: `data/extracted/CO`
- Inventory after extraction: `1620` non-archive documents, `16` preserved archives, `1636` files total

## Top-Level Structure
- `CHỨNG TỪ ĐẦU VÀO GROWATT GUS28825K061-1E`
  Large input-document dossier with a major `TKN` subtree.
- `CHỨNG TỪ XIN CO GROWATT GUS28825K061-1E`
  Smaller assembled CO request pack with `DINH CO`.
- `Chưa hoàn thiện`
  Main in-progress bucket.
- `Đã hoàn thiện`
  Completed dossiers.
- `CTU DAU VAO XIN CO SL14.SFB.XM144 DO THANH`
  Standalone dossier extracted from nested archives.
- `CTU XIN CO SL14.SFB.XM144 DO THANH`
  Smaller submission dossier.
- `Quy trình xin CO + file chạy dữ liệu CO`
  Workflow and business-rule artifacts, including the macro workbook.

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

## Major Implications
- The domain is document-heavy and spreadsheet-heavy.
- Customs declaration bundles (`TKN`) dominate file volume and need different treatment from curated submission packs.
- Folder structure mixes status, dossier type, customer/product code, and operator naming conventions.
- Nested archives are preserved after extraction, so ingestion must avoid double counting.

## Business-Rule Sources Found In Data
- `tru lui CO final  SXXK - 2025 commercial-MAC - Huyền đúng.xlsm`
- `QUY TRÌNH XIN CẤP CO.pdf`
- `Lưu trình xin CO.jpg`
- product-specific calculation workbooks such as `Bang Tinh Ham Luong LVC ...xlsx` and `Bang RVC ...xlsx`
- stock or tracking workbooks such as `BẢNG THEO DÕI TỒN CO.xlsx`

## Data Quality Risks
- inconsistent naming with and without accents
- mixed Unicode normalization
- repeated or near-duplicate files
- temporary Office lock files
- multiple status buckets and dossier types sharing similar naming

## Design Implications
- Separate `case status`, `dossier type`, `product/customer code`, and `document type` in the future model.
- Treat workbook logic and criteria workbooks as primary source material for business-rule extraction.
