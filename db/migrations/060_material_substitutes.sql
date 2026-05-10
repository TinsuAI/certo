-- 060 — Feature 4 MVP (NVL substitutes, no embedding yet).
--
-- Substitute candidate edges: client_confirmed (P1), same_hs (P4),
-- same_customs_diff_internal (P2 — toggleable per client), trigram (P5),
-- prefix_rule (P3 — deferred, schema-ready), embedding (P5 — deferred
-- until pgvector available), manual_user.
--
-- Per-client toggle in `hub.clients.substitute_rules` controls which
-- auto rules run during refresh — Johnson is identity-mode so P2
-- (same_customs_diff_internal) is meaningless and turned off.
--
-- Embedding column + pgvector live in a future migration once the
-- pgvector extension is installed on the box.
--
-- Spec: `.ai/features/2026-05-10-johnson-onboarding/brief.md` Feature 4.

create extension if not exists pg_trgm;

alter table hub.clients
    add column if not exists substitute_rules jsonb not null default
        '{"p1_client_confirmed":true,
          "p2_same_customs_diff_internal":true,
          "p3_prefix_rule":false,
          "p4_same_hs":true,
          "p5_trigram":true,
          "p5_embedding":false}'::jsonb;

-- Johnson identity-mode: P2 is meaningless (customs_code = internal_code).
update hub.clients
   set substitute_rules =
       substitute_rules || '{"p2_same_customs_diff_internal": false}'::jsonb
 where client_id = 'johnson-vn';

create table hub.material_substitutes (
    id              bigserial primary key,
    client_id       text not null
                    references hub.clients(client_id) on delete cascade,
    material_a_code text not null,
    material_b_code text not null,
    source          text not null
                    check (source in (
                        'client_confirmed',
                        'same_customs_diff_internal',
                        'same_hs',
                        'prefix_rule',
                        'trigram',
                        'embedding',
                        'manual_user'
                    )),
    score           numeric(5,4),                -- 0..1; null for client_confirmed
    confirmed_by    text,                        -- user_id
    confirmed_at    timestamptz,
    rejected_by     text,                        -- user_id
    rejected_at     timestamptz,
    created_at      timestamptz not null default now(),
    check (material_a_code <> material_b_code),
    unique (client_id, material_a_code, material_b_code, source)
);

comment on table hub.material_substitutes is
  'Directed substitute edges (a → b). Multiple sources can co-exist for '
  'the same pair; UI dedupes + ranks by combined score formula. Source '
  ''
  'CASCADE on hub.clients delete.';

create index ix_subs_lookup
    on hub.material_substitutes (client_id, material_a_code)
    where rejected_at is null;

create index ix_subs_pair_active
    on hub.material_substitutes (client_id, material_a_code, material_b_code)
    where rejected_at is null;

-- Trigram GIN index for fast similar-code lookup at refresh time.
create index ix_materials_code_trgm
    on hub.materials using gin (material_code gin_trgm_ops);
