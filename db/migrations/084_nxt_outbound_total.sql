-- Most ERP NXT exports (EZSOFT/3TSoft, MISA, SAP MB5B) report a single lumped
-- "Xuất" total; only the regulatory Mẫu 15 form / system template breaks it into
-- 4 buckets. Add a canonical outbound_total so closing_implied works for both:
-- adapters that have the 4-way split also set outbound_total = sum(buckets);
-- lumped sources set outbound_total only and leave the buckets null.
alter table hub.nxt_lines
    add column if not exists outbound_total numeric;
