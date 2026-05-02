# Backlog

Ideas captured but not yet planned. Each item should grow into a feature
brief (`.ai/features/YYYY-MM-DD-<slug>.md`) before being built.

For *current* in-flight state and immediate next steps, see `STATUS.md`.
For past architectural decisions, see `DECISIONS.md`.

---

## CO + BCQT — adopt service-account JWTs

**Captured 2026-05-02 PM.** Ship-blocking dependency for "API auth strict
promotion" below. No hard deadline — coexistence works fine.

Service-account JWTs are live in Data Hub (migration 020 + CLI). Sister
apps still call with permissive bearer / user JWT. To adopt:

1. **Mint tokens** (Data Hub admin):
   ```bash
   uv run python scripts/mint_service_token.py create \
     --name co --scopes hub:read,bom:propose \
     --client-ids growatt-vn,dke-vietnam-d0e3,johnson-vn,do-thanh-vietnam-2614 \
     --created-by <admin-email>

   uv run python scripts/mint_service_token.py create \
     --name bcqt --scopes hub:read \
     --created-by <admin-email>
   ```
2. **CO repo** (`barry-CO-main`): inject `DATA_HUB_SERVICE_TOKEN` env
   into `app/data_hub_client.py` Bearer header on every call. If CO
   verifies tokens locally, branch on `claims["typ"] == "service"` —
   service tokens have no email/role/name; `sub` is `svc:co`.
3. **BCQT repo**: same pattern, `hub:read` scope only.

Full instructions: `.ai/sister-app-notes/2026-05-02-service-account-jwts-available.md`.
Design rationale: `.ai/features/2026-05-02-service-account-jwts.md`.

**Pull this out of backlog when:** ready to coordinate the sister-repo
PRs, or when about to flip `api_auth_strict=true` (then it becomes
ship-blocking).

---

## API auth — flip dev-permissive reads to strict by default

**Captured 2026-05-02.** **Unblocked 2026-05-02 PM** — service-account
JWTs shipped (migration 020). Now waiting on sister-app cutover (item
above).

Today the read API on `/v1/hub/*` accepts non-empty legacy bearer strings
when `api_auth_strict=false` (default). Writes (BOM proposal POST) always
require a valid Data Hub JWT regardless of the flag. The trade-off was
chosen deliberately: prioritize dev/integration ergonomics today,
prioritize corruption prevention on writes.

**Promote when:**
- CO and BCQT have switched to service-account JWTs (per
  `.ai/sister-app-notes/2026-05-02-service-account-jwts-available.md`).
- We have a staging environment where strict mode can be soak-tested
  before flipping prod.

**Steps when promoting:**
1. Default `api_auth_strict=true` in fresh installs; add a one-time
   migration to flip existing installs after CO/BCQT confirm readiness.
2. Remove the legacy bearer fallback path in `_require_token`; keep only
   the JWT validation branch.
3. Update `docs/API_CONTRACT.md` to drop the dev-permissive mode section.
4. Update CO/BCQT consumer code to send real JWT on every read call.

---

## Manual mapping UI when LLM disabled

When LLM is unavailable AND a file fails rigid parse, the upload errors
with no recovery besides edit-in-DB. Add a "Manual mapping" link on the
parser-mapping preview when LLM is unavailable, surfacing the same
header→logical-field grid the LLM-confirmed flow uses. Reuses
`parser_mappings` cache once confirmed.

---

## BOM/BQD/Catalog parse-error UX

**Partial.** Phase 2 universal preview-confirm pattern surfaces parsed
rows nicely when parsing succeeds. But when the parser rejects the file
outright (no LLM available, or LLM also fails), `app/routes/bom.py:145`
still raises `HTTPException(400, ...)` which the browser renders as raw
FastAPI JSON `{"detail": "..."}`.

Compare BCCT's `parse-mapping` error path which renders a proper
template with recovery options.

**Fix:** catch the final parse-error path and render an error template
or redirect with a `?error=...` toast (matching the post-upload toast
pattern from `c77da85`).

---

## /rev cross-cuts (still open)

- **CSRF protection** on POST endpoints (pre-existing project gap).
- **`set_config('app.user_id', ..., false)`** — switch to `true`
  (LOCAL) if connection pooling lands. Today every `connect(user_id=...)`
  call gets a fresh connection, so SESSION-scoped GUC is fine.
- **Migration numbering gap** (010 → 012, no 011) — cosmetic; renaming
  applied migrations would diverge `schema_migrations` rows across
  environments.

---

## Notes

The previously-tracked items below have all shipped (verified in HEAD as
of 2026-05-02 PM):

- Pre-commit upload preview at all stages → `359ebec` Phase 2.
- Catalog multi-source provenance + auto-derive from BCCT → `6141d1e` A4.
- BCCT (and all 4 tab) staleness metadata → `53da49b` A3.
- Parser bugs A/B/C/D from 2026-05-02 real-data smoke → `338be91` Phase 1.
- BCCT confirm-on-update gate + history page → `b3a59d6` + `91d2ca7`.
- LLM smart parser → `175d1f8` (BCCT) + `5d44b60` (BOM/BQD).
- /rev cache `use_count` overcount + `Path(stored_path).read_bytes()`
  FileNotFoundError → `2e8cd05`.
- Apply confirm-gate pattern to catalog/bqd/bom (was a cross-cut from
  prior /rev) → `359ebec` Phase 2.
- Service-account JWTs → migration 020, `app/jwt_issuer.py:make_service_token`,
  `scripts/mint_service_token.py`, `tests/test_service_account_jwts.py`
  (13 new tests, 232 total).

These were removed from this file on 2026-05-02 PM. See git history of
`.ai/BACKLOG.md` for the original entries.
