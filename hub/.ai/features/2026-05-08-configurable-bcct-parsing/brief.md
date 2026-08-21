# Feature: Configurable per-client BCCT parsing + identity cleanup

**Date:** 2026-05-08.
**Owner:** Data Hub.
**Consumers affected:** CO (`barry-CO-main`), BCQT (future).
**Predecessor brief:** `.ai/features/2026-05-07-bcct-product-identity/brief.md` (mig 032 shipped).
**Pulls in:** "Modular BOM ingest adapters" item 5 from BACKLOG (now in-flight).

## Why

Three converging issues, all rooted in "wrong place for derivation":

1. **Naming**: `bcct_rows.product_identity` jsonb (mig 032) misnames after
   the in-brief amendment expanded scope to TP/BTP/NVL/CCDC. NVL +
   CCDC are not "products" in Vietnamese manufacturing semantics.
   Resolver target table is `hub.materials` (master registry).
   → Rename to `material_identity`.

2. **Cached regex over a pure function**: `bcct_rows.internal_code`
   (mig 005) is denormalized cache of regex parse over `goods_name`
   keyed by `(client.code_resolution_mode, goods_name, customs_code)`
   — all already in the row. Persisting adds drift risk + backfill
   burden, information gain zero.
   - Two bugs in `app/parsers/goods_name.py` regex F1: (a) anchor
     `\)\s*$` too strict (fails on Growatt export shape
     `BIENTAN.17#&...(PV01.0117500)#&VN` — 666/666 export rows wrong),
     (b) disjunction too narrow (misses `B700.x`, `00G.x` shapes —
     ~14 import rows wrong). F3 fallback aggressively returns leading
     prefix (= customs_code), producing 75 borderline rows.
   - R4 of predecessor brief misread these wrong values as legitimate
     "agency ERP code" semantics; that decision needs correction.
   → Drop column, compute runtime.

3. **Hardcoded per-client logic**: regex for Growatt lives in
   `goods_name.py::growatt_parse_internal_code` + `bcct_adapters/growatt.py`.
   New agency = code deploy. F1 anchor bug is a symptom of
   single-author-per-regex paradigm — staff who own agency data have
   no path to fix the regex without engineering. Patching the regex
   in code (as originally proposed) just delays the architectural
   fix.
   → Move regex rules to `hub.client_parser_rules` table, edit via
   web UI, evaluate at runtime. Hardcoded paths deleted.

Pre-production status (no agency live yet) makes this the right
window for these breaking changes. Sister apps (CO, BCQT) update
their consumers in the same release cycle.

## Scope

**In scope:**

Schema + data:
- Mig 035 (single transaction):
  - `bcct_rows.product_identity` → `material_identity`.
  - `bcct_product_identity_review` → `bcct_material_identity_review`.
  - Drop `bcct_rows.internal_code` + `idx_bcct_internal`.
  - Create `hub.client_parser_rules` + `client_parser_rules_history`
    + AFTER UPDATE/DELETE trigger (mirrors `bcct_row_history` mig 013
    pattern, per memory `project_bom_immutable_principle.md`).
- Seed migration data: port hardcoded Growatt regex → 3-4 rule rows
  for `client_id='growatt-vn'`, `output_field='internal_code'`.

Backend:
- Module rename `app/resolvers/bcct_product_identity.py` →
  `bcct_material_identity.py`. Function `resolve_product_identity` →
  `resolve_material_identity`.
- New module `app/parsers/client_parser_rules.py`:
  - `evaluate_rules(client_id, output_field, row, ctx) -> str | None`
  - `_load_rules_cached(...)` — per-request memoization keyed by
    `(client_id, output_field, parser_rules_version)`.
  - `_compile_pattern_cached(...)` — process-wide LRU.
- Helper `app/parsers/derivations.py::compute_internal_code(row, client, ctx)`:
  - For `client.code_resolution_mode='identity'` → return `customs_code`
    (no rule eval).
  - Otherwise → `evaluate_rules(client.client_id, 'internal_code', row, ctx)`.
