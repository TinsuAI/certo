# Backlog

Ideas captured but not yet planned. Each item should grow into a feature
brief (`.ai/features/YYYY-MM-DD-<slug>.md`) before being built.

For *current* in-flight state and immediate next steps, see `STATUS.md`.
For past architectural decisions, see `DECISIONS.md`.

---

## File-upload UX

### Pre-commit preview at appropriate upload stages
**Captured 2026-05-04.**

Today the upload flow is one-shot: user picks file, hub parses + ingests
in the same request. They only see the result after the fact (or a
confirm-gate preview if rows would CHANGE). For *first-time* uploads to a
fresh tab — Catalog, BQD, BOM — there's no preview at all. If the file is
malformed or the wrong shape entirely, hub either errors or ingests
silently.

Pattern proposed:
- Stage 1: upload file → parse → render preview (first ~20 rows, column
  mapping echoed back) → user confirms.
- Stage 2: confirm → ingest.

Already half-done for BCCT via the parser-mapping flow (when rigid
parsing fails), but valuable to extend to all four upload types so users
*always* see what hub interpreted before commit. May share template +
state with the existing `upload_pending` table.

Cross-cuts with: confirm-on-update gate (already shipped for BCCT, not
yet for catalog/bqd/bom).

---

## Catalog (Danh Mục) sources + provenance tracking

### Multi-source catalog with HQ-registration provenance
**Captured 2026-05-04.**

Catalog can be populated from 4 sources, each with different trust:

| Source | Provenance | Trust |
|---|---|---|
| DS NVL ĐK HQ | Registered with customs — agency declared this code | **Highest** — canonical |
| DS SP ĐK HQ | Same, for products | **Highest** |
| Auto-derived from BCCT (unique customs_codes from declarations) | Codes that appeared on declarations but may not be HQ-registered yet | Medium — operational reality |
| User-uploaded ad-hoc file | Free-form list | Lowest |

Reality: **codes appear on BCCT declarations even when not yet
registered with HQ** — they get rejected/queried later but show up in
the data. Auto-derive from BCCT will produce a superset of registered
codes; the *interesting* set is the diff between
"registered" and "appeared on a declaration but not registered".

Catalog should:
- Track per-row provenance (`registered_with_hq: bool`, `seen_in_bcct: bool`,
  `seen_in_user_upload: bool`).
- Render visual badge on catalog rows: ✓ registered / ⚠ unregistered but
  on declaration / 📥 user-added.
- Allow filtering by provenance.
- Surface "X codes appear on BCCT but aren't registered" as an audit
  alarm somewhere.

Schema sketch: extend `hub.materials` with `provenance jsonb` carrying
per-source first-seen dates + counts. Don't replace; auto-derive runs
nightly (or on-BCCT-upload) and merges into existing rows.

### Auto-derive catalog from BCCT
**Captured 2026-05-04, related to above.**

Job: scan `hub.bcct_rows` for distinct `customs_code` per client, upsert
into `hub.materials` with `provenance.seen_in_bcct = true`. Run on every
BCCT upload (or as a nightly cron). Hub shouldn't be the system of
record for these — they're just "spotted in declarations" — but having
them visible in the catalog UI helps staff notice missing registrations.

---

## BCCT tab — staleness metadata

### Show last-update + data-recency on BCCT tab
**Captured 2026-05-04.**

When staff opens the BCCT tab, they should see at a glance:
- "Last upload: 2 days ago (2026-04-30)"
- "Most recent declaration in DB: 2026-04-15 — data is 17 days old"

These two are different signals:
- Upload recency = how often is staff feeding the system?
- Declaration recency = how stale is the actual customs data, regardless
  of upload cadence?

A 30-day-old declaration on a pile that was uploaded yesterday means
"staff is on top of the upload, but no new declarations have been
processed in a month" — a different operational concern than "we haven't
been uploading for a month."

Surface as a status bar at the top of `/clients/{id}/bcct`:

```
┌─────────────────────────────────────────────────────────────┐
│ Lần upload cuối: 2 ngày trước (2026-04-30 14:23)            │
│ Tờ khai gần nhất: 2026-04-15 (17 ngày trước)                │
└─────────────────────────────────────────────────────────────┘
```

Same idea applicable to Catalog, BQD, BOM tabs.

Cheap to implement: two `MAX()` queries on `file_uploads.parsed_at` and
`bcct_rows.registration_date` per client. Cache for ~1 minute if
needed.

