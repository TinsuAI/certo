-- 025: Repair typed columns that were filled from the wrong Excel column
-- by the pre-2026-05-04 BCCT parser.
--
-- Root cause: the older parser used substring matching in `index_headers`
-- combined with short aliases (e.g. `"đvt"`, `"tt"`, `"đơn giá"`,
-- `"trị giá"`) that incidentally matched longer customs headers earlier
-- in the Excel column order. Result on real Growatt uploads:
--
--   typed column        | bound to (wrong)              | should bind to
--   ────────────────────┼───────────────────────────────┼─────────────────────
--   currency            | STT (sequence #)              | Đơn vị tiền tệ
--   unit                | Mã ĐVT kiện (package unit)    | Đơn vị tính
--   unit_2              | (nothing)                     | Đơn vị tính 2
--   unit_price          | Đơn giá (raw, pre-FX)          | Đơn giá tính thuế (taxable)
--   total_value         | Trị giá NT (foreign currency) | Tổng trị giá (in VND)
--   line_no             | STT (workbook seq)            | STT hàng (line within declaration)
--
-- Substring matching was removed in commit 338be91 ("Phase 1 parser
-- bug fixes") and ALIASES expanded in 365bfed ("stage A+B"); current
-- parser assigns these correctly. This migration backfills legacy
-- rows from `payload` jsonb (which preserves the raw header→value map
-- verbatim, so we can recover the truth without re-parsing files).
--
-- line_no participates in the PK `(client_id, year, transaction_key,
-- line_no)` and feeds transaction_key construction. We rebuild
-- transaction_key = '{declaration_no}-{cleaned_STT_hàng}' for rows
-- where the new line_no differs. Pre-flight verified 0 PK collisions
-- against current data; the migration aborts loudly if that changes.

alter table hub.bcct_rows disable trigger trg_bcct_row_history;

-- Drop the PK so we can rewrite line_no + transaction_key in a single
-- UPDATE without transient collisions during execution. The pre-flight
-- below verifies the *final* state has no duplicates; the PK is
-- recreated at the end to enforce that.
alter table hub.bcct_rows drop constraint bcct_rows_pkey;

-- ────────────────────────────────────────────────────────────────────────
-- Pre-flight: refuse if rebuilding line_no would collide with an
-- existing row in the same (client_id, year, declaration_no).
-- ────────────────────────────────────────────────────────────────────────
do $$
declare n_collision bigint;
begin
  select count(*) into n_collision from (
    select client_id, year, declaration_no,
           regexp_replace(payload->>'STT hàng', '\.0$', '') as new_line,
           count(*) as n
    from hub.bcct_rows
    where payload->>'STT hàng' is not null
    group by 1,2,3,4 having count(*) > 1
  ) s;
  if n_collision > 0 then
    raise exception
      'Cannot apply 025: % (client_id, year, declaration_no, STT hàng) '
      'tuples are non-unique. Inspect manually before retrying.', n_collision;
  end if;
end$$;

-- ────────────────────────────────────────────────────────────────────────
-- Backfill the 5 mis-claimed text/numeric columns from payload truth.
-- Numeric columns: cast jsonb-string to numeric; null on cast failure.
-- ────────────────────────────────────────────────────────────────────────
update hub.bcct_rows set
  currency    = nullif(payload->>'Đơn vị tiền tệ', ''),
  unit        = nullif(payload->>'Đơn vị tính', ''),
  unit_2      = nullif(payload->>'Đơn vị tính 2', ''),
  unit_price  = case
                  when nullif(payload->>'Đơn giá tính thuế','') is not null
                  then (payload->>'Đơn giá tính thuế')::numeric
                  else unit_price
                end,
  total_value = case
                  when nullif(payload->>'Tổng trị giá','') is not null
                  then (payload->>'Tổng trị giá')::numeric
                  else total_value
                end
where payload <> '{}'::jsonb
  and (
    payload->>'Đơn vị tiền tệ' is not null
    or payload->>'Đơn vị tính' is not null
    or payload->>'Đơn vị tính 2' is not null
    or payload->>'Đơn giá tính thuế' is not null
    or payload->>'Tổng trị giá' is not null
  );

-- ────────────────────────────────────────────────────────────────────────
-- Rebuild line_no + transaction_key from STT hàng for rows where the
-- legacy parser had bound line_no to STT (workbook sequence). Skip rows
-- where line_no already matches STT hàng (small synthetic seeds parsed
-- by the post-fix parser).
-- ────────────────────────────────────────────────────────────────────────
update hub.bcct_rows set
  line_no = regexp_replace(payload->>'STT hàng', '\.0$', ''),
  transaction_key = declaration_no || '-' || regexp_replace(payload->>'STT hàng', '\.0$', '')
where payload->>'STT hàng' is not null
  and declaration_no is not null
  and line_no <> regexp_replace(payload->>'STT hàng', '\.0$', '');

-- ────────────────────────────────────────────────────────────────────────
-- Mirror to bcct_row_history audit table for query consistency. We do
-- NOT touch the jsonb snapshot columns (`old_row` / `new_row`) — those
-- preserve the literal historical payload by design.
-- ────────────────────────────────────────────────────────────────────────
update hub.bcct_row_history h
set
  line_no = b.line_no,
  transaction_key = b.transaction_key
from hub.bcct_rows b
where h.client_id = b.client_id
  and h.year = b.year
  and (
    h.transaction_key like b.declaration_no || '-%'
    or h.transaction_key like b.declaration_no || '.0-%'
  )
  and (h.line_no <> b.line_no or h.transaction_key <> b.transaction_key);

-- Recreate the PK now that all rows are in their final shape.
alter table hub.bcct_rows
  add constraint bcct_rows_pkey
    primary key (client_id, year, transaction_key, line_no);

alter table hub.bcct_rows enable trigger trg_bcct_row_history;
