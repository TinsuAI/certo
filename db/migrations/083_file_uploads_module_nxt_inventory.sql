-- Allow NXT + year-end inventory-snapshot uploads to flow through the shared
-- hub.file_uploads stash (mig 082 added their tables; this opens the upload
-- module check that gates record_upload). Additive: existing modules unchanged.
alter table hub.file_uploads drop constraint if exists chk_module;
alter table hub.file_uploads add constraint chk_module
  check (module in ('materials','bcct','bom','code_mappings','nxt','inventory'));
