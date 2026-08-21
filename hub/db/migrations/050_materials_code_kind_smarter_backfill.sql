-- 050_materials_code_kind_smarter_backfill.sql
--
-- Brief: .ai/features/2026-05-09-ma-cho-duyet/brief.md
--
-- Mig 047's backfill was pattern-only (regex match → 'nb'). This missed
-- the "unified by data" case: a code that's listed in code_mappings as a
-- self-loop (internal_code == customs_code) is genuinely unified for
-- that material — the agency declares NB == HQ for that SKU, even
-- though the client overall has a dual-system (other materials DO have
-- different NB/HQ). Pattern alone is misleading.
--
-- New backfill priority (overrides mig 047 result):
-- 1. Self-loop in code_mappings (internal_code = customs_code) → 'unified'
-- 2. Appears as paren-extract in BCCT goods_name AND customs_code in same
--    row matches → 'unified' (NB == HQ overlap)
-- 3. Distinct from paired NB anywhere → 'nb' / 'hq' as before
-- 4. Default → keep current value

begin;

-- Rule 1: code_mappings self-loop → 'unified'
update hub.materials m set code_kind = 'unified'
where exists (
  select 1 from hub.code_mappings cm
  where cm.client_id = m.client_id
    and cm.internal_code = m.material_code
    and cm.customs_code = m.material_code
);

-- Rule 2: BCCT row had customs_code = paren-extracted (NB == HQ overlap)
-- detected by: any BCCT row has customs_code = m.material_code AND
-- the goods_name contains '(<material_code>)'. (This is approximate but
-- robust — re-extracting via parser rules in SQL would require plpython.)
update hub.materials m set code_kind = 'unified'
where m.code_kind <> 'unified'
  and exists (
    select 1 from hub.bcct_rows b
    where b.client_id = m.client_id
      and b.customs_code = m.material_code
      and b.goods_name like '%(' || m.material_code || ')%'
  );

commit;