---

## Parser bugs surfaced by 2026-05-02 real-data smoke test

Captured driving real Growatt/DKE/Johnson BOM + BQD files through the live
UI (see `tests/test_real_data_external.py` BOM/BQD parametrize blocks +
`scripts/smoke_real_uploads.py`). Files staged at `/tmp/dh_real_data/`.

### Bug A — `header_row()` picks data row over header row
**Severity:** P0 (blocks every real Growatt BOM today).

`app/parsers/_excel.py:68` scores rows by raw non-empty count. When the
header row has a leading empty STT cell but data row 2 has STT populated,
data row beats header row (10 > 9 non-empty), and `index_headers` runs
against data values. `_parse_flat` then either rejects the file
(BomParseError) or produces garbage when Bug C kicks in.

Real Growatt BOM TP (963 KB) and BTP (462 KB) are both blocked by this.

**Fix idea:** prefer the first row hitting a min-non-empty floor (e.g. ≥4
distinct strings, no all-numeric cells); or score rows by alias-match
count rather than raw non-empty count.

### Bug B — DKE BQD alias gap
**Severity:** P1 (blocks DKE BQD upload; probably affects other agencies).

`app/parsers/code_mappings.py:11` ALIASES doesn't recognize `Mã ERP`
(=internal_code) or `Mã NPL/TP` (=customs_code) — DKE's actual column
names. Pure alias gap. Plus DKE BQD multi-sheet `.xls` has headers on row
4-5, not row 0; `header_row()` `max_scan=15` does cover this, so when
aliases are added the file should parse.

**Fix:** 1-line addition — `"mã erp"` to internal_code aliases, `"mã npl tp"`
+ `"mã npl/tp"` to customs_code aliases.

### Bug C — `index_headers()` empty-header substring match silently corrupts
**Severity:** P0 — silent data corruption. *Found while triaging Bug A.*

`app/parsers/_excel.py:118` pass-2 substring matching uses
`target in h or h in target`. When `h` (header cell) is empty (`''`),
`'' in target` is always True. Empty trailing header cells therefore
get claimed as columns for any unmatched logical field, with column
indices in document order.

**Real-world impact:** Growatt BTP file's data rows have random values at
the trailing-empty-header positions. Hub silently ingests 50 "products"
keyed on values like `'FARATRONIC'` (a brand string that happened to land
at the wrong column). NO user-visible error. Would corrupt customer DB if
shipped.

**Fix:** add `if not target or not h: continue` in the inner pass-2 loop.

### UX-1 — BOM upload parse error renders as raw FastAPI JSON
**Severity:** UX, low.

`app/routes/bom.py:85` raises `HTTPException(400, "Parse error: ...")`
which the browser renders as `{"detail":"Parse error: ..."}` JSON page.
Compare BCCT's parse-mapping flow (`app/routes/bcct.py`) which renders a
proper template with the error embedded + recovery options.

**Fix:** catch BomParseError in route, render an error template (or
redirect with `?error=...` toast pattern matching the BCCT post-upload
toast).

### UX-2 — BOM upload silently corrupts on Bug C path
**Severity:** Critical — see Bug C above. Same root cause; surfaces in UI
as "successful upload" when in fact the parser produced garbage rows.
Mitigated only if Bug A and Bug C are both fixed; until then, BOM uploads
of Growatt-shape files create version/row records that look valid but
reference nonexistent material codes.

---

## Cross-cut from /rev (still open)

- **Cache `use_count` overcounts** when cached mapping fails parse and
  fallback to rigid happens (`_lookup_cached_mapping` increments before
  we know the parse succeeded).
- **`Path(stored_path).read_bytes()`** in `parse_mapping_confirm` has no
  FileNotFoundError handling — 500s if blob missing.
- **Migration numbering gap** (010 → 012, no 011).
- **CSRF protection** on POST endpoints (pre-existing project gap).
- **`set_config('app.user_id', ..., false)`** — switch to `true` (LOCAL)
  if connection pooling lands.

## Cross-cut from prior /rev (Stage A+B/D/C1/C2)

- Apply confirm-gate pattern to catalog/bqd/bom uploads (currently only
  BCCT has the pre-flight diff).
- Manual mapping UI when LLM is disabled (today: upload errors with
  no recourse besides edit-in-DB).

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
- Service-account JWTs land (see "Service-account JWTs" backlog item).
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

**Captured 2026-05-02.**

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
