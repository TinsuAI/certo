-- 045_materials_audit_trigger.sql
--
-- Brief: .ai/features/2026-05-08-catalog-multi-source/brief.md
--
-- Add audit trigger on hub.materials so every UPDATE/DELETE writes an
-- event to hub.material_audit_events. Mirrors the bcct_row_history
-- trigger pattern from mig 013. Honors memory
-- `project_bom_immutable_principle.md`: never DELETE aggregate data,
-- but also track changes so staff can review history.
--
-- Event types:
--   'update'   — column changed (compares old vs new jsonb; skips no-op).
--   'delete'   — row removed (rare; tombstone via status='tombstoned' is
--                preferred per immutable principle).

begin;

create or replace function hub.material_audit_trigger()
  returns trigger
  language plpgsql
  as $$
declare
  actor text;
  old_jsonb jsonb;
  new_jsonb jsonb;
begin
  actor := coalesce(nullif(current_setting('app.user_id', true), ''), 'system');
  old_jsonb := to_jsonb(old);
  if (tg_op = 'UPDATE') then
    new_jsonb := to_jsonb(new);
    if old_jsonb = new_jsonb then
      return null;
    end if;
    insert into hub.material_audit_events
      (client_id, material_code, event_type, actor, payload)
    values
      (old.client_id, old.material_code, 'update', actor,
       jsonb_build_object('old', old_jsonb, 'new', new_jsonb));
    return new;
  elsif (tg_op = 'DELETE') then
    insert into hub.material_audit_events
      (client_id, material_code, event_type, actor, payload)
    values
      (old.client_id, old.material_code, 'delete', actor,
       jsonb_build_object('old', old_jsonb));
    return old;
  end if;
  return null;
end;
$$;

drop trigger if exists trg_material_audit on hub.materials;
create trigger trg_material_audit
  after update or delete on hub.materials
  for each row execute function hub.material_audit_trigger();

commit;
