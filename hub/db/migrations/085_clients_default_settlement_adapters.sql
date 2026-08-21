-- Per-client default adapter binding for the NXT + inventory tiers (mirrors
-- mig 081 default_bom_adapter). Null = auto-detect (parse_with_fallback). A
-- non-null value pins one registered adapter as the upload-form default; an
-- unregistered value degrades to 'auto' at read time so removing an adapter
-- never breaks the upload form.
alter table hub.clients add column if not exists default_nxt_adapter text;
alter table hub.clients add column if not exists default_inventory_adapter text;
