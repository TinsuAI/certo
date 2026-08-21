-- Run before re-running the manual-test scenarios:
--   psql -d data_hub -f data/manual_test/_cleanup.sql

-- Phase 2026-05-04 BCCT (files 01-03b)
delete from hub.bcct_row_history
 where transaction_key like 'MAN\_%' escape '\';

delete from hub.bcct_rows
 where transaction_key like 'MAN\_%' escape '\';

-- Phase 1+2+3 (files 04-11) — BQD / Catalog / BOM
delete from hub.code_mappings
 where internal_code like 'MAN\_%' escape '\';

delete from hub.materials
 where customs_code like 'MAN-%' or internal_code like 'MAN\_%' escape '\';

-- Cascade delete BOM versions for MAN_ products (also clears bom_version_rows)
delete from hub.bom_versions
 where product_code like 'MAN\_%' escape '\';

-- Pending rows from any in-flight preview
delete from hub.upload_pending
 where parsed_rows::text like '%MAN\_%' escape '\'
    or parsed_rows::text like '%MAN-%';

-- LLM-cached mappings from manual-test runs
delete from hub.parser_mappings
 where mapping::text like '%MAN\_%' escape '\'
    or mapping::text like '%报关%'
    or sample_headers::text ~ 'Internal|Customs|Recipe|Finished Goods';

delete from hub.file_uploads
 where original_filename like '0%_stage_%.xlsx'
    or original_filename like '04_bqd%' or original_filename like '05_bqd%'
    or original_filename like '06_catalog%' or original_filename like '07_catalog%'
    or original_filename like '08_bom%' or original_filename like '09_bom%'
    or original_filename like '10_bcct%' or original_filename like '11_malformed%';