- Delete: `app/parsers/goods_name.py` regex (`growatt_parse_internal_code`,
  `internal_code_parser_for`, `_PAT_F1/F3/F4`).
  Delete: `app/parsers/bcct_adapters/growatt.py` + `identity.py`
  + `__init__.py` adapter registry (replaced by config rules + the
  identity-mode short-circuit).
- Wire helper into 3 callsites: resolver, BCCT API serializer
  (`app/routes/api.py`), UI route handler (`app/routes/bcct.py`).
  Eager-derivation in `_apply_bcct_rows` deleted.

API:
- Param renames (hard cut, no alias): `include_product_identity` →
  `include_material_identity`, `product_identity_candidate_limit` →
  `material_identity_candidate_limit`.
- Response field: remove `internal_code` from item shape entirely.
  Legacy "what was filed" is `material_identity.declared_internal_code`;
  canonical resolved form is `material_identity.display_code`.
- New CRUD endpoints under `/v1/hub/clients/{client_id}/parser-rules`:
  GET (list), POST (create), PATCH (update), DELETE (soft-disable
  via `enabled=false`, never hard delete per memory
  `project_bom_immutable_principle.md`), POST `/test` (preview rule
  output against sample input — does not persist), GET
  `/{rule_id}/history` (audit log).

UI:
- Drop `internal_code` column from BCCT list + history pages. Drop
  from sort options + free-text search clause.
- Render `display_code` from `material_identity` in column where
  internal_code previously appeared.
- New page `/clients/<client_id>/parser-rules`:
  - List rules grouped by `output_field`, ordered by `priority`.
  - Add/edit form (pattern, source_field, priority, match_group,
    match_action, no_match_action, notes, enabled).
  - **Test panel** (mandatory): paste sample value(s) for `source_field`,
    preview which rule matches + capture output. Three modes:
    - **Single sample**: one paste, full per-rule trace.
    - **Recent rows**: last 50 BCCT rows for this client → preview
      output + diff vs current cached value.
    - **Coverage**: run all rules over last 1k rows, show
      resolved/null/changed counts.

Security:
- ReDoS protection: use `google-re2` (Python binding `pyre2` or
  `google-re2` — pick at TDD; both linear-time, no backreferences).
  Reject patterns with backreferences at save time.
- Auth: re-use existing `auth.can_edit_client_technical(user, client_id)`
  from `app/routes/clients.py` (same gate as `code_resolution_mode`
  edit).
- Rate limit on `/parser-rules/test` endpoint to prevent
  CPU-saturation DoS via repeated test calls. 60/min/user single
  sample, 10/min/user coverage.

Sister apps:
- CO sister-app note: API changes + consumer migration steps for
  `data_hub_client.py:415,426,438,538`, `bom_service.py:266`,
  `main.py:1794` (these read `internal_code` directly from row dicts).
- BCQT sister-app note: forward-looking, explains rule infra so
  BCQT settlement integration plans accordingly.

Docs:
- Update `docs/API_CONTRACT.md`: param renames + response field
  removal + new parser-rules endpoints.
- R4 amendment in predecessor brief
  `.ai/features/2026-05-07-bcct-product-identity/brief.md`
  (chronological in-place, `## Amendment 2026-05-08` header — not
  top-banner, per memory `feedback_bom_vocab.md` immutable history
  principle).
- New section in `AGENTS.md`: "Per-client parsing rules" — pointer to
  config UI + ReDoS rule-of-thumb + rule-version audit lookup.

**Out of scope (explicit):**

- BOM adapter side of "Modular BOM ingest adapters" (BACKLOG items
  1-4: file-shape detection, `derive_btp_shallows.py`, adapter
  registry extraction, Phase 3 readiness). Same `client_parser_rules`
  table SHAPE serves both, but BOM-specific work — file detection
  heuristics, post-ingest hooks, adapter selection — remains in
  BACKLOG.
- Manual override per-row for `internal_code`. If staff need to
  correct individual rows after parsing, that's a separate
  override-table feature. Not a current use case.
- Code mappings table (`hub.code_mappings`) has its own
  `internal_code` column — different concept (agency-side
  mapping registry), out of scope.
- Generic rule DSL beyond regex (e.g., XPath, JSONPath, function
  composition). v1 is regex-only; broader DSL deferred unless agency
  requirement surfaces.
