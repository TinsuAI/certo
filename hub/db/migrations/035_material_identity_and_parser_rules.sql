-- 035_material_identity_and_parser_rules.sql
--
-- Brief: .ai/features/2026-05-08-configurable-bcct-parsing/brief.md
--
-- Three coupled changes shipped in one transaction:
--   (a) Rename `bcct_rows.product_identity` → `material_identity`
--       (resolver scope expanded to TP/BTP/NVL/CCDC; column name catches up).
--   (b) Drop `bcct_rows.internal_code` column. It was a denormalized
--       cache of a regex parse; replaced by runtime computation via
--       configurable parser rules.
--   (c) Create `hub.client_parser_rules` + history audit table for
--       per-client regex rules editable via web UI (replaces hardcoded
--       Growatt regex in `app/parsers/goods_name.py` +
--       `app/parsers/bcct_adapters/`).

begin;

-- (a) Rename material_identity column + review table.
alter table hub.bcct_rows
  rename column product_identity to material_identity;

alter table hub.bcct_product_identity_review
  rename to bcct_material_identity_review;

alter index hub.idx_bcct_product_identity_review_lookup
  rename to idx_bcct_material_identity_review_lookup;

comment on column hub.bcct_rows.material_identity is
  'Resolved canonical material/product identity per '
  '.ai/features/2026-05-08-configurable-bcct-parsing/brief.md. '
  'Shape: {resolution_status, resolved_code, bom_product_code, '
  'product_kind, candidates[], evidence{}, resolution_source, '
  'confidence, review_status, parser_adapter, parser_version, '
  'line_key{}, declared_internal_code, display_code, ...}. '
  'NULL = not yet resolved (lazy-fill at read time).';

-- (b) Drop legacy internal_code column + index.
drop index if exists hub.idx_bcct_internal;
alter table hub.bcct_rows drop column if exists internal_code;

-- (c) Configurable parser rules.
create table hub.client_parser_rules (
  rule_id           bigserial primary key,
  client_id         text       not null references hub.clients(client_id) on delete cascade,
  output_field      text       not null,
  priority          int        not null,
  pattern           text       not null,
  source_field      text       not null default 'goods_name',
  match_group       int        not null default 1,
  match_action      text       not null default 'capture'
                    check (match_action in ('capture', 'reject')),
  no_match_action   text       not null default 'next_rule'
                    check (no_match_action in ('next_rule', 'return_null')),
  enabled           boolean    not null default true,
  notes             text,
  created_by        text       not null,
  created_at        timestamptz not null default now()
);

comment on table hub.client_parser_rules is
  'Per-client regex rules for runtime field derivation (e.g. '
  'internal_code from goods_name). Edited via web UI by staff with '
  'can_edit_client_technical permission. Patterns are compiled via '
  're2 (linear-time, ReDoS-safe). Soft-disable via enabled=false; '
  'never hard DELETE per project_bom_immutable_principle.md.';

create unique index uq_client_parser_rules_priority
  on hub.client_parser_rules (client_id, output_field, priority)
  where enabled;

create index idx_client_parser_rules_lookup
  on hub.client_parser_rules (client_id, output_field, priority)
  where enabled;

-- History audit (mirrors hub.bcct_row_history mig 013 pattern).
create table hub.client_parser_rules_history (
  history_id    bigserial primary key,
  rule_id       bigint     not null,
  change_kind   text       not null check (change_kind in ('insert', 'update', 'delete')),
  changed_by    text       not null,
  changed_at    timestamptz not null default now(),
  prev_state    jsonb,
  new_state     jsonb
);

create index idx_client_parser_rules_history_lookup
  on hub.client_parser_rules_history (rule_id, changed_at desc);

create or replace function hub.client_parser_rules_audit() returns trigger as $$
begin
  if TG_OP = 'INSERT' then
    insert into hub.client_parser_rules_history
      (rule_id, change_kind, changed_by, new_state)
      values (NEW.rule_id, 'insert', NEW.created_by, to_jsonb(NEW));
  elsif TG_OP = 'UPDATE' then
    insert into hub.client_parser_rules_history
      (rule_id, change_kind, changed_by, prev_state, new_state)
      values (NEW.rule_id, 'update',
              coalesce(current_setting('app.user_id', true), 'system'),
              to_jsonb(OLD), to_jsonb(NEW));
  elsif TG_OP = 'DELETE' then
    insert into hub.client_parser_rules_history
      (rule_id, change_kind, changed_by, prev_state)
      values (OLD.rule_id, 'delete',
              coalesce(current_setting('app.user_id', true), 'system'),
              to_jsonb(OLD));
  end if;
  return null;
end;
$$ language plpgsql security definer;

create trigger trg_client_parser_rules_audit
  after insert or update or delete on hub.client_parser_rules
  for each row execute function hub.client_parser_rules_audit();

commit;
