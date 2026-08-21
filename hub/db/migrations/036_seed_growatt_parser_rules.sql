-- 036_seed_growatt_parser_rules.sql
--
-- Brief: .ai/features/2026-05-08-configurable-bcct-parsing/brief.md (D2 + seed)
--
-- Port the hardcoded Growatt regex (was in app/parsers/goods_name.py — now
-- deleted) to client_parser_rules rows for `growatt-vn`. After this migration
-- runs, runtime computation of internal_code via compute_internal_code()
-- yields per-row values matching pre-mig-035 behavior on the happy path,
-- AND fixes the F1 anchor bug (666 export rows that previously returned
-- BIENTAN.xx now correctly return PV01.xxxx).
--
-- Rules are ordered by priority (asc = earlier). First match wins.
-- All patterns compile under re2 (linear time, no backreferences).
--
--   priority 10: reject `.#&...` shape — equipment with no internal code.
--   priority 20: capture `\d{3}\.\w+` — agency NVL codes (940.x, 960.x).
--   priority 30: capture `[A-Z]{2,}\d{2}\.\w+` — agency TP codes
--                (PV01.xxxx, SD00.xxxx, TV03.xxxx).
--   priority 40: capture `[A-Z]\d{3}\.\w+` — single-letter prefix
--                (B700.xxxx PCBA shape).
--   priority 50: capture `\d{2}[A-Z]\.\w+` — `00G.xxxx` shape.
--
-- Idempotent + safe on fresh DB:
--   - `where exists (select … from hub.clients …)` skips when growatt-vn
--     is not yet seeded (CI fresh DB applies migrations before app
--     lifespan seeds clients). app/seed.py::seed_parser_rules_if_empty
--     re-runs the same logic from Python after client seed.
--   - `where not exists (… same rule …)` makes re-runs no-ops.
--
-- F1 anchor `\)\s*$` is GONE. Patterns scan parens anywhere — fixes the
-- export-row suffix-blocking bug. F3 (leading-prefix fallback) is GONE
-- per brief D10: rows that don't match any rule return None, not
-- conflate with customs_code.

begin;

insert into hub.client_parser_rules
  (client_id, output_field, priority, pattern, source_field,
   match_group, match_action, no_match_action, notes, created_by)
select v.client_id, v.output_field, v.priority, v.pattern, v.source_field,
       v.match_group, v.match_action, v.no_match_action, v.notes, v.created_by
from (values
  ('growatt-vn', 'internal_code', 10,
   '^\.\s*#&', 'goods_name', 1, 'reject', 'next_rule',
   'Equipment marker: goods_name starts with `.#&` → no internal code.',
   'system'),
  ('growatt-vn', 'internal_code', 20,
   '\((\d{3}\.[\w\-]+)\)', 'goods_name', 1, 'capture', 'next_rule',
   'Paren-extracted NVL code (e.g. `(960.0062100)`).',
   'system'),
  ('growatt-vn', 'internal_code', 30,
   '\(([A-Z]{2,}\d{2}\.[\w\-]+)\)', 'goods_name', 1, 'capture', 'next_rule',
   'Paren-extracted TP code (e.g. `(PV01.0117500)`, `(SD00.0010600)`).',
   'system'),
  ('growatt-vn', 'internal_code', 40,
   '\(([A-Z]\d{3}\.[\w\-]+)\)', 'goods_name', 1, 'capture', 'next_rule',
   'Paren-extracted PCBA shape (e.g. `(B700.0242002)`).',
   'system'),
  ('growatt-vn', 'internal_code', 50,
   '\((\d{2}[A-Z]\.[\w\-]+)\)', 'goods_name', 1, 'capture', 'next_rule',
   'Paren-extracted alpha-suffix shape (e.g. `(00G.0101600)`).',
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