- Bulk re-resolve / backfill of historical rows. Runtime compute
  means no persisted value to backfill. Memory `project_reingest_pending.md`
  wipe-and-reingest queue can drop the BCCT half (still applicable to
  BOM-side cleanup).
- Migration `down.sql` rollback. Pre-production = forward-only.

## Decisions

**D1. Migration 035 — single transaction, schema-only.**

```sql
begin;

-- Rename material_identity column + review table.
alter table hub.bcct_rows rename column product_identity to material_identity;
alter table hub.bcct_product_identity_review rename to bcct_material_identity_review;
alter index hub.idx_bcct_product_identity_review_lookup
  rename to idx_bcct_material_identity_review_lookup;

-- Drop legacy internal_code column + index.
drop index if exists hub.idx_bcct_internal;
alter table hub.bcct_rows drop column if exists internal_code;

-- Create configurable parser rules.
create table hub.client_parser_rules (
  rule_id           bigserial primary key,
  client_id         text not null references hub.clients(client_id) on delete cascade,
  output_field      text not null,
  priority          int  not null,
  pattern           text not null,
  source_field      text not null default 'goods_name',
  match_group       int  not null default 1,
  match_action      text not null default 'capture'
                    check (match_action in ('capture','reject')),
  no_match_action   text not null default 'next_rule'
                    check (no_match_action in ('next_rule','return_null')),
  enabled           boolean not null default true,
  notes             text,
  created_by        text not null,
  created_at        timestamptz not null default now()
);
create unique index uq_client_parser_rules_priority
  on hub.client_parser_rules (client_id, output_field, priority)
  where enabled;
create index idx_client_parser_rules_lookup
  on hub.client_parser_rules (client_id, output_field, priority)
  where enabled;

-- History audit (mirrors bcct_row_history mig 013).
create table hub.client_parser_rules_history (
  history_id    bigserial primary key,
  rule_id       bigint     not null,
  change_kind   text       not null check (change_kind in ('insert','update','delete')),
  changed_by    text       not null,
  changed_at    timestamptz not null default now(),
  prev_state    jsonb,
  new_state     jsonb
);
create index on hub.client_parser_rules_history (rule_id, changed_at desc);

-- Trigger: auto-write history on every change.
create or replace function hub.client_parser_rules_audit() returns trigger as $$
begin
  if TG_OP = 'INSERT' then
    insert into hub.client_parser_rules_history
      (rule_id, change_kind, changed_by, new_state)
      values (NEW.rule_id, 'insert', NEW.created_by, to_jsonb(NEW));
  elsif TG_OP = 'UPDATE' then
    insert into hub.client_parser_rules_history
      (rule_id, change_kind, changed_by, prev_state, new_state)
      values (NEW.rule_id, 'update',
              coalesce(current_setting('app.user_id', true), 'system'),
              to_jsonb(OLD), to_jsonb(NEW));
  elsif TG_OP = 'DELETE' then
    insert into hub.client_parser_rules_history
      (rule_id, change_kind, changed_by, prev_state)
      values (OLD.rule_id, 'delete',
              coalesce(current_setting('app.user_id', true), 'system'),
              to_jsonb(OLD));
  end if;
  return null;
end;
$$ language plpgsql security definer;

create trigger trg_client_parser_rules_audit
  after insert or update or delete on hub.client_parser_rules
  for each row execute function hub.client_parser_rules_audit();

commit;
```

Postgres `RENAME COLUMN`, `RENAME TABLE`, `DROP COLUMN` are all
metadata-only; pre-prod = no live load to contend lock. No backfill.

**D2. Rule data model — minimal but sufficient.**

```
rule_id          bigserial PK
client_id        FK clients
output_field     'internal_code' (v1); future: any derivable
                 row attribute the resolver/serializer layer needs
priority         int, ascending; unique per (client, output_field, enabled)
pattern          regex string; re2-compatible
source_field     'goods_name' | 'customs_code' | 'declaration_no' | ...
                 (any column in the BCCT row dict)
match_group      int, default 1
match_action     'capture' | 'reject'
no_match_action  'next_rule' | 'return_null'
enabled          boolean — soft-disable; never hard DELETE
notes            free text; staff context
```

