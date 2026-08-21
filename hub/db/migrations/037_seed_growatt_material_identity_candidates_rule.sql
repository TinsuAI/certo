-- 037_seed_growatt_material_identity_candidates_rule.sql
--
-- Brief: .ai/features/2026-05-08-configurable-bcct-parsing/brief.md
--
-- Final adapter retirement: replaces app/parsers/bcct_adapters/growatt.py
-- (and the bcct_adapters registry as a whole) with a config-rule that
-- the resolver Stage 2 reads via the rule engine. Same regex shape;
-- semantic identifier preserved in `notes` so audit/parser_adapter
-- output stays stable.
--
-- Identity-mode clients (DKE, Johnson, Do Thanh, demo) need NO rules
-- here either: resolver short-circuits Stage 2 when no rules are
-- configured (extract_all_matches over an empty rule list = []).
--
-- Idempotent + safe on fresh DB (see mig 036 docstring for rationale).

begin;

insert into hub.client_parser_rules
  (client_id, output_field, priority, pattern, source_field,
   match_group, match_action, no_match_action, notes, created_by)
select v.client_id, v.output_field, v.priority, v.pattern, v.source_field,
       v.match_group, v.match_action, v.no_match_action, v.notes, v.created_by
from (values
  ('growatt-vn', 'material_identity_candidates', 10,
   '\(([A-Z]{2,}\d{2}\.[A-Za-z0-9._\-]+)\)',
   'goods_name', 1, 'capture', 'next_rule',
   'parenthesized_product_code_exists_in_bom_products',
   'system')
) as v(client_id, output_field, priority, pattern, source_field,
       match_group, match_action, no_match_action, notes, created_by)
where exists (select 1 from hub.clients c where c.client_id = v.client_id)
  and not exists (
    select 1 from hub.client_parser_rules r
    where r.client_id = v.client_id
      and r.output_field = v.output_field
      and r.priority = v.priority
  );

commit;
