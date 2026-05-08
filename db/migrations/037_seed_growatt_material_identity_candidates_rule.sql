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

begin;

insert into hub.client_parser_rules
  (client_id, output_field, priority, pattern, source_field,
   match_group, match_action, no_match_action, notes, created_by)
values
  ('growatt-vn', 'material_identity_candidates', 10,
   '\(([A-Z]{2,}\d{2}\.[A-Za-z0-9._\-]+)\)',
   'goods_name', 1, 'capture', 'next_rule',
   'parenthesized_product_code_exists_in_bom_products',
   'system');

commit;
