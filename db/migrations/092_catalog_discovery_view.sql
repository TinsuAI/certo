-- 092_catalog_discovery_view.sql
-- Catalog phase 4 (#34, ADR-0001): discovery becomes a computed relation.
--
-- Three kinds of information, three homes:
--   pending  = derived            → hub.catalog_discovery(client) (set-
--                                   returning SQL function, this file)
--   rejected = manual input       → hub.catalog_rejections (small table)
--   accepted = manual input       → a row in hub.materials (unchanged)
--
-- A function, not a view: the discovery CTEs are referenced repeatedly,
-- so a view materializes the WHOLE corpus per query (measured 4.5s, all
-- clients). The function takes client_id and computes one client
-- (measured ~0.6s Growatt). Still "stored nowhere" per ADR-0001.
--
-- DROP REVIEW (wipe rule — unreplayable columns enumerated):
--   hub.catalog_candidates holds 4,513 rows at drop time (1,207 accepted
--   + 3,306 pending, 0 rejected — verified 2026-07-11). Unreplayable
--   manual input: (decided_by, decided_at, decision_reason) on the
--   decided rows — copied to hub.bom_audit_events below BEFORE the drop,
--   event_type='catalog_candidate_decision'; rejected rows additionally
--   seed hub.catalog_rejections. status/created_at/updated_at ride in
--   the same payload. Every other column (observed_count, sample_text,
--   suggested_category, bom_role, hs_code, uom, origin, counts,
--   material_group, ...) is a pure derivation from bcct_rows /
--   bcct_nb_codes / bom_edges / bom_artifacts / code_mappings and is
--   recomputed live. Pending rows carry no manual input at all.

-- ── 1. Suppression table (reject = "staff said no to this string") ──────

create table if not exists hub.catalog_rejections (
    client_id    text not null references hub.clients(client_id)
                   on delete cascade,
    code         text not null,
    code_kind    text,
    reason       text,
    rejected_by  text not null,
    rejected_at  timestamptz not null default now(),
    primary key (client_id, code)
);

-- ── 2. Preserve decision audit, seed rejections, drop the table ─────────
-- Guarded so the migration is safe on a DB where the table is already
-- gone (re-apply during development).

do $$
begin
    if exists (select 1 from information_schema.tables
                where table_schema = 'hub'
                  and table_name = 'catalog_candidates') then
        insert into hub.bom_audit_events
            (client_id, product_code, event_type, actor, details,
             occurred_at)
        select client_id, code, 'catalog_candidate_decision',
               coalesce(decided_by, 'unknown'),
               jsonb_build_object(
                   'code', code,
                   'code_kind', code_kind,
                   'status', status,
                   'decided_by', decided_by,
                   'decided_at', decided_at,
                   'decision_reason', decision_reason,
                   'migrated_from', 'catalog_candidates',
                   'created_at', created_at,
                   'updated_at', updated_at),
               coalesce(decided_at, now())
          from hub.catalog_candidates
         where status in ('accepted', 'rejected');

        insert into hub.catalog_rejections
            (client_id, code, code_kind, reason, rejected_by, rejected_at)
        select client_id, code, code_kind, decision_reason,
               coalesce(decided_by, 'unknown'), coalesce(decided_at, now())
          from hub.catalog_candidates
         where status = 'rejected'
        on conflict (client_id, code) do nothing;

        drop table hub.catalog_candidates;
    end if;
end $$;

-- ── 3. Re-extract bcct_nb_codes with the widened semantics ──────────────
-- The table now also stores the 'unified' self-link (extracted code equal
-- to the row's customs_code) so discovery can detect the NB==HQ case. The
-- boot backfill (app/main.py lifespan, runs right after migrations)
-- refills every client in this same boot.

delete from hub.bcct_nb_codes;

-- ── 4. Discovery ─────────────────────────────────────────────────────────
-- Mirrors app/parsers/code_extraction.py per-row classification:
--   case 1 dual      → (hq,'hq') + (nb,'nb')...
--   case 2 NB==HQ    → (hq,'unified') only (self-link present; other
--                      extractions on that row are suppressed, as the
--                      parser does)
--   case 3 HQ-only   → (hq, 'hq' if dual client else 'unified')
--   case 4 no HQ     → (nb,'nb')...
-- then collapses multi-kind codes with no cross-string BCCT pairing to
-- 'unified' (ADR-0001), anti-joins hub.materials, and LEFT JOINs
-- rejections so rejected codes stay visible with status='rejected'.

create or replace function hub.catalog_discovery(p_client text)
returns table (
    client_id text,
    code text,
    code_kind text,
    sources text[],
    observed_count bigint,
    import_count bigint,
    export_count bigint,
    decl_count bigint,
    first_seen date,
    last_seen date,
    sample_text text,
    hs_code text,
    hs_alternates_count bigint,
    uom text,
    origin text,
    bom_role text,
    bom_sample text,
    co_occurrence_count bigint,
    suggested_category text,
    multi_direction boolean,
    inferred_production_source text,
    customs_relevance text,
    status text,
    decision_reason text,
    decided_by text,
    decided_at timestamptz
) language sql stable as $$
with params as (
    select p_client as client_id,
           (exists (select 1 from hub.client_parser_rules r
                     where r.client_id = p_client
                       and r.output_field = 'internal_code' and r.enabled)
            or exists (select 1 from hub.code_mappings cm
                        where cm.client_id = p_client)) as dual,
           (select c.customs_code_placeholders from hub.clients c
             where c.client_id = p_client) as placeholders
), bcct_emit as (
    -- HQ side: the declared customs_code (placeholder/empty lines drop).
    select b.transaction_key, b.line_no,
           trim(b.customs_code) as code,
           case
               when exists (select 1 from hub.bcct_nb_codes s
                             where s.client_id = p_client
                               and s.transaction_key = b.transaction_key
                               and s.line_no = b.line_no
                               and s.nb_code = trim(b.customs_code))
                   then 'unified'
               when p.dual then 'hq'
               else 'unified'
           end as code_kind,
           b.direction, b.registration_date, b.declaration_no,
           b.goods_name, b.hs_code,
           coalesce(ua.uom_code,
                    nullif(lower(regexp_replace(trim(b.unit), '\s+', ' ',
                                                'g')), '')) as unit_norm,
           b.origin
      from hub.bcct_rows b
      cross join params p
      left join hub.uom_aliases ua
        on ua.alias_norm = lower(regexp_replace(trim(b.unit), '\s+', ' ', 'g'))
     where b.client_id = p_client
       and nullif(trim(b.customs_code), '') is not null
       and not (trim(b.customs_code) = any(p.placeholders))
    union all
    -- NB side: extracted codes, except on NB==HQ rows (parser case 2
    -- returns only the unified emission and discards siblings).
    select n.transaction_key, n.line_no, n.nb_code, 'nb',
           b.direction, b.registration_date, b.declaration_no,
           b.goods_name, b.hs_code,
           coalesce(ua.uom_code,
                    nullif(lower(regexp_replace(trim(b.unit), '\s+', ' ',
                                                'g')), '')),
           b.origin
      from hub.bcct_nb_codes n
      join hub.bcct_rows b
        on b.client_id = n.client_id
       and b.transaction_key = n.transaction_key
       and b.line_no = n.line_no
      left join hub.uom_aliases ua
        on ua.alias_norm = lower(regexp_replace(trim(b.unit), '\s+', ' ', 'g'))
     where n.client_id = p_client
       and n.nb_code is distinct from trim(b.customs_code)
       and not exists (select 1 from hub.bcct_nb_codes s
                        where s.client_id = n.client_id
                          and s.transaction_key = n.transaction_key
                          and s.line_no = n.line_no
                          and s.nb_code = trim(b.customs_code))
), bcct_stats as (
    select e.code, e.code_kind,
           count(*) as bcct_count,
           count(*) filter (where e.direction = 'import') as import_count,
           count(*) filter (where e.direction = 'export') as export_count,
           count(distinct e.declaration_no) as decl_count,
           min(e.registration_date) as first_seen,
           max(e.registration_date) as last_seen,
           (array_agg(e.goods_name
                      order by e.registration_date desc nulls last,
                               e.goods_name))[1] as sample_text,
           mode() within group (order by e.hs_code) as hs_code,
           greatest(count(distinct e.hs_code) - 1, 0) as hs_alternates_count,
           mode() within group (order by e.unit_norm) as uom,
           mode() within group (order by e.origin) as origin
      from bcct_emit e
     group by e.code, e.code_kind
), cooccur as (
    -- hq↔nb pairings on the same physical row (the parser records
    -- co-occurrence only between the two sides, never nb↔nb siblings).
    select distinct e1.code, e1.code_kind, e2.code as partner
      from bcct_emit e1
      join bcct_emit e2
        on e2.transaction_key = e1.transaction_key
       and e2.line_no = e1.line_no
       and e2.code <> e1.code
     where (e1.code_kind = 'hq' and e2.code_kind = 'nb')
        or (e1.code_kind = 'nb' and e2.code_kind = 'hq')
), co_stats as (
    select c.code, c.code_kind,
           count(distinct c.partner) as co_occurrence_count
      from cooccur c
     group by c.code, c.code_kind
), bom_roles as (
    select r.code,
           case when (select dual from params) then 'nb'
                else 'unified' end as code_kind,
           case
               when r.is_root then 'tp_root'
               when r.parent_n > 0 then 'btp_sx'
               else 'nvl_leaf'
           end as bom_role,
           r.parent_n + r.child_n as bom_edge_count,
           r.bom_uom, r.bom_desc
      from (
          select codes.code,
                 bool_or(codes.is_root) as is_root,
                 sum(codes.parent_n) as parent_n,
                 sum(codes.child_n) as child_n,
                 mode() within group (order by codes.uom) as bom_uom,
                 mode() within group (order by codes.descr) as bom_desc
            from (
                select a.product_code as code,
                       true as is_root, 0 as parent_n, 0 as child_n,
                       null::text as uom, null::text as descr
                  from hub.bom_artifacts a
                 where a.client_id = p_client and a.tombstoned_at is null
                union all
                select e.parent_code, false, 1, 0, null, null
                  from hub.bom_edges e
                  join hub.bom_artifacts a on a.artifact_id = e.artifact_id
                 where a.client_id = p_client and a.tombstoned_at is null
                union all
                select e.child_code, false, 0, 1, nullif(trim(e.uom), ''),
                       nullif(e.payload->>'description', '')
                  from hub.bom_edges e
                  join hub.bom_artifacts a on a.artifact_id = e.artifact_id
                 where a.client_id = p_client and a.tombstoned_at is null
            ) codes
           where codes.code is not null and codes.code <> ''
           group by codes.code
      ) r
), bqd_codes as (
    select trim(cm.customs_code) as code,
           case when trim(cm.customs_code) = trim(cm.internal_code)
                then 'unified' else 'hq' end as code_kind
      from hub.code_mappings cm
     where cm.client_id = p_client
       and nullif(trim(cm.customs_code), '') is not null
       and nullif(trim(cm.internal_code), '') is not null
    union
    select trim(cm.internal_code),
           case when trim(cm.customs_code) = trim(cm.internal_code)
                then 'unified' else 'nb' end
      from hub.code_mappings cm
     where cm.client_id = p_client
       and nullif(trim(cm.customs_code), '') is not null
       and nullif(trim(cm.internal_code), '') is not null
), stream_rows as (
    select bs.code, bs.code_kind,
           true as f_bcct, false as f_bom, false as f_bqd,
           bs.bcct_count as observed_count,
           bs.import_count, bs.export_count, bs.decl_count,
           bs.first_seen, bs.last_seen, bs.sample_text,
           bs.hs_code, bs.hs_alternates_count, bs.uom, bs.origin,
           null::text as bom_role, null::text as bom_sample,
           coalesce(co.co_occurrence_count, 0) as co_occurrence_count
      from bcct_stats bs
      left join co_stats co
        on co.code = bs.code and co.code_kind = bs.code_kind
    union all
    select br.code, br.code_kind,
           false, true, false,
           br.bom_edge_count,
           0, 0, 0, null, null, br.bom_desc, null, 0, br.bom_uom, null,
           br.bom_role,
           case br.bom_role
               when 'tp_root' then 'TP root trong BOM'
               when 'btp_sx' then 'Parent giữa cây (BTP_SX)'
               when 'nvl_leaf' then 'Leaf trong BOM'
           end,
           0
      from bom_roles br
    union all
    select bq.code, bq.code_kind,
           false, false, true,
           0, 0, 0, 0, null, null, null, null, 0, null, null,
           null, null, 0
      from bqd_codes bq
), combined as (
    -- Stage 1: merge the three streams per (code, kind).
    select s.code, s.code_kind,
           bool_or(s.f_bcct) as f_bcct, bool_or(s.f_bom) as f_bom,
           bool_or(s.f_bqd) as f_bqd,
           sum(s.observed_count) as observed_count,
           sum(s.import_count) as import_count,
           sum(s.export_count) as export_count,
           sum(s.decl_count) as decl_count,
           min(s.first_seen) as first_seen,
           max(s.last_seen) as last_seen,
           coalesce(max(s.sample_text) filter (where s.f_bcct),
                    max(s.sample_text)) as sample_text,
           max(s.hs_code) as hs_code,
           max(s.hs_alternates_count) as hs_alternates_count,
           coalesce(max(s.uom) filter (where s.f_bcct),
                    max(s.uom)) as uom,
           max(s.origin) as origin,
           max(s.bom_role) as bom_role,
           max(s.bom_sample) as bom_sample,
           sum(s.co_occurrence_count) as co_occurrence_count
      from stream_rows s
     group by s.code, s.code_kind
), affiliated as (
    select distinct c.code from cooccur c
), merged as (
    -- Stage 2: collapse — multi-kind codes with no cross-string BCCT
    -- pairing merge into one 'unified' row (ADR-0001: whole-corpus
    -- property, so it lives here, not in an ingest hook).
    select k.code, k.final_kind as code_kind,
           array_remove(array[
               case when bool_or(k.f_bcct) then 'bcct' end,
               case when bool_or(k.f_bom) then 'bom' end,
               case when bool_or(k.f_bqd) then 'bqd' end
           ], null) as sources,
           sum(k.observed_count) as observed_count,
           sum(k.import_count) as import_count,
           sum(k.export_count) as export_count,
           sum(k.decl_count) as decl_count,
           min(k.first_seen) as first_seen,
           max(k.last_seen) as last_seen,
           coalesce(max(k.sample_text) filter (where k.f_bcct),
                    max(k.sample_text)) as sample_text,
           max(k.hs_code) as hs_code,
           max(k.hs_alternates_count) as hs_alternates_count,
           coalesce(max(k.uom) filter (where k.f_bcct),
                    max(k.uom)) as uom,
           max(k.origin) as origin,
           max(k.bom_role) as bom_role,
           max(k.bom_sample) as bom_sample,
           sum(k.co_occurrence_count) as co_occurrence_count
      from (
          select c.*,
                 case
                     when count(*) over (partition by c.code) > 1
                          and a.code is null then 'unified'
                     else c.code_kind
                 end as final_kind
            from combined c
            left join affiliated a on a.code = c.code
      ) k
     group by k.code, k.final_kind
)
select p_client,
       m.code,
       m.code_kind,
       m.sources,
       m.observed_count,
       m.import_count,
       m.export_count,
       m.decl_count,
       m.first_seen,
       m.last_seen,
       m.sample_text,
       m.hs_code,
       m.hs_alternates_count,
       m.uom,
       m.origin,
       m.bom_role,
       m.bom_sample,
       m.co_occurrence_count,
       case
           when m.import_count > 0 then 'nvl'
           when m.export_count > 0 then 'tp'
           when m.bom_role = 'tp_root' then 'tp'
           when m.bom_role = 'btp_sx' then 'btp_sx'
       end as suggested_category,
       (m.import_count > 0 and m.export_count > 0) as multi_direction,
       case
           when m.import_count > 0 and m.export_count > 0 then 'mixed'
           when m.import_count > 0 then 'nk'
           when m.export_count > 0 then 'sx'
       end as inferred_production_source,
       case when po.material_code is not null
            then 'excluded_non_material' end as customs_relevance,
       case when r.code is not null then 'rejected'
            else 'pending' end as status,
       r.reason,
       r.rejected_by,
       r.rejected_at
  from merged m
  left join hub.catalog_rejections r
    on r.client_id = p_client and r.code = m.code
  left join hub.v_placeholder_only_codes po
    on po.client_id = p_client and po.material_code = m.code
 where not exists (
       select 1 from hub.materials mat
        where mat.client_id = p_client
          and mat.material_code = m.code)
$$;
