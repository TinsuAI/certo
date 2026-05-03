-- 024: Strip trailing `.0` from text-of-number BCCT key fields.
--
-- openpyxl returns numeric cells as float, so historical uploads stored
-- declaration_no = '308449399330.0' and line_no = '133.0', which then
-- propagated into transaction_key = '308449399330.0-133.0'. The parser
-- has been patched (`app/parsers/bcct.py:_cell_str`) so new uploads land
-- clean; this migration cleans the legacy data.
--
-- Why also rebuild transaction_key: it's a primary-key column built as
-- '{declaration_no}-{line_no}'. Without rebuilding, re-uploads of the
-- same Excel would create duplicate rows because the cleaned key would
-- not match the polluted PK already in the table.
--
-- Trigger trg_bcct_row_history is suppressed for the duration so we
-- don't write thousands of "system migration cleaned key" audit rows;
-- the prior row state is already preserved by `bcct_row_history` rows
-- written when the polluted data was first applied.

alter table hub.bcct_rows disable trigger trg_bcct_row_history;

-- ────────────────────────────────────────────────────────────────────────
-- Pre-flight: confirm no PK collision will occur. With current data all
-- rows are uniformly `.0`-suffixed (no clean rows exist), so collision
-- count is expected to be 0.
-- ────────────────────────────────────────────────────────────────────────
do $$
declare n_collision bigint;
begin
  with cleaned as (
    select client_id, year,
           regexp_replace(declaration_no, '\.0$', '') as new_decl,
           regexp_replace(line_no, '\.0$', '') as new_line
    from hub.bcct_rows
    where declaration_no like '%.0' or line_no like '%.0'
  )
  select count(*) into n_collision
  from cleaned c
  join hub.bcct_rows b
    on b.client_id = c.client_id and b.year = c.year
   and b.declaration_no = c.new_decl and b.line_no = c.new_line
  where b.declaration_no not like '%.0' and b.line_no not like '%.0';
  if n_collision > 0 then
    raise exception
      'Cannot apply 024: % rows would collide on PK after cleaning. '
      'Hand-resolve the collisions before retrying.', n_collision;
  end if;
end$$;

-- ────────────────────────────────────────────────────────────────────────
-- Strip `.0` from declaration_no and line_no, rebuild transaction_key.
-- transaction_key historically follows two shapes:
--   1. '{declaration_no}-{line_no}'           (when declaration_no present)
--   2. '{customs_code}-{token_hex(4)}'        (legacy fallback when missing)
-- The cleaning only applies to shape 1; shape 2 is left untouched.
-- ────────────────────────────────────────────────────────────────────────
update hub.bcct_rows
set
  declaration_no = regexp_replace(declaration_no, '\.0$', ''),
  line_no = regexp_replace(line_no, '\.0$', ''),
  transaction_key = case
    when declaration_no is not null then
      regexp_replace(declaration_no, '\.0$', '') || '-' || regexp_replace(line_no, '\.0$', '')
    else transaction_key
  end
where declaration_no like '%.0' or line_no like '%.0';

-- ────────────────────────────────────────────────────────────────────────
-- bcct_row_history mirrors transaction_key + line_no for audit lookups.
-- Clean it for query consistency. We do NOT rewrite the jsonb snapshot
-- columns (`old_row` / `new_row`) — those preserve the literal historical
-- payload by design.
-- ────────────────────────────────────────────────────────────────────────
update hub.bcct_row_history
set
  line_no = regexp_replace(line_no, '\.0$', ''),
  transaction_key = regexp_replace(
                      regexp_replace(transaction_key, '^([0-9]+)\.0-', '\1-'),
                      '\.0$', '')
where transaction_key like '%.0%' or line_no like '%.0';

alter table hub.bcct_rows enable trigger trg_bcct_row_history;
