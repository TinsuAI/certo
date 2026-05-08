-- 040_promote_payload_tier2.sql
--
-- Brief: ad-hoc per user 2026-05-08 — Tier 2 typed-column promotions.
-- Less critical than Tier 1 (mig 039) but useful for CO origin cert
-- (contract data) + traceability (internal mgmt no + package marks).
--
-- New columns:
--   contract_no         text    — Số hợp đồng (sparse: 191 rows so far)
--   contract_date       date    — Ngày hợp đồng (sparse: 160 rows)
--   internal_mgmt_no    text    — Số quản lý nội bộ (8,963 rows)
--   package_marks       text    — Ký hiệu và số hiệu bao bì (6,254 rows)

begin;

alter table hub.bcct_rows
  add column if not exists contract_no       text,
  add column if not exists contract_date     date,
  add column if not exists internal_mgmt_no  text,
  add column if not exists package_marks     text;

update hub.bcct_rows
   set contract_no       = nullif(payload->>'Số hợp đồng', ''),
       contract_date     = nullif(payload->>'Ngày hợp đồng', '')::date,
       internal_mgmt_no  = nullif(payload->>'Số quản lý nội bộ', ''),
       package_marks     = nullif(payload->>'Ký hiệu và số hiệu bao bì', '')
where payload is not null and payload <> '{}'::jsonb;

commit;
