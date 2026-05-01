# Session: 2026-05-02 (evening) — Rip BCQT-flavored resolver out of hub

Continued from `2026-05-02-rbac-acl.md`. After RBAC landed and user reviewed the architecture, asked whether `code_resolution_mode` change requires re-importing data, then asked whether the whole resolver concept is BCQT-flavored.

## Question that triggered the work

User: "nhung cai nay deu dang cu the voi BCQT dung khong nhi?" (Aren't all of these BCQT-specific?)

I had three options on the table:
- **A.** Keep resolver in hub, rename + DECISIONS entry.
- **B.** Move resolver out to BCQT.
- **B-lite.** Drop materialization from hub, keep algorithm as a CLI script destined for BCQT.
- **C.** Pluggable strategies (over-engineering).

I recommended A. User asked for an independent critic before deciding.

## Critic findings (decisive)

Three findings flipped the decision from A to B-lite:

1. **Hub stores incorrect canonical data for TP today.** Original Growatt algorithm at `bcqt-growatt/settlement/code_map.py` distinguishes NVL (E11/E15/E13 import qty) vs TP (E42 export qty). Hub's port `app/stores/code_resolution.py` collapsed everything to `direction='import'` (line 39). So `bcct_rows.resolved_customs_code` written for TP rows is *wrong*. Not a cosmetic concern — data integrity bug.

2. **Read API has zero real consumers right now.** `routes/bcct.py` is HTML-only. The `/v1/hub/bcct` endpoint exists but no caller. CO doesn't read resolution. BCQT-System hasn't migrated. Cost of removal = 0 today; grows weekly.

3. **Schema vocabulary leaks.** `resolution_basis` CHECK enum (`'bcct_qty_pick'`, etc.) at `migrations/003_code_mappings.sql:28` is settlement vocabulary literally enshrined in hub schema. Renaming the function doesn't fix the schema leak.

User chose option 2 (B-lite).

## What was done

7 task list items, all completed:

1. **Migration `009_rip_resolver.sql`** — drops `idx_bcct_resolved`, drops column `bcct_rows.resolved_customs_code`, drops table `hub.code_mapping_resolutions`. Applied cleanly against existing seed DB.

2. **`app/stores/code_resolution.py` deleted.** Re-implemented as `scripts/settlement_resolver.py` — same algorithm but reads hub raw data as a consumer, writes to stdout / JSON, never touches hub schema. Module docstring documents the known incompleteness (NVL/TP collapse) and the destination repo (BCQT-System when migration lands).

3. **Caller cleanup**:
   - `routes/bcct.py` — removed import + `resolve_for_dncx` call after upload.
   - `routes/bqd.py` — removed import; removed call after BQD upload; **deleted `trigger_resolve` route** (`POST /clients/{id}/bqd/resolve`); deleted `_list_resolutions` helper; removed `resolutions` template var.
   - `routes/api.py` — removed `lookup_resolution` import; **deleted `/v1/hub/code-mappings/resolutions` endpoint**; removed `resolved_customs_code` field from `/v1/hub/bcct/*` SELECT lists.
   - `seed.py` — removed import + 2 calls (Growatt + Johnson seed paths).

4. **Template cleanup**: `templates/clients/bqd.html` — removed manual "Resolve" button, removed "Resolved" chip in stats row, removed entire "Resolutions" panel (40+ lines).

5. **Tests**: deleted `tests/test_code_resolution.py` (5 tests). 40 pytest passing (45 - 5).

6. **Smoke test against running server**:
   - `/clients`, `/clients/growatt-vn/{bqd,bcct,catalog}` all 200.
   - `/v1/hub/bcct?client_id=growatt-vn` returns 200 with no `resolved_customs_code` field.
   - `/v1/hub/code-mappings/resolutions` returns 404 (endpoint gone).
   - BQD page no longer shows resolve button or resolutions panel.
   - `scripts/settlement_resolver.py growatt-vn` runs standalone, prints summary `bcct_qty_pick: 1, bqd_unique: 6, identity: 3`.
   - Auto-seed produces 2 clients + 13 bcct_rows + 8 BQD pairs cleanly. No errors.

7. **Docs**: STATUS.md updated; DECISIONS.md got new entry "2026-05-02 Settlement code resolver moved out of hub" with full rationale + cross-references; this session log; feature brief at `.ai/features/2026-05-02-rip-resolver-from-hub.md`.

## Decisions made

- **B-lite over full B.** Don't move into BCQT-System repo yet — BCQT hasn't migrated to consumer mode, no integration code exists. Putting in `data-hub/scripts/` keeps the algorithm reachable for current dev/demo while signaling out-of-runtime status. When BCQT migrates: copy to BCQT, fix NVL/TP, store in `bcqt` schema or per-project SQLite.
- **Keep `goods_name.py` parser at hub.** That's genuine ingestion (Excel goods_name → internal_code at upload time). Hub-job. Different from canonical-pick which is consumer-side.
- **Keep `hub.code_mappings` (BQD pairs).** Master data. Pure pairing entered by agency staff. Not derived.
- **Keep `bcct_rows.internal_code`.** Parser output at ingestion. Stored once, deterministic from `goods_name`.
- **Keep `code_resolution_mode` field on `clients`.** Still meaningful — controls parser pick (identity vs growatt regex). It's NOT the canonical-pick strategy (that's gone).
- **Document the move in DECISIONS, not just STATUS.** Architectural decisions need persistent reasoning trail. STATUS is current-state; DECISIONS is "why we got here".
- **Resolver script keeps the known-incomplete NVL/TP collapse for now.** Module docstring flags it. Fixing it is BCQT's job when they own this code. Patching it inside hub-side script would mask the fact that the algorithm needs a real owner.

