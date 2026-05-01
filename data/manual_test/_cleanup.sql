-- Run before re-running the manual-test scenarios:
--   psql -d data_hub -f data/manual_test/_cleanup.sql

delete from hub.bcct_row_history
 where transaction_key like 'MAN\_%' escape '\';

delete from hub.bcct_rows
 where transaction_key like 'MAN\_%' escape '\';

delete from hub.upload_pending
 where parsed_rows::text like '%MAN\_%' escape '\';

delete from hub.parser_mappings
 where mapping::text like '%报关%';

delete from hub.file_uploads
 where original_filename like '0%_stage_%.xlsx';
