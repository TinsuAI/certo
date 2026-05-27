-- Cost allocation ratios per client × finished-product code.
--
-- Drives the LVC/RVC cost-buildup auto-fill: when the operator clicks
-- "Áp hệ số" on an origin product panel, the app multiplies each
-- coefficient by FOB and pre-fills the 6 detail inputs.
--
-- Mode A (per Mã SP): row with non-empty product_code.
-- Mode B (per client, fallback): row with product_code = '' (sentinel).
--
-- Profit is intentionally not stored as a coefficient — TT 05/2018 form B
-- treats profit as the residual (FOB − material − I+II+III − VII), and the
-- GROWATT sample sheet defines it the same way (=GIÁ XUẤT XƯỞNG − CHI PHÍ
-- XUẤT XƯỞNG).
--
-- See .ai/features/2026-05-27-cost-allocation-ratios.md and
-- app/cost_allocation_store.py.

create table if not exists co_cost_allocation_ratio (
  client_id              text not null,
  product_code           text not null default '',
  coef_wages             numeric(14,10) not null default 0,
  coef_welfare           numeric(14,10) not null default 0,
  coef_rent              numeric(14,10) not null default 0,
  coef_depreciation      numeric(14,10) not null default 0,
  coef_other_mfg         numeric(14,10) not null default 0,
  coef_transport_storage numeric(14,10) not null default 0,
  note                   text not null default '',
  updated_at             timestamptz not null default now(),
  primary key (client_id, product_code)
);