## What didn't work / Surprises

- Initial pkill on uvicorn returned exit code 144 (SIGTERM trap) — that's normal for `pkill -f`, not an error. Just background-task notification noise.
- Resolver had 3 callers I expected (bcct, bqd, seed) and 2 I didn't immediately check (api endpoints). Found via single grep across `app/`. Took an extra 5 min to update the API endpoints, would have left orphaned references otherwise.
- BQD template still had a "Resolve" button + manual stats chip "X resolved" referencing dropped table. Caught during template edit, removed.

## Open items rolled forward

- **NVL vs TP split fix** — when BCQT adopts the resolver, it must distinguish E42 export for TP from E11/E15/E13 import for NVL per `bcqt-growatt/settlement/code_map.py:119`. Hub's port collapses both → wrong canonical for TP. Documented in `scripts/settlement_resolver.py` docstring + DECISIONS entry.
- **`code_resolution_mode` reparse-on-change** — still not wired (separate from this work, was left open in earlier RBAC session). When dev changes mode, existing `bcct_rows.internal_code` doesn't get re-parsed. Solution waiting in earlier handoff. Not urgent because resolver removal didn't change this.
- **Read API consumers** — when BCQT/CO migrate, they'll need to know `resolved_customs_code` field is gone from `/v1/hub/bcct`. Document in BCQT/CO migration brief.

## How to resume

```bash
cd ~/workspace/client/data-hub
uv run uvicorn app.main:app --port 8754 --host 127.0.0.1 --reload
# Login admin@data-hub.local / admin123
uv run pytest -q  # 40 passing

# Test the standalone settlement resolver (CLI):
uv run python scripts/settlement_resolver.py growatt-vn
uv run python scripts/settlement_resolver.py growatt-vn --json | head -30

# Reset DB and re-seed cleanly:
psql -d data_hub -c "truncate hub.clients cascade"
# (auto-seed re-runs on next request via lifespan)
```

Settlement resolver lives at `scripts/settlement_resolver.py`. Hub's app/ no longer imports it. When BCQT migration sprint lands, this file moves to BCQT-System repo, gets NVL/TP fix, and stores output in `bcqt` schema.

## Post-implementation cleanup (after second critic pass)

User asked for a thorough post-rip review before commit. Critic spawned a second time, this time auditing the RESULT of the rip-out. Findings (all WARN, no CRITICAL):

1. **6 dangling i18n keys** in `app/i18n.py` referencing UI that was deleted: `bqd.resolve_btn`, `bqd.resolve_hint`, `bqd.basis_label`, `bqd.section.resolutions`, `bqd.col.resolved`, `bqd.col.basis`, `bqd.col.updated`. Both vi + en dicts. Originally listed in feature brief's "i18n cleanup" section but skipped during implementation. **Fixed:** all 14 entries deleted.

2. **User-visible lying string:** `workspace.module.bqd_meta` rendered "{n} mapping · resolver tự chạy sau upload" on workspace overview tile. Hub no longer auto-runs any resolver. **Fixed:** replaced with neutral "{n} cặp mã NB ↔ HQ" / "{n} internal ↔ customs pairs".

3. **Pre-existing docstring bug** in `app/parsers/goods_name.py`: docstring claimed "fall back to None" for non-Growatt clients in simple_mapping mode, but code unconditionally returned Growatt regex. Predates this work but surfaced during review. **Fixed:** rewrote docstring to match actual code; deleted unused `_GROWATT_DNCX_TOKENS` constant.

Critic also flagged but did NOT need fix:
- Migration 003/005 historical text still mentions dropped artifacts (immutable migration history convention; intentional).
- `scripts/seed_demo.py` rot (HTTP-seeder pointed at renamed URLs). User asked to delete in cleanup pass — done.
- Settlement resolver script `sys.path` hack works fine; will be revisited when ported to BCQT.

After cleanup: 40 pytest passing, server smoke OK, BQD page renders without dangling strings, workspace overview shows truthful tile text, all orphan refs swept.

## Commit `e3a5697`

Single commit covering both 2026-05-02 features (RBAC + ACL **and** resolver rip). File overlap (i18n, bcct, bqd, clients routes had both kinds of changes) made splitting via `git add -p` risky. Commit message has structured sections naming both features and pointing at briefs/sessions/decisions. 38 files, +2029/-636. Working tree clean post-commit.

`git rename` detected: `app/auth.py → app/auth/session.py` (100% similarity).

## Resume next session

```bash
cd ~/workspace/client/data-hub
uv run uvicorn app.main:app --port 8754 --host 127.0.0.1 --reload  # server NOT running at handoff
uv run pytest -q  # 40 passing

# Sanity: settlement resolver script standalone
uv run python scripts/settlement_resolver.py growatt-vn

# Reset DB:
psql -d data_hub -c "delete from hub.user_managed_clients; delete from hub.user_client_access; delete from hub.users where role != 'dev'; truncate hub.clients cascade;"
# (auto-seed re-runs on next request via lifespan)
```

Key open items rolled forward (also in STATUS.md):
- `code_resolution_mode` reparse-on-change — dropdown is editable for dev now, but POST handler doesn't auto re-parse existing rows. ~15-line helper waiting.
- Real-data validation (Growatt + DKE + Johnson + Dothanh) at scale.
- Cross-app SSO Phase 2 — when BCQT/CO migrate.
