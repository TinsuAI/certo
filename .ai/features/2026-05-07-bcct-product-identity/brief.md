# Feature: BCCT canonical product/material identity resolver

**Source request:** `~/workspace/client/barry-CO-main/.ai/api-requests/2026-05-07-bcct-bom-product-resolution.md`
**Owner:** Data Hub. **Consumers:** CO (read-only) + BCQT (read-only, NVL imports).
**Date:** 2026-05-07.

## Amendment 2026-05-07 PM — Generalize beyond BOM

Original scope was "BCCT export row → BOM product code". Expanded to
"BCCT row → canonical material/product (any kind: TP, BTP, NVL, CCDC)"
because BCQT settlement also needs NVL identity for import rows.

Resolution rate jumped from 3% → 96-99% on real Growatt + Johnson data
once Stage 1 validates against `hub.materials` (master registry,
superset) instead of `bom_artifacts.product_code` (BOM-only subset).

**Decisions amended:**
- **D1 → D1'**: persisted column shape adds `resolved_code` + `product_kind`.
  `bom_product_code` becomes a conditional alias = `resolved_code` when
  the resolved material has alive BOM (preserves CO's existing
  `if bom_product_code: load_bom(...)` logic — non-BOM resolutions
  leave it None so CO doesn't try to fetch BOM for an NVL leaf).
- **D2 → D2'**: Stage 1 validates `customs_code` against `hub.materials`
  (not `bom_artifacts`). Stage 2 same change.
- **New D11**: `product_kind ∈ {tp, btp_sx, btp_nm, nvl, ccdc, unknown}`.
  Consumers filter by kind for their use case (CO: `kind == 'tp'`,
  BCQT: `kind in ('nvl', 'btp_sx')` for material consumption).

**BCQT consumer plan deferred** — sister-repo work after Data Hub
contract stabilizes. Tracked in BACKLOG.

## Scope

Add an item-level `product_identity` object to:
- `GET /v1/hub/bcct` (default `include_product_identity=false`)
- `GET /v1/hub/bcct/invoice-matches` (default `include_product_identity=true`)

The object names which Data Hub BOM `product_code` belongs to a BCCT
export line, with provenance + confidence + candidates. CO uses
`product_identity.bom_product_code` only when `resolution_status='resolved'`.

**In scope:**
- Resolver layer at `app/resolvers/bcct_product_identity.py`. Pure
  Python — no SQL inside endpoint handlers.
- Per-client parser adapter registry mirroring the BOM adapter pattern
  (`app/parsers/bcct_adapters/`). One adapter per agency; default =
  identity (no goods-name parsing).
- Growatt adapter: extract parenthesized BOM-shaped codes from
  `goods_name`, validate against same-client `hub.bom_artifacts.product_code`.
- Persisted column `hub.bcct_rows.product_identity jsonb` populated
  at ingest time + lazy-fill at read time when missing.
- Reviewed line mapping table `hub.bcct_product_identity_review`
  (append-only audit, supports operator overrides).
- API response shape per CO spec, covered by provider tests.

**Out of scope (explicit):**
- New mutating endpoint for review writes. CO request itself defers
  this: "If Data Hub later wants CO/user selections to feed back into
  Data Hub, define a separate proposal endpoint." We only ship the
  table + lookup; UI and write API land in a follow-up brief.
- Re-resolving existing rows on parser-version bump. Handled by
  `scripts/resolve_bcct_product_identity.py` ad-hoc; no background
  worker.
- BCQT consumption — BCQT does not need this field.

## Decisions

**D1. Persist as `bcct_rows.product_identity jsonb` column.**
- Populate at BCCT ingest (parser → resolver → write).
- Endpoint reads the column. If NULL, lazy-resolve at read time
  (covers existing 23k Growatt rows post-deploy without a backfill
  blocking the deploy). Resolved value is NOT written back during
  read — `resolve_bcct_product_identity.py` script does the bulk
  backfill once.
- Why JSONB not separate table: 1:1 with row, never queried
  independently, additive evolution (parser_version, candidates list)
  without migrations. Cost: index on `(client_id, (product_identity->>'resolution_status'))`
  if filtering by status becomes a pattern (deferred — not in spec).
- Alternative considered: separate `bcct_product_identity` table
  keyed by line_key. Rejected: extra join on every list query, no
  benefit over jsonb when 1:1.

**D2. Resolver stage order matches CO spec verbatim.**
1. `structured_field` — `customs_code` exists in
   `hub.bom_artifacts.product_code` for this client (covers Johnson +
   any client where customs_code IS the BOM product code, like
   Growatt rows where `customs_code='SA00.0001402'` is also a BOM
   product). Confidence: high.
2. `goods_name_embedded_code` — client adapter parses parenthesized
   BOM-shaped codes from `goods_name`, validates each against
   bom_artifacts. Exactly one match → resolved/high. Multiple → ambiguous.
3. `reviewed_line_mapping` — lookup `bcct_product_identity_review`
   by `(client_id, declaration_no, line_no, transaction_key)`.
   Confidence: high (manual review).
4. `code_mapping_candidate` — list internal_codes/customs_codes from
   `hub.code_mappings`. Add to `candidates[]` with confidence=low.
   **Never resolves** — must not set `resolution_status='resolved'`
   from this stage alone.
5. `missing` — no candidates at all.

**D3. Parser adapter pattern mirrors BOM adapter registry.**
- `app/parsers/bcct_adapters/__init__.py` — `register()`, `resolve(name)`.
- `app/parsers/bcct_adapters/identity.py` — default no-op. `parse_product_identity_candidates(row, client_id) → []`.
- `app/parsers/bcct_adapters/growatt.py` — regex `\(([A-Z]{2,}\d{2}\.\w+)\)`
  scans `goods_name`, returns each match as candidate evidence.
- Adapter selection: per `clients.code_resolution_mode` (existing
  column). `growatt` → growatt adapter; `identity` or NULL → identity.
- `parser_version`: module-level constant per adapter (e.g.
  `growatt:2026-05-07`). Bump on regex change.

**D4. New table `hub.bcct_product_identity_review`** (migration 032).
```sql
create table hub.bcct_product_identity_review (
  client_id text not null references hub.clients(client_id) on delete cascade,
  declaration_no text not null,
  line_no text not null,
  transaction_key text not null,
  bom_product_code text,            -- null = explicit "no resolution"
  status text not null check (status in ('reviewed', 'rejected')),
  reviewed_by text not null,
  reviewed_at timestamptz not null default now(),
  notes text,
  primary key (client_id, transaction_key, line_no, reviewed_at)
);
create index on hub.bcct_product_identity_review (client_id, transaction_key, line_no);
```
Append-only (no UPDATE; new review rows supersede). Resolver picks
`order by reviewed_at desc limit 1`. No write API in this brief —
populated by future operator UI or admin script.

**D5. `confidence` mapping.**
- `high`: structured_field, single goods_name match, reviewed_line_mapping.
- `medium`: multiple goods_name matches resolved by tiebreak rule
  (prefer one with most BOM artifacts).
- `low`: code_mapping_candidate.

**D6. Response field ordering exactly per CO spec.**
- `resolution_status`, `bom_product_code`, `selected_candidate_code`,
  `display_code`, `declared_customs_code`, `declared_internal_code`,
  `line_key`, `resolution_source`, `confidence`, `review_status`,
  `parser_adapter`, `parser_version`, `evidence`, `candidates`.
- Non-resolved statuses → `bom_product_code = null`. Best candidate
  may appear in `selected_candidate_code` for UI preselection.

**D7. `include_product_identity` query param defaults differ per endpoint.**
- `/bcct`: default `false` (broad list views stay light).
- `/invoice-matches`: default `true` (CO origin flow consumes).
- Param accepted on both endpoints; `false` strips the field from
  response items (does NOT skip the resolver if column already
  populated — just omits in serializer).

**D8. `product_identity_candidate_limit` query param.**
- Default 5, max 20. `400 invalid_product_identity_candidate_limit`
  on out-of-range (per spec).

**D9. Ingest write-path integration.**
- `app/routes/bcct.py:_apply_bcct_rows` (line ~1037) already calls
  `internal_code_parser_for(client_id, mode)`. Add a sibling call to
  `resolve_product_identity(row, client_id)` and write result to
  `product_identity` column.
- Lazy-fill at read: in `api_list_bcct` + `api_invoice_matches`,
  after fetching rows, for any row where `product_identity IS NULL`
  AND `include_product_identity=true`, call resolver and merge into
  response. Do NOT write back (read endpoints stay read-only against DB).

**D10. Backfill script.**
- `scripts/resolve_bcct_product_identity.py --client-id <id>`.
- Run once post-deploy on Growatt + Johnson. Wipe + ingest fresh
  (pending) supersedes if resolver lands first.

## Risks

**R1. `code_mappings` candidate contamination.**
The single highest-risk failure mode is auto-resolving from many-to-many
code-mappings. CO has 2,892 mappings across 520 customs_codes (avg
5.5 internal_codes per customs_code). Resolver MUST keep
code-mappings as candidates only. Negative test guards this.

**R2. Persisted-column staleness.**
BOM artifacts get added/tombstoned. A `product_identity` written when
the BOM existed could become stale (resolved → product no longer has
alive artifact). Mitigation: lazy re-validate at read time when
returning `resolved` — quick check that bom_artifact still alive for
that product_code. If not, downgrade to `unverified`. Single index
lookup per row.

**R3. Goods_name regex precision.**
False positives from model numbers like `(Pro.E)` or `(MIN 11400TL-XH-US)`
matched as BOM codes. Mitigation: shape regex `[A-Z]{2,}\d{2}\.\w+`
excludes these. Cross-check against actual `bom_artifacts.product_code`
set further reduces FP. Test corpus must include real Growatt edge cases
(`(Pro)`, `(Pro.E)`, `(MIN ...)`).

**R4. `internal_code` semantic clash.**
Growatt's existing `bcct_rows.internal_code` column stores
`BIENTAN.17`-shape codes (agency ERP code), NOT BOM product codes.
Don't repurpose. New field `product_identity.bom_product_code` is
distinct. Keep both columns intact; CO consumes the new one.

**R5. `bcct_rows.artifact_id` confusion.**
Existing column from migration 031 (renamed from `bom_version_id`).
This binds a row to a specific BOM artifact UUID at point-of-use
(BCQT-side concern). Different concept from `product_identity` which
identifies the product CODE. Don't conflate. Document the difference
in code comments.

**R6. Wipe + ingest fresh sequencing.**
If resolver ships before wipe, the wipe re-ingest populates the new
column natively for every row. No backfill needed. Build resolver
first → wipe → no second pass. STATUS step 1 (wipe) waits on user
trigger anyway, so this works.

**R7. Parser version churn.**
Bumping `parser_version` constant doesn't auto-trigger re-resolve.
Backfill script handles it on demand. CO consumers receive whatever
`parser_version` was current when the row's `product_identity` was
written. Acceptable per spec ("Same query against unchanged data and
same parser version must return the same product identity result").

## Open Questions

**Q1. Reviewed-line-mapping write path — defer or include?**
Spec hints at it ("If Data Hub later wants CO/user selections to feed
back into Data Hub, define a separate proposal endpoint"). I propose
**defer**: ship the read-side table + lookup now (so the resolver
honors reviewed mappings if they exist), but leave the write API +
operator UI to a follow-up brief. CO doesn't need write today.
**Recommendation: defer.** Confirm before implementation.

**Q2. Lazy-write back vs strict read-only?**
When a read request triggers lazy-resolve for rows with NULL
`product_identity`, do we write the result back asynchronously?
- Pro: speeds up subsequent reads, populates column without backfill.
- Con: read endpoint becomes write endpoint, complicates caching +
  test isolation.
- **Recommendation: do NOT write back.** Backfill script + ingest-time
  population are enough. Lazy-resolve at read is a one-release-grace
  fallback only.

**Q3. `bom_artifact_count` and `latest_flatten_status` in candidates.**
Spec example shows these fields. Cheap (one indexed query per
candidate). Include for UI ergonomics or skip for v1?
- **Recommendation: include** — adds ~1 query per candidate, capped
  at `product_identity_candidate_limit=5` default. Negligible.

**Q4. Should ambiguous candidates be ranked?**
Spec: "ranked candidate list". Tiebreak when multiple parenthesized
codes match BOM products: by `bom_artifact_count` desc, then
`latest_flatten_status='flattened'` first. Single deterministic order.
- **Recommendation: yes, deterministic rank** as above.

**Q5. Caching `product_code` set per resolver call.**
Endpoint may receive a 200-row page; resolver does N lookups against
`bom_artifacts.product_code`. Cheaper to fetch the set once per
request and validate in Python.
- **Recommendation: per-request memoization in resolver context object.**

## Implementation Plan

**Order:**
1. **Migration 032** — `bcct_product_identity` jsonb column +
   `bcct_product_identity_review` table. Ship alone (safe, additive).
2. **Resolver core** + identity adapter + Growatt adapter, all
   under `app/resolvers/` and `app/parsers/bcct_adapters/`. TDD with
   golden Growatt fixtures.
3. **Ingest write-path** — wire resolver into `_apply_bcct_rows`.
   Tests with Growatt corpus.
4. **Endpoint serialization** — additive `product_identity` field on
   `/v1/hub/bcct` + `/invoice-matches`. Provider tests per CO spec.
5. **Backfill script** — opt-in, manual trigger.
6. **Cross-repo** — once provider tests green, post sister-app note
   for CO; CO removes its temporary code-mappings BOM resolution.

**Estimate:** 6-9h end-to-end. Migration 30min, resolver core 2-3h,
ingest wire-up + tests 2h, endpoint surface + tests 1-2h, backfill
script + cross-repo notes 1h.

**Test plan (mirrors CO spec exactly):**
- Provider — Growatt `(PV01.0117500)` → resolved.
- Provider — same identity on invoice-matches after invoice filter.
- Provider — same-client BOM only (cross-client isolation).
- Provider — `include_product_identity=false` omits field.
- Provider — non-resolved → `bom_product_code` null.
- Negative — many-to-many code-mappings only → ambiguous/unverified.
- Negative — parsed code with no BOM artifact → unverified.
- Negative — multiple plausible codes → ambiguous.
- Negative — unknown client_id → 404.
- Negative — invalid candidate_limit → 400.
- Edge — multi-paren goods_name (model + BOM code).
- Edge — model-only paren `(Pro.E)` no BOM match → no embedded resolution.
- Edge — customs_code IS the BOM code (structured_field stage hit).
- Edge — non-flattened BOM artifact only → resolved still allowed
  (BOM exists, even if not flattened — CO surfaces "missing flatten").

## Next step

After D1-D10 + Q1-Q5 confirmed: open `/tdd` with the resolver core as
the first test target.