**Engine semantics**:
- Load rules `where enabled=true and client_id=? and output_field=?
  order by priority asc`.
- For each rule:
  - Run `pattern.search(row[source_field])`.
  - If match: `match_action='capture'` → return `match.group(match_group)`;
    `match_action='reject'` → return `None`, stop.
  - If no match: `no_match_action='next_rule'` → continue;
    `no_match_action='return_null'` → return `None`, stop.
- After all rules: return `None`.

**Identity mode short-circuit**: helper checks
`client.code_resolution_mode == 'identity'` first; if so, return
`customs_code` without loading rules. No rule rows needed for
identity clients.

**Rejected alternatives**:
- Higher-level DSL (paren-extractor, prefix-extractor primitives) —
  too restrictive for the long tail of agency formats; regex is the
  lingua franca staff understand.
- Single jsonb config column on `clients` — loses history audit
  granularity; already have a precedent (`parser_mappings`,
  `bcct_row_history`) for separate table + history pattern.
- Adapter Python classes — what we're explicitly removing.

**D3. ReDoS protection — `google-re2`.**

Use Google's RE2 library (linear-time matching, no
backreferences/lookahead support). Python bindings: `google-re2`
(official, recommended) or `pyre2` (community). Pick at TDD; both
expose `re`-compatible API.

Save-time validation:
- Compile pattern with `re2.compile(pattern)`. If it throws
  (unsupported feature), reject with 400.
- Reject patterns matching unsafe shapes via static check (paranoid
  belt-and-suspenders): patterns containing `(?:.*)+`, `(.+)+`, etc.
- Maximum pattern length 500 chars.

Runtime: re2's linear-time guarantee means no per-execution timeout
needed.

**D4. Pattern cache strategy.**

Two layers:
- **Process-wide LRU** (size 256): keyed by `pattern_string` →
  `compiled_pattern`. Cheap to share across clients.
- **Per-request rule list memoization**: keyed by
  `(client_id, output_field, parser_rules_version)` → ordered list of
  compiled rules. Single load per (client_id, output_field) per
  request.

Cache invalidation on rule edit: bump a server-wide
`parser_rules_version` counter (atomic int, lives in module global
or Redis later); cache key includes counter, so any edit
invalidates all cached lookups process-wide. Cheap because edits
are rare (maybe daily, not per-request).

**D5. UI test panel — non-negotiable.**

The test panel is the only thing standing between staff and
shipping broken regex. Three modes:

1. **Single sample mode** — paste a value, see per-rule trace:
   - Rule N: pattern "..." → match? yes/no → capture group = "..."
     → action: capture (output) | reject (null) | next_rule.
   - Final output value.
2. **Recent rows mode** — pick last 50 rows from
   `hub.bcct_rows where client_id=? order by indexed_at desc`. Show:
   - row id (transaction_key + line_no).
   - source_field value (truncated).
   - current output (computed via existing rules).
   - new output (if rules changed).
   - diff highlighted.
3. **Coverage mode** — scan last 1k rows, show:
   - Total: N rows.
   - Resolved (non-null): X rows.
   - Null: Y rows.
   - Changed vs current: Z rows (only meaningful when previewing
     edit).

Test panel is read-only; never persists results.

**D6. API surface for parser-rules CRUD.**

```
GET    /v1/hub/clients/{client_id}/parser-rules
       → list rules; optional ?output_field= filter; ?include_disabled=true
POST   /v1/hub/clients/{client_id}/parser-rules
       → create; body {output_field, priority, pattern, source_field?,
         match_group?, match_action?, no_match_action?, notes?}
PATCH  /v1/hub/clients/{client_id}/parser-rules/{rule_id}
       → update; body any subset of editable fields
DELETE /v1/hub/clients/{client_id}/parser-rules/{rule_id}
       → soft-disable (sets enabled=false); never DELETE the row
POST   /v1/hub/clients/{client_id}/parser-rules/test
       → body {output_field, sample_input | recent_n | coverage_n,
         pattern_overrides?}; response: per-rule trace + final output
GET    /v1/hub/clients/{client_id}/parser-rules/{rule_id}/history
       → audit log; paginated
```

