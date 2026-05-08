-- 039_promote_payload_tier1.sql
--
-- Brief: ad-hoc per user 2026-05-08 — promote frequently-used payload
-- jsonb keys to typed columns. Tier 1 = critical (fixes currency-tag
-- mismatch bug + CO/BCQT consumer needs).
--
-- Bug: `currency` column was sourced from "Đơn vị tiền tệ" (FX-domain
-- transaction currency, e.g. USD), but `total_value` and `unit_price`
-- were sourced from "Tổng trị giá" / "Đơn giá tính thuế" (VND-converted
-- for tax calc). Result: currency=USD with VND-magnitude amounts —
-- semantically wrong for both FX consumers (origin cert) and VND
-- consumers (settlement).
--
-- Fix: split into two parallel domains.
--   FX-domain (transaction currency):
--     currency_nt (was: currency)        — text, e.g. 'USD' / 'EUR'
--     total_value_nt                     — numeric, foreign currency total
--     unit_price_nt                      — numeric, foreign currency per-piece
--   Local-domain (always VND, for tax):
--     total_value (existing)             — VND-converted total
--     unit_price (existing)              — VND-converted per-piece
--     exchange_rate (existing)           — VND per FX unit
--
-- Plus 2 frequently-queried promotions:
--     total_tax                          — Tổng tiền thuế (VND)
--     unloading_location                 — Địa điểm dỡ hàng
--                                          (was: jsonb extract in invoice-matches)

begin;

alter table hub.bcct_rows rename column currency to currency_nt;

alter table hub.bcct_rows
  add column if not exists total_value_nt   numeric(20, 6),
  add column if not exists unit_price_nt    numeric(20, 6),
  add column if not exists total_tax        numeric(20, 6),
  add column if not exists unloading_location text;

-- Backfill from payload jsonb. nullif handles empty strings; cast to
-- numeric is safe per pre-check (75,304/75,304 castable in current DB).
update hub.bcct_rows
   set total_value_nt = nullif(payload->>'Trị giá NT', '')::numeric,
       unit_price_nt  = nullif(payload->>'Đơn giá', '')::numeric,
       total_tax      = nullif(payload->>'Tổng tiền thuế', '')::numeric,
       unloading_location = nullif(payload->>'Địa điểm dỡ hàng', '')
where payload is not null and payload <> '{}'::jsonb;

commit;
