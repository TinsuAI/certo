-- Per-client default BOM pick per finished-product code (#14).
--
-- When staff pick a BOM (định mức) artifact for a product, the pick is saved
-- here as the client's default for that product code. Later cases auto-reuse
-- it (read-time fallback below per-case overrides) unless overridden.
--
-- artifact_id pins a specific BOM version on purpose — we do not auto-upgrade
-- to a newer version. See app/bom_default_store.py and
-- .ai/features/2026-06-18-bom-default-batch-flow.md.

create table if not exists co_bom_product_default (
  client_id     text not null,
  product_code  text not null,
  artifact_id   text not null,
  updated_at    timestamptz not null default now(),
  primary key (client_id, product_code)
);
