-- 091_bcct_nb_codes_and_paren_aware_views.sql
-- Catalog phase 3 (#33, closes BACKLOG A.5). Three parts:
--
--   1. hub.bcct_nb_codes — persisted BCCT paren extraction. The one
--      non-columnar catalog fact (brief Decision 4): NB codes extracted
--      from goods_name by client_parser_rules. SQL cannot run the re2
--      extraction (mig 050), so Python writes this table
--      (app/stores/bcct_nb_codes.py) and SQL joins it. A deliberate
--      persisted derivation — exception to no-derived-in-source, with a
--      delete-and-rebuild invalidation policy (measured ~0.9s Growatt):
--      rebuilt on BCCT apply and on any parser-rule edit; backfilled at
--      app boot when empty (fresh DBs, this deploy).
--   2. v_material_roles, 6th definition — BCCT signals now flow through
--      a links CTE (customs_code ∪ bcct_nb_codes), so paren-only NB
--      codes (Growatt-shape) finally get observations. Replaces the
--      request-time Python workaround app/stores/material_observations.py.
--   3. v_material_classification — machinery marking: a code observed
--      ONLY on placeholder lines (hub.clients.customs_code_placeholders,
--      mig 090; fixed-asset E13 rows) is 'excluded_non_material'. The
--      branch sits FIRST: those codes now have has_imports=true via the
--      rebuilt roles view and must not fall through to 'declarable'.
--      Codes that also appear on any production line — or as a
--      customs_code themselves — are never marked.

-- ── 1. Link table ────────────────────────────────────────────────────────

create table if not exists hub.bcct_nb_codes (
    client_id        text not null references hub.clients(client_id)
                       on delete cascade,
    transaction_key  text not null,
    line_no          text not null,
    nb_code          text not null,
    primary key (client_id, transaction_key, line_no, nb_code)
);

create index if not exists idx_bcct_nb_codes_code
    on hub.bcct_nb_codes (client_id, nb_code);

-- Supports the view joins from links back to rows (PK includes year, so
-- (client_id, transaction_key, line_no) lookups had no index).
create index if not exists idx_bcct_txn_line
    on hub.bcct_rows (client_id, transaction_key, line_no);

-- ── 2. v_material_roles — paren-aware BCCT signals ──────────────────────

create or replace view hub.v_material_roles as
with bcct_links as (
    -- Every (row, code) pairing: the declared customs_code plus each
    -- paren-extracted NB code. UNION (not ALL) so a unified row where
    -- the same string is both sides yields one link.
    select client_id, transaction_key, line_no,
           customs_code as material_code
      from hub.bcct_rows
     where customs_code is not null
    union
    select client_id, transaction_key, line_no, nb_code
      from hub.bcct_nb_codes
), bcct_signals as (
    select l.client_id,
           l.material_code,
           bool_or(b.direction = 'import') as has_imports,
           bool_or(b.direction = 'export') as has_exports,
           bool_or(b.direction = 'import'
                   and b.declaration_type in
                       ('E11','E15','E21','E23','E31','E33')) as has_nvl_import,
           count(distinct b.declaration_no) as observed_count,
           min(b.registration_date) as observed_first_at,
           max(b.registration_date) as observed_last_at,
           array_agg(distinct b.direction)
               filter (where b.direction is not null) as observed_directions
      from bcct_links l
      join hub.bcct_rows b
        on b.client_id = l.client_id
       and b.transaction_key = l.transaction_key
       and b.line_no = l.line_no
     group by l.client_id, l.material_code
), bom_consumed as (
    select a.client_id, e.child_code as material_code
      from hub.bom_edges e
      join hub.bom_artifacts a on a.artifact_id = e.artifact_id
     where a.tombstoned_at is null
     group by a.client_id, e.child_code
), bom_owned as (
    select client_id, product_code as material_code
      from hub.bom_artifacts
     where tombstoned_at is null
     group by client_id, product_code
), atoms as (
    select m.client_id,
           m.material_code,
           m.category as declared_kind,
           coalesce(bs.has_imports, false) as has_imports,
           coalesce(bs.has_exports, false) as has_exports,
           coalesce(bs.has_nvl_import, false) as has_nvl_import,
           bc.material_code is not null as is_consumed_in_bom,
           bo.material_code is not null as has_own_bom,
           coalesce(bs.observed_count, 0) as observed_count,
           bs.observed_first_at,
           bs.observed_last_at,
           coalesce(bs.observed_directions, '{}'::text[]) as observed_directions
      from hub.materials m
      left join bcct_signals bs
        on bs.client_id = m.client_id and bs.material_code = m.material_code
      left join bom_consumed bc
        on bc.client_id = m.client_id and bc.material_code = m.material_code
      left join bom_owned bo
        on bo.client_id = m.client_id and bo.material_code = m.material_code
)
select client_id,
       material_code,
       declared_kind,
       has_imports,
       has_exports,
       has_nvl_import,
       is_consumed_in_bom,
       has_own_bom,
       array_remove(array[
           case when has_exports then 'tp' end,
           case when is_consumed_in_bom and has_own_bom then 'btp_sx' end,
           case when has_imports and is_consumed_in_bom and has_own_bom
                then 'btp_nm' end,
           case when has_nvl_import and not has_own_bom then 'nvl' end
       ], null) as observed_roles,
       (case when has_exports then 1 else 0 end
        + case when is_consumed_in_bom and has_own_bom then 1 else 0 end
        + case when has_imports and is_consumed_in_bom and has_own_bom
               then 1 else 0 end
        + case when has_nvl_import and not has_own_bom then 1 else 0 end
       ) >= 2 as is_multi_role,
       (case when has_exports then 1 else 0 end
        + case when is_consumed_in_bom and has_own_bom then 1 else 0 end
        + case when has_imports and is_consumed_in_bom and has_own_bom
               then 1 else 0 end
        + case when has_nvl_import and not has_own_bom then 1 else 0 end
       ) > 0
       and declared_kind in ('tp','btp_sx','nvl','ccdc')
       and (declared_kind = 'ccdc'
            or not (   (has_exports and declared_kind = 'tp')
                    or (is_consumed_in_bom and has_own_bom
                        and declared_kind = 'btp_sx')
                    or (has_nvl_import and not has_own_bom
                        and declared_kind = 'nvl')))
       as declared_observed_conflict,
       observed_count,
       observed_first_at,
       observed_last_at,
       observed_directions
  from atoms a;

-- ── 3. v_material_classification — machinery marking ────────────────────

create or replace view hub.v_material_classification as
with placeholder_only as (
    -- Codes whose every BCCT appearance is a placeholder line (fixed
    -- assets) and that never appear as a customs_code themselves.
    -- Growatt: forklift/rack part numbers (210 of 218 paren-extracted
    -- fixed-asset codes; the 8 shared with production lines fail
    -- bool_and and stay unmarked).
    select n.client_id, n.nb_code as material_code
      from hub.bcct_nb_codes n
      join hub.bcct_rows b
        on b.client_id = n.client_id
       and b.transaction_key = n.transaction_key
       and b.line_no = n.line_no
      join hub.clients c on c.client_id = n.client_id
     group by n.client_id, n.nb_code
    having bool_and(coalesce(
               nullif(trim(b.customs_code), '')
                   = any(c.customs_code_placeholders),
               false))
       and not exists (
               select 1 from hub.bcct_rows b2
               where b2.client_id = n.client_id
                 and b2.customs_code = n.nb_code)
)
select m.client_id,
       m.material_code,
       m.material_group,
       map.item_category,
       map.is_declarable,
       case
           when po.material_code is not null then 'excluded_non_material'
           when m.material_group is null then null
           when coalesce(vmr.has_imports, false) then 'declarable'
           when map.material_group is null then 'review'
           when map.is_declarable = false then 'excluded_non_material'
           else 'declarable_unmatched'
       end as customs_relevance
  from hub.materials m
  left join hub.client_material_group_map map
    on map.client_id = m.client_id
   and map.material_group = m.material_group
  left join hub.v_material_roles vmr
    on vmr.client_id = m.client_id
   and vmr.material_code = m.material_code
  left join placeholder_only po
    on po.client_id = m.client_id
   and po.material_code = m.material_code;
