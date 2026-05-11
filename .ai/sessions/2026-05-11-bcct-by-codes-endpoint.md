# Session: BCCT lookup by material codes endpoint

**Date:** 2026-05-11.
**Topic:** Add `GET /v1/hub/clients/{client_id}/bcct/by-codes` to
fix CO's 30s substitute-modal stock derivation against Johnson 65k
BCCT.

## What Was Done

1. **New endpoint** in `app/routes/api.py`:
   `GET /v1/hub/clients/{client_id}/bcct/by-codes?codes=A,B,C`.
   - Mirrors row shape of `/v1/hub/bcct` (same SELECT column set).
   - Filters by `client_id = %s AND upper(customs_code) = any(%s)`.
   - Codes are split, trimmed, deduped, uppercased; max 100/request.
   - Supports `direction`, `include_material_identity`,
     `material_identity_candidate_limit`, `cursor`, `limit` (default
     200, cap 1000) — same semantics as existing `/v1/hub/bcct`.
   - Auth: `_require_token` + `_require_can_view_client` + scope
     `hub:read`. Same as the rest of `/v1/hub/*`.
   - Validation order: token → view-client → candidate_limit → codes
     shape → client exists → page args.

2. **Provider tests** (`tests/test_bcct_by_codes_api.py`, 19 tests):
   - Codes filter: single, multi, mixed-case, URL-decoded.
   - Direction combine with codes.
   - Unknown codes → 200 empty.
   - Row shape mirrors `/v1/hub/bcct` column set.
   - `include_material_identity=true` attaches resolver output.
   - Cursor pagination round-trip (page 1 → next_cursor → page 2;
     different rows; final next_cursor=null).
   - Error contract: empty codes → 400; whitespace-only → 400;
     omitted param → 400; >100 → 400; exactly 100 → 200 empty;
     unknown client → 404.
   - Strict-mode auth: hub:read scope grants 200; missing scope → 403;
     whitelist mismatch → 403; no bearer → 401.

3. **Contract docs:**
   - `docs/API_CONTRACT.md` — entry under BCCT section.
   - `docs/API_CHANGELOG.md` — additive entry dated 2026-05-13 with
     full contract, why-not-alternatives, and pointer to provider
     tests + CO request spec.

4. **Backlog:**
   - New item **C.1.a** — soak test pending under real CO load.
     Provider tests cover contract; not yet validated under
     concurrent requests, long-history codes, large slices with
     material_identity, or with prod-shaped EXPLAIN ANALYZE.
   - "Shipped — kept for context" entry added with cross-link to
     C.1.a.

5. **Live smoke** against Johnson:
   - `codes=005365-00,005048-AB&direction=import&limit=5` → 5 rows
     in ~30ms.
   - Mixed case (`005048-ab`) matched correctly.
   - All three error contracts (empty, >100, unknown client) fire.

## Decisions Made

- **Endpoint shape: `/v1/hub/clients/{client_id}/bcct/by-codes` (path
  param)** not `/v1/hub/bcct?customs_codes=...&client_id=...` (query
  param). Matches the CO spec; consistent with the
  substitute-mirror precedent (`ae3373b`,
  `/v1/hub/clients/{c}/materials/{m}/substitutes`). Memory
  `project_api_routing_convention.md` covers the dual `/api/v1/*`
  vs `/v1/hub/*` split.
- **Case-insensitive exact match.** `upper(customs_code) = any(%s)`
  with the params list uppercased in Python. Skipped trigram /
  fuzzy match — CO already resolved to candidate codes upstream;
  this endpoint is a strict lookup, not a search.
- **No `material_identity.bom_product_code` matching** despite the
  CO spec calling it "optional enrichment". Kept the implementation
  to `customs_code`-only to ship cleanly. CO can layer that on
  later if needed.
- **Validation order: codes-shape before client-existence.** Empty
  codes / >100 returns 400 even when client_id is also invalid.
  Saves a DB hit on bad input, matches spec error enumeration
  order. Tests assert this on real seeded client; live smoke
  confirms ordering on unknown client.
- **Reused existing `_paged()` shape** (items / next_cursor /
  total_estimate=None) rather than computing total_estimate.
  Matches `/v1/hub/bcct` — consumer parses identically.
- **`include_material_identity` defaults to false** — same as
  `/v1/hub/bcct` (per D7 in earlier sessions). CO can opt in.

## What Didn't Work

- **First validation ordering** put `if not get_client(...)` before
  `_parse_codes_param(codes)`. Live smoke against `client=foo` +
  `codes=` returned `404 Client not found` instead of
  `400 missing codes` — the spec lists 400 errors before 404, and
  401/403 callers don't care, so I reordered. Tests with seeded
  client still passed before/after the reorder (real client
  exists, so 400 fires regardless).
- **One transient test failure** in `test_bom_raw_edges.py`'s
  `test_technical_raw_upload_confirm_materializes_edges` during
  the first full-suite run with the new test file present.
  Re-running the full suite was clean (1072/1072). Running the
  failing test alone, then together with the new file in pairs,
  was also clean. Could not reproduce. Not blocking; flagged in
  STATUS.md and noted as something to watch if it recurs.

## Open Items

1. **CO consumer not yet shipped.** Per CO `CLAUDE.md`, they will
   consume only after they see Data Hub provider tests + changelog
   bump — both landed in this session. Ping-back expected from CO
   in `.ai/sister-app-notes/`.
2. **Backlog C.1.a — soak test under real CO load.** Specifics in
   that entry: concurrent requests, long-history codes,
   `include_material_identity` on ~100-row slices, EXPLAIN ANALYZE
   for index usage of `upper(customs_code) = any(...)`.
3. **Memory candidate considered, skipped:** "API endpoint
   validation order: input shape before resource existence". One
   data point; if this pattern repeats, capture it. For now the
   reasoning is local to the endpoint and noted in STATUS Notes.
4. **CO spec mentioned but skipped:** match against
   `material_identity.bom_product_code` as optional enrichment.
   Easy to add if CO ever passes resolved codes instead of raw
   customs codes.