All write endpoints require `can_edit_client_technical(user, client_id)`.

**D7. Module + function rename mirrors column.**

- `app/resolvers/bcct_product_identity.py` →
  `app/resolvers/bcct_material_identity.py`.
- `resolve_product_identity` → `resolve_material_identity`.
- Internal helpers (`_kind_for`, `_no_match`, `_resolved`,
  `ResolverContext`, etc.) keep their names.
- Tests under `tests/test_bcct_product_identity*.py` rename to
  `test_bcct_material_identity*.py`.

Imports: grep before estimating final count. Rough check on existing
state (counted via the predecessor-brief implementation) suggests
~40-60 references across app/ + tests/.

**D8. API response shape — hard cut, breaking.**

- `internal_code` removed from `/v1/hub/bcct/*` response items at
  every level.
- `material_identity.declared_internal_code` is the legacy "what
  was filed" view (NULL when client is identity-mode without filed
  internal code).
- `material_identity.display_code` is the canonical "best display"
  (resolved code if any, fallback `customs_code`).
- Old API params return `400 invalid_parameter` with hint pointing
  to new name. No silent alias, no 308 redirect.

**Pre-production rationale**: no agency live, sister apps coordinate
in same release cycle. Hard cut is intentional — soft alias would
just delay the consumer migration we want to force now.

**D9. CO consumer migration — coordinated, not deferred.**

`barry-CO-main` reads `internal_code` directly from row dicts at:
- `app/data_hub_client.py:415,426,438,538` — row normalizer.
- `app/bom_service.py:266` — BOM lookup.
- `app/main.py:1794` — display field.

These all need to switch to `material_identity.declared_internal_code`
or `material_identity.display_code` (depending on which semantic the
caller wanted). Sister-app note (D-docs) details the mapping. Land
CO PR same release window.

**D10. F3 fallback semantics — explicit decision (was Critic blocker B3).**

Predecessor F3 path returned the leading prefix (= customs_code) for
rows with no parens. This conflated "no internal code recoverable"
with "internal_code identity to customs". Configurable rules make
this explicit:
- For `growatt-vn`, no rule will produce that fallback. Rules in seed
  cover (a) paren-extracted code, (b) dot-prefix reject.
- Rows that don't match any rule → `None`. Config of `growatt-vn`
  rules treats the 75 borderline rows as `None` (not customs-identity).
- Identity-mode clients (DKE, Johnson, Do Thanh, Demo) unaffected:
  short-circuits before rule evaluation.

This is a behavior change from current state: 75 import rows that
today display `internal_code = customs_code` will display `None`.
Acceptable per discussion — those rows had no real internal code,
just the regex falling back to prefix.

**D11. Predecessor brief amendment — chronological, not top-banner.**

Append `## Amendment 2026-05-08 — material_identity rename, drop internal_code, configurable rules` section AT THE BOTTOM of
`.ai/features/2026-05-07-bcct-product-identity/brief.md`. Include:
- Correction of R4 wording: `bcct_rows.internal_code` was *buggy*
  (F1 anchor + disjunction errors), not "agency ERP code semantics".
  The 666 wrong export rows were not data shape but parse error.
- Reference to this brief for the resolution.

