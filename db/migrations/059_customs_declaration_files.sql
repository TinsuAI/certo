-- 059 — Feature 6 (TKX/TKN management): customs declaration file metadata.
--
-- Tracks per-declaration files (XLS forms, PDF scans) without ingesting
-- their content. Sister-app C/O reads these to attach customs evidence
-- to dossiers. Files themselves live in FileBackend (LocalFS day 1, S3
-- phase 2); this table holds metadata + backend key + linkage to BCCT.
--
-- A declaration may have multiple files (PDF original + XLS data + scan).
-- Uniqueness is on (client_id, declaration_no, direction, sha256) so the
-- same byte-identical upload is a no-op while distinct files for the
-- same declaration coexist.
--
-- Linkage to hub.bcct_rows is via (client_id, declaration_no, direction)
-- composite — no hard FK because legacy data may have files for
-- declarations not present in BCCT (or vice versa). UI surfaces missing
-- files as a soft warning per Feature 6 brief.
--
-- Spec: `.ai/features/2026-05-10-johnson-onboarding/brief.md` Feature 6.

create table hub.customs_declaration_files (
    id                bigserial primary key,
    client_id         text not null
                      references hub.clients(client_id) on delete cascade,
    declaration_no    text not null,
    direction         text not null
                      check (direction in ('import','export')),
    file_kind         text not null
                      check (file_kind in ('xls','pdf','scan','other')),
    backend_key       text not null,
    original_filename text not null,
    declaration_date  date,
    sha256            text not null,
    size_bytes        bigint not null check (size_bytes >= 0),
    uploaded_by       text,
    uploaded_at       timestamptz not null default now(),
    notes             text,
    unique (client_id, declaration_no, direction, sha256)
);

comment on table hub.customs_declaration_files is
  'Per-declaration customs form files (XLS/PDF/scan). Metadata + backend '
  'key only — content lives in FileBackend storage. Linked to bcct_rows '
  'by (client_id, declaration_no, direction) without hard FK to allow '
  'legacy archive imports.';

create index ix_decl_files_lookup
    on hub.customs_declaration_files (client_id, declaration_no, direction);

create index ix_decl_files_client_date
    on hub.customs_declaration_files (client_id, declaration_date desc nulls last);
