-- 010: Promote 12 CO-essential payload keys to typed columns + convert
-- `year` to GENERATED ALWAYS AS (EXTRACT(YEAR FROM registration_date)) STORED.
--
-- Order matters and is documented inline. The whole migration runs in a single
-- transaction (per app.database.apply_migrations); no CREATE INDEX CONCURRENTLY.
-- At current corpus size (~5K rows) wall-clock is well under 1s; the brief
-- discusses the cost model for larger production data.
--
-- See .ai/features/2026-05-04-bcct-overhaul-and-llm-parsing.md for rationale.

-- ────────────────────────────────────────────────────────────────────────
-- Pre-flight: refuse to run if any row lacks registration_date (the new
-- generated column requires it). Current invariant: 0 rows with NULL date.
-- Failing here is loud and recoverable; silent skip would not be.
-- ────────────────────────────────────────────────────────────────────────
do $$
declare n_null bigint;
begin
  select count(*) into n_null from hub.bcct_rows where registration_date is null;
  if n_null > 0 then
    raise exception
      'Cannot apply 010: % bcct_rows have NULL registration_date. '
      'Resolve those rows (delete or assign date) before retrying.', n_null;
  end if;
end$$;

-- ────────────────────────────────────────────────────────────────────────
-- 1. Add 12 new typed columns. Metadata-only on PG11+ (no defaults).
-- ────────────────────────────────────────────────────────────────────────
alter table hub.bcct_rows
  add column if not exists exporter_name      text,
  add column if not exists exporter_tax_code  text,
  add column if not exists consignee_name     text,
  add column if not exists incoterms          text,
  add column if not exists weight             numeric(20,6),
  add column if not exists weight_unit        text,
  add column if not exists package_count      numeric(20,6),
  add column if not exists package_unit       text,
  add column if not exists invoice_date       date,
  add column if not exists departure_date     date,
  add column if not exists destination_code   text,
  add column if not exists destination_name   text,
  add column if not exists transport_mode     text,
  add column if not exists exchange_rate      numeric(20,6);

-- ────────────────────────────────────────────────────────────────────────
-- 2. Back-fill from payload jsonb. Uses NULLIF + casts safe against empty
-- strings. Date columns: payload values are ISO 8601 timestamps (xlrd
-- xldate_as_datetime / openpyxl datetime → .isoformat()). Cast through
-- timestamp then to date.
-- ────────────────────────────────────────────────────────────────────────
update hub.bcct_rows set
  exporter_name      = nullif(payload->>'Tên doanh nghiệp', ''),
  exporter_tax_code  = nullif(payload->>'Mã doanh nghiệp', ''),
  consignee_name     = nullif(payload->>'Tên đối tác', ''),
  incoterms          = nullif(payload->>'Điều kiện giá hóa đơn', ''),
  weight             = nullif(payload->>'Trọng lượng', '')::numeric,
  weight_unit        = nullif(payload->>'Mã ĐVT trọng lượng', ''),
  package_count      = nullif(payload->>'Số lượng kiện', '')::numeric,
  package_unit       = nullif(payload->>'Mã ĐVT kiện', ''),
  invoice_date       = (nullif(payload->>'Ngày hóa đơn', '')::timestamp)::date,
  departure_date     = (nullif(payload->>'Ngày khởi hành vận chuyển', '')::timestamp)::date,
  destination_code   = nullif(payload->>'Mã địa điểm đích', ''),
  destination_name   = nullif(payload->>'Tên địa điểm đích cho vận chuyển bảo thuế', ''),
  transport_mode     = nullif(payload->>'Mã hiệu PTVC', ''),
  exchange_rate      = nullif(payload->>'Tỷ giá thanh toán', '')::numeric
where payload != '{}'::jsonb;

-- ────────────────────────────────────────────────────────────────────────
-- 3. Convert `year` to GENERATED ALWAYS AS STORED. Postgres requires:
--    drop PK → drop column → re-add as generated → re-add PK → recreate
--    indexes that referenced year (auto-dropped with the column).
-- ────────────────────────────────────────────────────────────────────────
alter table hub.bcct_rows drop constraint bcct_rows_pkey;

alter table hub.bcct_rows drop column year;

alter table hub.bcct_rows
  add column year integer
    generated always as (extract(year from registration_date)::integer) stored
    not null;

alter table hub.bcct_rows
  add constraint bcct_rows_pkey
    primary key (client_id, year, transaction_key, line_no);

-- ────────────────────────────────────────────────────────────────────────
-- 4. Recreate covering indexes that referenced `year`. The DROP COLUMN
-- in step 3 took these out automatically; recreate verbatim from 005.
-- (idx_bcct_resolved was dropped in 009 along with resolved_customs_code;
-- not recreated.)
-- ────────────────────────────────────────────────────────────────────────
create index if not exists idx_bcct_internal     on hub.bcct_rows(client_id, year, internal_code);
create index if not exists idx_bcct_customs      on hub.bcct_rows(client_id, year, customs_code);
create index if not exists idx_bcct_declaration  on hub.bcct_rows(client_id, year, declaration_no, line_no);
create index if not exists idx_bcct_invoice      on hub.bcct_rows(client_id, year, invoice_ref);
create index if not exists idx_bcct_direction    on hub.bcct_rows(client_id, year, direction);

-- New indexes for the promoted CO columns most likely to be filtered/joined.
create index if not exists idx_bcct_invoice_date on hub.bcct_rows(client_id, invoice_date);
create index if not exists idx_bcct_consignee    on hub.bcct_rows(client_id, consignee_name);
