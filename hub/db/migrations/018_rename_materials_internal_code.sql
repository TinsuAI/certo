-- 018_rename_materials_internal_code.sql
-- Semantic fix: hub.materials.product_code stores the agency's internal
-- code (NB), not a "product" code in the BOM sense. Other tables already
-- use `internal_code` for the same concept (hub.code_mappings,
-- hub.bcct_rows). This rename brings hub.materials into alignment.
--
-- BOM tables (bom_versions.product_code, bom_change_requests.product_code,
-- bom_version_rows.material_code) are NOT touched — they correctly use
-- "product" to mean "the head of a BOM tree" which is different from
-- this generic NB code.
--
-- Read API impact: /v1/hub/materials response field renames. No external
-- consumers in production yet so safe.

alter table hub.materials rename column product_code to internal_code;

-- Drop the old index name explicitly so the rename below succeeds across
-- environments where the index might already exist with the new name.
alter index if exists hub.idx_materials_product_code
  rename to idx_materials_internal_code;
