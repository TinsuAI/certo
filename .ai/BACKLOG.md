# Backlog

Ideas captured but not yet planned. Each item should grow into a feature
brief (`.ai/features/YYYY-MM-DD-<slug>.md`) before being built.

For *current* in-flight state and immediate next steps, see `STATUS.md`.
For past architectural decisions, see `DECISIONS.md`.

---

## API auth — flip dev-permissive reads to strict by default

**Captured 2026-05-02.**

Today the read API on `/v1/hub/*` accepts non-empty legacy bearer strings
when `api_auth_strict=false` (default). Writes (BOM proposal POST) always
require a valid Data Hub JWT regardless of the flag. The trade-off was
chosen deliberately: prioritize dev/integration ergonomics today,
prioritize corruption prevention on writes.

**Promote when:**
- CO and BCQT have stable JWT issuance flows wired in (no longer relying
  on hand-pasted bearer strings during integration).
- Service-account JWTs land (see "Service-account JWTs" below).
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

## Service-account JWTs and scoped tokens

**Captured 2026-05-02. Blocks "auth strict" promotion above.**

Strict-write auth today uses real **user** JWTs plus the user's current
client ACL. There is no notion of a "machine identity" — CO and BCQT have
to carry a real user's token to call mutating endpoints.

**Why this matters:**
- Background jobs (cron, batch ingest) have no logged-in user; pinning a
  human user's token to a job is fragile (user offboarding, password
  rotation breaks the job).
- Audit log `bcct_row_history.changed_by` records the user_id, so CO
  ingest writes look like a human edit in history view.
- User ACL is broader than what CO actually needs (CO only needs
  bom:propose / bcct:write for its own clients).

**Design sketch when implementing:**
- New `hub.service_accounts` table (name, scopes[], created_at,
  revoked_at, hashed_secret).
- Token issue endpoint or bootstrap script that mints a service JWT
  with `typ=service`, `sub=svc:co|svc:bcqt`, `scopes=[...]`.
- `_require_token` branches on `typ`: user JWTs validate against ACL;
  service JWTs validate against scopes.
- Audit GUC `app.user_id` set to `svc:<name>` for service requests so
  history view distinguishes machine actors from humans.
- Per-token revocation independent of user accounts.

**Cross-repo:** needs sister-app notes for CO + BCQT once design is
locked. CO consumer code in `app/data_hub_client.py` will need to
swap from user-JWT to service-JWT on writes.

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

These were removed from this file on 2026-05-02 PM. See git history of
`.ai/BACKLOG.md` for the original entries.
