-- Allow the NXT + inventory upload flows to cache confirmed column mappings in
-- hub.parser_mappings (the LLM/staff mapping-page cache). Additive: existing
-- modules unchanged. The original module CHECK has an auto-generated name, so
-- find + drop it by definition before re-adding the widened check.
do $$
declare cname text;
begin
  select conname into cname from pg_constraint
   where conrelid = 'hub.parser_mappings'::regclass and contype = 'c'
     and pg_get_constraintdef(oid) like '%module = ANY%';
  if cname is not null then
    execute format('alter table hub.parser_mappings drop constraint %I', cname);
  end if;
end $$;
alter table hub.parser_mappings add constraint parser_mappings_module_check
  check (module in ('bcct','catalog','bqd','bom','nxt','inventory'));