Per memory `feedback_bom_vocab.md`, past briefs are immutable
history. Top-banner approach rejected (Critic notable #8).

**D12. Memory update — after ship, not now.**

Defer memory writes (`internal_code` semantics, `material_identity`
naming, `client_parser_rules` infra) until PR merges and behavior
verifies on dev. Memory should reflect shipped state, not in-flight
state.

## Risks

**R1. CO consumer break — intentional, coordinated.**
CO reads `internal_code` directly at 6 places. Hard cut breaks them.
*Pre-production status* makes this the right call: force coordinated
migration in same release cycle rather than carrying alias debt.
**Mitigation:** D9 sister-app note + CO PR coordinated. CI gate:
don't deploy Data Hub mig 035 until CO consumer PR merges.

**R2. Staff writes broken regex.**
Staff with `can_edit_client_technical` permission can author rules
that break ingestion or break consumer queries. Failure modes:
catastrophic regex (ReDoS — covered by D3), wrong capture group,
wrong priority order, pattern that matches nothing, pattern that
matches too much.
**Mitigation:** D5 test panel — staff MUST preview against recent
rows + coverage mode before saving. Save endpoint can require a
`preview_token` that proves user ran preview within last 5 minutes
against current pattern. (Belt-and-suspenders; consider deferring
the token check until first real-world misconfig.)

**R3. ReDoS via re library mistake.**
If any developer accidentally imports `re` instead of `re2` in the
rule engine path, ReDoS regression. **Mitigation:** lint rule
forbidding `import re` in rule-engine modules; CI check. Helper
imports `re2 as re` aliased per convention.

**R4. Performance regression on large reads.**
Lazy-fill on full export endpoint (BCQT settlement, ~23k rows)
applies rule engine per row. Estimated cost (3 rules + cached
compile + memoized rule load): ~5-10 µs/row × 23k = 115-230 ms.
Borderline acceptable for cold pull; warm cache should drop to <50
ms.
**Mitigation:** D4 caching. If still slow, add
`?include_material_identity=false` skip-resolve path for bulk
exports.

**R5. Identity-mode regression.**
Helper short-circuit on `code_resolution_mode='identity'` must be
preserved exactly. If short-circuit drops or rule engine runs
identity-mode by mistake, every identity client breaks.
**Mitigation:** unit test asserting identity-mode bypasses rules for
DKE + Johnson + Do Thanh + Demo (existing identity clients).
Functional test asserting `internal_code = customs_code` in helper
output for these clients with NO rule rows in DB.

**R6. Test surface explosion.**
Mig 032 tests reference `product_identity` everywhere; rename touches
~40-60 sites. New rule engine adds ~25-35 tests. Total ~65-95 test
changes/additions.
**Mitigation:** ordered implementation — schema first, rename
second, rule engine third. Each step its own commit; tests pass
between commits.

**R7. Rule audit trail vs `app.user_id` GUC.**
Trigger reads `app.user_id` GUC for `changed_by`. Existing pattern
(`bcct_row_history`) uses same GUC; needs `set_config('app.user_id',
'<user>', false)` per-connection. Per BACKLOG `/rev cross-cut`,
SESSION-scoped GUC fine while pool returns clean connections.
**Mitigation:** match existing `bcct_row_history` pattern verbatim;
`set_config(..., false)` is the project default.

**R8. UI test panel — staff usability.**
Test panel exposing regex internals is power-user UX. Domain staff
(non-developer) may struggle.
**Mitigation:** UI design defer to TDD round; ship simplest version
first (single-sample mode), iterate based on staff feedback. Notes
field on each rule lets staff document intent in Vietnamese.

**R9. Migration rollback.**
Mig 035 has no `down.sql`. Rolling back rename + drop column
requires manual SQL and would lose any rule data added.
*Pre-production rationale*: forward-only acceptable; if mig 035
breaks dev, drop schema + replay.

## Open Questions

**Q1. Soft-disable vs hard-delete for rules.**
Memory `project_bom_immutable_principle.md` says never hard-DELETE
aggregate data. Rules feel like aggregate data (audit history
matters). Soft-disable via `enabled=false` is in D2.
**Recommendation: soft-disable only**; UI hides disabled by default;
audit history preserves prior versions. Confirm.

**Q2. Multiple rule sets per client (versioning beyond audit)?**
Use case: staff drafts new rule set, tests against fixture, then
swaps in atomically. Today design has one active set at any time;
edits go live immediately.
**Recommendation: defer.** v1 is one live set. If staff need
draft-then-swap, add `rule_set_id` later. YAGNI.

**Q3. `output_field` enum — open or constrained?**
v1 needs only `'internal_code'`. Constraining to a CHECK enum
prevents typos; opening it keeps future flexibility (e.g.,
`'product_kind'` later).
**Recommendation: open string** (no CHECK); validate against a
hardcoded list in the API CRUD layer (easier to extend than
migration). Confirm.

**Q4. Test panel "recent rows" — what counts as "recent"?**
50 most recent by `indexed_at`? Per `direction` (export vs import)?
Last calendar quarter?
**Recommendation: 50 most recent overall, allow staff filter by
direction in UI. Defer fancier slicing to v2.**

**Q5. `client_parser_rules_test` rate limit — strict or loose?**
Test endpoint runs regex against up to 1k rows in coverage mode →
expensive. Limit to prevent CPU-saturation DoS by adversarial
power-user.
**Recommendation: 60/min/user for single-sample mode, 10/min/user
for coverage mode** (more expensive). Tune at TDD if too tight.

**Q6. Folder rename for predecessor brief.**
Folder `.ai/features/2026-05-07-bcct-product-identity/` carries the
old name.
**Recommendation: keep.** Memory `feedback_bom_vocab.md` immutable
history precedent. Future readers find via this brief's "Predecessor
brief" link.

## Implementation Plan

**Order (single PR, multiple commits for review tractability):**

1. **Mig 035** — schema-only. Apply, run `pytest` smoke (existing
   tests pass since rename is additive re-pointing; engine not yet
   wired).
2. **Module + function rename** — `bcct_product_identity` →
   `bcct_material_identity`. `grep -rn` first to enumerate all import
   sites. Tests rename + pass.
3. **Rule engine core** — `app/parsers/client_parser_rules.py`:
   `evaluate_rules`, `_load_rules_cached`, `_compile_pattern_cached`.
   TDD: unit tests for engine edge cases (no rules, all reject,
   capture wrong group, ReDoS pattern rejected at save).
4. **Helper + 3 callsites** — `compute_internal_code` helper +
   identity-mode short-circuit; wire into resolver, API serializer,
   UI route handler. Delete old eager-derivation in
   `_apply_bcct_rows`. Delete `goods_name.py` regex + adapter
   classes.
5. **API CRUD** — parser-rules endpoints. Auth gate. Test endpoint
   with rate limit.
6. **Seed Growatt rules** — port hardcoded regex to 3-4 rule rows
   in mig 036 (data-only, separate from schema mig 035 for cleanliness).
   TDD against 666 export + 22k import golden corpus to derive
   correct patterns.
7. **UI page + test panel** — `/clients/<id>/parser-rules`. Three
   test modes (single, recent, coverage). UI smoke against dev DB.
8. **API response shape** — drop `internal_code` field; rename query
   params with 400-on-old-name. Provider tests updated.
9. **UI BCCT pages** — drop column from list/history, drop search,
   drop sort. Render `display_code`.
10. **Sister-app note** —
    `.ai/sister-app-notes/2026-05-08-material-identity-and-parser-rules.md`
    for CO + BCQT.
11. **API_CONTRACT.md** + AGENTS.md docs update.
12. **Predecessor brief amendment** — D11.
13. **STATUS.md update** — mark migration done + summary.

**Estimate: 16-23h end-to-end.**
- Mig 035 + 036: 1.5h.
- Module rename + import sweep: 1.5h.
- Rule engine core + tests: 3h.
- Helper + callsite wiring + delete legacy: 2h.
- API CRUD + tests: 2h.
- Seed Growatt rules + golden tests: 2h.
- UI page + test panel + smoke: 4-5h.
- Response shape + UI BCCT page changes: 1.5h.
- Sister-app note + docs + brief amendment: 1.5h.
- Real-data smoke + integration: 1-2h.

## Test Plan

**Unit (rule engine):**
- Empty rule set → returns None.
- Single capture rule, match → returns capture group.
- Single capture rule, no match → returns None.
- Reject rule matches → returns None and stops.
- `no_match_action='return_null'` → stops at first non-match.
- Rules in priority order; lower priority first.
- Disabled rule skipped.
- ReDoS pattern rejected at save.
- Backreference pattern rejected at save (re2 limitation).
- Pattern length >500 rejected at save.
- Cache invalidation: bump version → next call re-loads.

**Integration (Growatt corpus):**
- Export `BIENTAN.17#&...(PV01.0117500)#&VN`
  → `internal_code = 'PV01.0117500'`.
- Import `DOV#&...(960.0000200)`
  → `internal_code = '960.0000200'`.
- Import `PCBA#&...(B700.0242002)` (former bug-shape)
  → `internal_code = 'B700.0242002'`.
- Import `25-GRTAPPS600#&Máy kiểm tra...` (no parens)
  → `internal_code = None` (was: '25-GRTAPPS600').
- Import `.#&...` → `internal_code = None`.
- Identity-mode (DKE) row → `internal_code = customs_code`.

**API contract:**
- `?include_material_identity=true` returns field.
- `?include_product_identity=true` returns 400 with rename hint.
- Response item has no top-level `internal_code` key.
- `material_identity.declared_internal_code` populated for filed
  internal-code clients.
- `material_identity.display_code` falls back to customs_code.

**CRUD:**
- Create rule → audit history row with `change_kind='insert'`.
- Update rule → audit row `update` with prev + new state.
- Delete rule → soft-disable, audit row `delete` with prev state;
  row still visible with `?include_disabled=true`.
- Test endpoint: single sample → per-rule trace + final output.
- Test endpoint: coverage → resolved/null/changed counts.
- Auth: non-tech user 403 on POST/PATCH/DELETE.
- Rate limit: 61st test call in 60s → 429.

**Schema:**
- `\d hub.bcct_rows` shows `material_identity` column, no
  `internal_code`.
- `\d hub.bcct_material_identity_review` exists; old name "does not
  exist".
- `\d hub.client_parser_rules` + history table exist.
- Trigger fires on rule INSERT/UPDATE/DELETE.

**UI smoke:**
- BCCT list page renders for Growatt without errors; no
  `internal_code` column visible.
- Parser-rules page lists Growatt's 3-4 seeded rules.
- Test panel single-sample mode: paste
  `BIENTAN.17#&...(PV01.0117500)#&VN` → output `PV01.0117500`.
- Test panel coverage: returns counts for last 1k rows.
- Auth gate: non-technical user does not see "Edit" button on
  rule rows.
- Identity-mode client (DKE) has empty parser-rules page (no rules
  needed); UI shows "Identity mode — no rules required" notice.

**Real-data smoke:**
- `DATA_HUB_REAL_DATA_DIR=/tmp/dh_real_data uv run pytest -q` green.
- Manually verify: `select count(*) from hub.bcct_rows where
  client_id='growatt-vn' and material_identity->>'resolved_code' is
  not null` → expect ~21.5k+ resolved (was: ~21k via bug, now full
  including 666 exports + 14 bug-shape imports).

**Cross-client isolation:**
- Adding rule to client A does not affect client B's evaluation.
- Identity-mode short-circuit doesn't load rules from any client.

## Done Criteria

- All tests green (current 232 + new ~70-90 = ~300-320 passed).
- Real-data smoke green.
- `psql data_hub` schema verifications all pass.
- Sample queries:
  - Growatt export rows resolve to `PV01.xxxx`-shape codes (not
    `BIENTAN.xx`); spot-check 5 rows.
  - Identity clients see `internal_code = customs_code` consistently
    via helper output.
- API responses:
  - `/v1/hub/bcct?client_id=growatt-vn&include_material_identity=true`
    returns response with `material_identity` field; no
    `internal_code` at top level.
  - `/v1/hub/clients/growatt-vn/parser-rules` returns 3-4 seeded
    rules.
  - Old API params return 400.
- UI pages render for Growatt + Johnson + DKE + Demo without errors.
- Parser-rules page allows full CRUD + test panel works end-to-end.
- CO sister-app note posted; CO PR coordinated for same-release
  window.
- Predecessor brief has Amendment 2026-05-08 section appended
  chronologically.
- `goods_name.py` regex + `bcct_adapters/growatt.py` +
  `bcct_adapters/identity.py` deleted; no remaining hardcoded
  per-client parsing logic.

## Next step

After confirmation: open `/tdd` with **rule engine core (D2 + D3)** as
the first test target — rule evaluation semantics + ReDoS rejection
+ identity-mode short-circuit + cache invalidation. These are the
load-bearing primitives; everything else (CRUD, UI, mig data seed,
rename) builds on top.

Subsequent `/tdd` cycles in implementation-plan order; `/rev` after
each major commit to catch issues before bundle review at PR ready.
