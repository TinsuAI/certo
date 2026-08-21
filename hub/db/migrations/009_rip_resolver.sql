-- Rip BCQT-flavored resolver out of hub. Settlement-side canonical pick belongs
-- to BCQT (consumer), not hub (master data owner). See feature brief
-- .ai/features/2026-05-02-rip-resolver-from-hub.md
--
-- Keep: hub.code_mappings (BQD pairs — master data), bcct_rows.internal_code
-- (parser output at ingestion), parsers/goods_name.py.
--
-- Drop: materialized canonical pick + denormalized projection on bcct_rows.

drop index if exists hub.idx_bcct_resolved;

alter table hub.bcct_rows drop column if exists resolved_customs_code;

drop table if exists hub.code_mapping_resolutions;
