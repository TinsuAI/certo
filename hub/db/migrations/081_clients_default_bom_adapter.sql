-- Per-client default BOM adapter binding (B.0). Null = auto-detect
-- (parse_with_fallback, detect-ranked) — the current behaviour. A non-null
-- value pins one registered adapter as the upload-form default for this client.
-- Stored as a free text adapter name; an unregistered value degrades to 'auto'
-- at read time (app/stores/adapter_binding.py), so removing an adapter never
-- breaks the upload form.

alter table hub.clients
    add column if not exists default_bom_adapter text;
