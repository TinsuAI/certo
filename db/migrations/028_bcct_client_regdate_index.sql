-- 028: index for the BCCT list ORDER BY.
--
-- The list view sorts by (registration_date desc nulls last,
-- declaration_no, line_no) filtered by client_id. Existing indexes
-- (idx_bcct_internal/customs/declaration/...) all start with
-- (client_id, year, ...) so they can't drive the order-by — explain
-- showed a Seq Scan over hub.bcct_rows for growatt-vn (3185 rows
-- scanned, 1941 filtered) before the join.
--
-- This index covers the WHERE+ORDER BY directly. Also speeds up the
-- pagination total-count when filtered by client_id.

create index if not exists idx_bcct_client_regdate
  on hub.bcct_rows (
    client_id,
    registration_date desc nulls last,
    declaration_no,
    line_no
  );
