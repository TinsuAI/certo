-- 032_bcct_product_identity.sql
--
-- BCCT BOM product identity resolver (CO API request 2026-05-07).
-- Brief: .ai/features/2026-05-07-bcct-product-identity/brief.md
--
-- Two additions:
--   (a) hub.bcct_rows.product_identity jsonb         (D1)
--   (b) hub.bcct_product_identity_review table       (D4)
--
-- Both additive. NULL `product_identity` means "not yet resolved";
-- the read endpoints lazy-resolve when include_product_identity=true.

begin;

alter table hub.bcct_rows
  add column if not exists product_identity jsonb;

comment on column hub.bcct_rows.product_identity is
  'Resolved BOM product identity per .ai/features/2026-05-07-bcct-product-identity. '
  'Shape: {resolution_status, bom_product_code, candidates[], evidence{}, '
  'resolution_source, confidence, review_status, parser_adapter, parser_version, '
  'line_key{}, ...}. NULL = not yet resolved (lazy-fill at read time).';

create table if not exists hub.bcct_product_identity_review (
  client_id        text       not null references hub.clients(client_id) on delete cascade,
  declaration_no   text       not null,
  line_no          text       not null,
  transaction_key  text       not null,
  bom_product_code text,                                   -- null = explicit "no resolution"
  status           text       not null check (status in ('reviewed', 'rejected')),
  reviewed_by      text       not null,
  reviewed_at      timestamptz not null default now(),
  notes            text,
  primary key (client_id, transaction_key, line_no, reviewed_at)
);

comment on table hub.bcct_product_identity_review is
  'Append-only audit of operator-reviewed BCCT->BOM product identity '
  'mappings. Resolver picks latest by (client_id, transaction_key, line_no) '
  'order by reviewed_at desc. Write API deferred to a follow-up brief; '
  'this migration ships the read-side schema only.';

create index if not exists idx_bcct_product_identity_review_lookup
  on hub.bcct_product_identity_review (client_id, transaction_key, line_no, reviewed_at desc);

commit;
