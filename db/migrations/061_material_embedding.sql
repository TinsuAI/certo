-- 061 — Feature 4 P5b: pgvector embedding pipeline.
--
-- Adds embedding storage + tracking columns to `hub.materials` and a
-- per-client config JSONB to `hub.clients`. Vector dimension defaults
-- to 1536 to match OpenAI text-embedding-3-small (the default model).
-- HNSW index for cosine ANN search at query time.
--
-- Embedding-text composition:
--   {name}. HS={hs_code}. UoM={unit}. Origin={country_origin}.
-- (Auditable via embedding_text_hash; re-embed when config changes.)
--
-- Spec: `.ai/features/2026-05-10-johnson-onboarding/brief.md` Feature 4 P5b.

create extension if not exists vector;

alter table hub.materials
    add column if not exists description_embedding vector(1536),
    add column if not exists embedding_text_hash    text,
    add column if not exists embedding_model        text,
    add column if not exists embedding_at           timestamptz;

-- HNSW index on the vector column for fast cosine ANN search.
-- Partial index: only rows with embedding populated. Default HNSW
-- params (m=16, ef_construction=64) are fine for ≤100K materials.
create index if not exists ix_materials_embedding_hnsw
    on hub.materials using hnsw (description_embedding vector_cosine_ops)
    where description_embedding is not null;

-- Per-client embedding config override. NULL = use global default from
-- app_settings. JSONB merges over default at runtime.
alter table hub.clients
    add column if not exists embedding_config jsonb;

-- Sanity: app_settings keys for embedding global defaults will be set
-- by `app.settings_store` on first read; no INSERT here so callers
-- can self-default safely.
comment on column hub.materials.description_embedding is
  'Vector embedding of {name, hs_code, unit, country_origin} per the '
  'embedding text template. Re-derived when embedding_text_hash mismatches '
  'current state or embedding_model differs from current config.';
comment on column hub.materials.embedding_text_hash is
  'sha256 of generated text used for the stored vector. Mismatch with '
  'recomputed text triggers re-embed (post_ingest_hook + nightly batch).';
comment on column hub.clients.embedding_config is
  'Per-client overrides on top of global defaults from app_settings. '
  'NULL = use global. Merge semantics: shallow JSONB || at read time.';
