-- 014_catalog_provenance.sql
-- Multi-source provenance for hub.materials. Tracks where each catalog row
-- came from: HQ-registered (canonical), seen-on-BCCT-declaration (operational
-- reality, may not be HQ-registered yet), or user-added (manual entry).
--
-- Shape (per row):
--   { "registered_with_hq": {"first_seen": tz, "source_upload_id": text},
--     "seen_in_bcct":       {"first_seen": tz, "last_seen": tz, "decl_count": int},
--     "user_added":         {"first_seen": tz, "added_by": text} }
-- Each top-level key is optional. Presence = signal.

alter table hub.materials
  add column if not exists provenance jsonb not null default '{}'::jsonb;

-- GIN-on-jsonb-path-keys index helps the common filter queries:
--   SELECT … WHERE provenance ? 'seen_in_bcct' AND NOT provenance ? 'registered_with_hq'
create index if not exists idx_materials_provenance_keys
  on hub.materials using gin (provenance jsonb_path_ops);

-- Backfill step 1: every existing materials row was inserted via catalog
-- upload or seed (the only paths that write to materials before this
-- migration). Mark them all registered_with_hq with created_at as the
-- first-seen sentinel. source_upload_id=null because the legacy rows
-- weren't linked to file_uploads.upload_id. Catalog upload route owns
-- future writes here and will set source_upload_id explicitly.
update hub.materials
set provenance = provenance ||
    jsonb_build_object(
      'registered_with_hq',
      jsonb_build_object(
        'first_seen', to_char(created_at, 'YYYY-MM-DD'),
        'source_upload_id', null
      )
    )
where not (provenance ? 'registered_with_hq');

-- Backfill step 2: for every materials row whose customs_code matches
-- existing bcct_rows, additionally mark seen_in_bcct from the historical
-- aggregate. Rows can have BOTH registered_with_hq AND seen_in_bcct —
-- that's the canonical happy path (registered AND showing up on declarations).
update hub.materials m
set provenance = m.provenance ||
    jsonb_build_object(
      'seen_in_bcct',
      jsonb_build_object(
        'first_seen', to_char(b.first_seen, 'YYYY-MM-DD'),
        'last_seen',  to_char(b.last_seen,  'YYYY-MM-DD'),
        'decl_count', b.decl_count
      )
    )
from (
  select client_id, customs_code,
         min(registration_date) as first_seen,
         max(registration_date) as last_seen,
         count(distinct declaration_no) as decl_count
  from hub.bcct_rows
  where customs_code is not null and customs_code <> ''
  group by client_id, customs_code
) b
where m.client_id = b.client_id
  and m.customs_code = b.customs_code
  and not (m.provenance ? 'seen_in_bcct');
