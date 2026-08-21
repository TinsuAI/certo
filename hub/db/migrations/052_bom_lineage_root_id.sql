-- 052 — bom_artifacts.lineage_root_id (logical phiên bản identity)
--
-- Per glossary: "Phiên bản BOM" (logical) = tuple
-- (client, product, variant, lineage_root_id, case_id). The lineage
-- root is the artifact_id at the top of the parent_artifact_id chain.
-- A standard upload yields 3 artifacts (raw_graph + shallow + full_flat)
-- with shared lineage_root, representing 1 logical phiên bản.
--
-- Adds:
-- - `lineage_root_id` column (NOT NULL after backfill).
-- - BEFORE INSERT trigger that:
--     parent_artifact_id IS NULL → lineage_root_id := NEW.artifact_id.
--     parent_artifact_id NOT NULL → lineage_root_id := parent's
--       lineage_root_id (inherit).
-- - Recursive CTE backfill for existing rows.
-- - Index for list-page group-by query.

alter table hub.bom_artifacts
  add column if not exists lineage_root_id text;

-- Backfill via recursive CTE: walk parent chain to root, propagate
-- root's artifact_id to every descendant.
with recursive chain as (
  select artifact_id, parent_artifact_id, artifact_id as root_id
    from hub.bom_artifacts
   where parent_artifact_id is null
   union all
  select c.artifact_id, c.parent_artifact_id, ch.root_id
    from hub.bom_artifacts c
    join chain ch on c.parent_artifact_id = ch.artifact_id
)
update hub.bom_artifacts a
   set lineage_root_id = ch.root_id
  from chain ch
 where a.artifact_id = ch.artifact_id
   and a.lineage_root_id is null;

-- Defensive: any orphan with parent_artifact_id pointing to a deleted
-- artifact won't have hit the recursive CTE. Treat them as their own
-- root (best-effort recovery; lineage chain broken anyway).
update hub.bom_artifacts
   set lineage_root_id = artifact_id
 where lineage_root_id is null;

alter table hub.bom_artifacts
  alter column lineage_root_id set not null;

-- Trigger: maintain invariant on every insert.
create or replace function hub.bom_artifacts_set_lineage_root()
returns trigger as $$
begin
  if NEW.lineage_root_id is not null then
    -- Caller-supplied root wins (e.g., backfill scripts, tests with
    -- explicit lineage). Trust the caller.
    return NEW;
  end if;
  if NEW.parent_artifact_id is null then
    NEW.lineage_root_id := NEW.artifact_id;
  else
    select lineage_root_id into NEW.lineage_root_id
      from hub.bom_artifacts
     where artifact_id = NEW.parent_artifact_id;
    if NEW.lineage_root_id is null then
      -- Parent missing or has NULL root (data integrity issue) →
      -- fall back to self so insert succeeds + invariant holds.
      NEW.lineage_root_id := NEW.artifact_id;
    end if;
  end if;
  return NEW;
end;
$$ language plpgsql;

drop trigger if exists trg_bom_artifacts_set_lineage_root on hub.bom_artifacts;
create trigger trg_bom_artifacts_set_lineage_root
  before insert on hub.bom_artifacts
  for each row
  execute function hub.bom_artifacts_set_lineage_root();

-- Index supporting list_products_with_bom group-by query.
create index if not exists idx_bom_artifacts_lineage_root
  on hub.bom_artifacts (client_id, product_code, lineage_root_id)
  where tombstoned_at is null;
