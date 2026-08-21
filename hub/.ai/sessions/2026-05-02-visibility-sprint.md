# Session: 2026-05-02 — Visibility sprint (autopilot)

User asked for a long autopilot run from ~03:06 SGT through ~10:30 SGT.
Sprint A (visibility) was scoped first; Sprint B (notification + chat
agent + SSO) drives the remainder.

This session log covers Sprint A. Sprint B continues in subsequent log.

## What was done

### A1 — feature brief (`/discover` compact)

`.ai/features/2026-05-02-visibility-sprint.md` — single doc covering
A2/A3/A4 with schema, helper signatures, test plan, risks. Skipped a
formal critic round because each sub-task is well-scoped.

### A2 — BCCT LLM-fallback gate cement (commit `1f4d70a`)

**Discovery:** STATUS follow-up #1 was stale. Phase 2's universal
`_ingest_rows` stash (commit `359ebec`) already routes
`parse_mapping_confirm` through the diff-preview gate — the route ends
with `return _ingest_rows(...)` without any confirm flags, so the gate
fires and the staff sees a preview of any DIFFs/ORPHANs the
LLM-confirmed parse would introduce.

Did not refactor — just locked the contract with 2 regression tests:
- `test_ingest_rows_default_routes_through_preview_gate`: no flags →
  redirect to `/upload/preview/{id}`, no row applied.
- `test_ingest_rows_partial_confirm_still_gated`: `confirm_diffs=True`
  alone still gates. Both flags must be True together to bypass.

STATUS + BACKLOG entry crossed out.

### A3 — staleness metadata bar (commit `53da49b`)

Two-line bar at the top of all 4 workspace tabs. Implementation:

- `app/stores/staleness.py`:
  - `tab_freshness(client_id, module)` — `MAX(parsed_at)` on
    `file_uploads WHERE parse_status='done'` + per-module data MAX().
  - `humanize_age(when, lang)` — coarse-grained 'năm/tháng/ngày/giờ/
    phút trước' (vi/en).
  - `freshness_for_template(request, client_id, module)` —
    pre-renders the entire dict shape so templates stay declarative.
- `app/templates/clients/_staleness_bar.html` — partial; hidden when
  both timestamps null.
- `app/static/css/app.css` — `.staleness-bar` 2-col grid; collapses
  to 1-col under 720px.
- `app/i18n.py` — 6 keys (vi + en) for labels + empty states.
- 4 routes (`bcct`/`bom`/`bqd`/`catalog` `list_view`) call
  `freshness_for_template()` and pass `freshness` to template.
- 4 templates include the partial right after `_client_nav.html`.

Tests: 16 in `test_staleness.py` covering helper happy path + unknown
client + unknown module + parse_status filter + humanize_age all
buckets + bilingual + naive-date input + future-clamps-to-now.

UI smoke (curl): all 4 tabs render correctly. BCCT shows e.g.
`Lần upload gần nhất: 2026-05-02 02:44 (33 phút trước)` +
`Tờ khai gần nhất: 2026-04-21 (11 ngày trước)`. BQD/Catalog gracefully
show 'chưa upload lần nào' when no `parse_status='done'` row exists
(because their ingest paths flip to done only via the confirm route,
not on upload).

### A4 — catalog multi-source provenance (commit `6141d1e`)

Three top-level provenance keys per `hub.materials` row, each optional,
presence = signal:
- `registered_with_hq`: agency declared via Danh Mục Excel upload.
- `seen_in_bcct`: code shows up on at least one customs declaration.
- `user_added`: free-form manual entry (deferred — not in MVP).

Migration `014_catalog_provenance.sql`:
- adds `provenance jsonb default '{}'`.
- GIN(jsonb_path_ops) index for fast `provenance ? 'key'`.
- Backfill: every existing row → `registered_with_hq` (only path
  that wrote to materials before this migration was catalog upload).
- Backfill step 2: existing rows with matching `bcct_rows` get
  `seen_in_bcct` aggregate (canonical happy path: registered AND seen).

`app/stores/provenance.py`:
- `derive_from_bcct(cur, client_id, customs_codes)`: scoped UPSERT on
  materials. Default category 'nvl' for new rows. JSONB merge in
  conflict branch preserves `registered_with_hq` if already present.
- `unregistered_seen_count(cur, client_id)`: drives the audit alarm.

`_apply_bcct_rows` collects touched customs_codes from the apply batch
and calls `derive_from_bcct` on the same cursor (same transaction as
the BCCT insert + orphan delete). New declaration codes flow into
catalog as ⚠seen rows automatically.

`_insert_materials_with_cursor` now takes `upload_id` and writes
`registered_with_hq.source_upload_id` for audit traceability. Conflict
branch uses `provenance ||` so `seen_in_bcct` survives a re-upload.

UI:
- Audit alarm banner at top of catalog page when unregistered count > 0;
  one-click filter to the unregistered list.
- Source filter chip row beside Category chips (All / ✓ ĐK / ⚠ Chưa ĐK
  / 📥 Tự thêm with counts).
- Source column in the table per row with multi-badge support
  (registered + seen-in-BCCT can both render simultaneously).

i18n: 12 new keys (vi + en).

Tests: 10 in `test_provenance.py`:
- new BCCT code → material with seen_in_bcct + cat='nvl'
- existing registered → derive merges, registered preserved
- decl_count is distinct count
- empty/whitespace customs_codes filtered
- idempotent: re-running with new BCCT updates last_seen + count
- catalog upload after BCCT → both keys present
- unregistered_seen_count: zero/one/zero-when-both

Plus `test_bcct_confirm_flow.py` cleanup updated to delete the
auto-derived materials rows.

E2E smoke (live UI): seeded a synthetic BCCT row with new customs_code
+ matching materials row with only `seen_in_bcct`. Catalog page showed
⚠ alarm banner + ⚠ Chưa ĐK HQ badge + filter chip count = 1.
`?provenance=unregistered` filtered to that single row. Cleaned up.

## Decisions made

- **A2: don't refactor, just lock with tests.** The fix already shipped
  in Phase 2; the follow-up note was stale. Cementing via regression
  tests is cheaper + safer than refactoring 800 LoC of bcct.py.
- **A3: pre-render strings in helper, not template.** Templates have
  no Python — pre-rendering keeps the partial small and pure-jinja.
- **A3: BQD/Catalog 'chưa upload lần nào' is correct, not a bug.**
  Their ingest paths today don't flip `file_uploads.parse_status` to
  'done' on upload. Bar reflects ground truth.
- **A4: backfill assumes existing rows came from catalog upload.**
  True today — only catalog upload + seed write to materials. If BCCT
  ever starts writing materials directly (which is what `derive_from_bcct`
  is designed to do going forward), provenance keys disambiguate.
- **A4: default category 'nvl' for auto-derived rows.** Most BCCT
  rows are NVL imports. Wrong-but-fixable: staff re-categorizes in
  catalog UI; provenance signal is independent of category.
- **A4: keep BCCT auto-derive in same transaction.** Foreign-key
  integrity is automatic; partial failure can't leave provenance
  out of sync with BCCT data.
- **A4: alarm only renders when count > 0 AND user isn't already
  filtered to unregistered.** Avoids redundant scolding.

## What didn't work / Surprises

- **Initial staleness `bqd` query used `updated_at`** which doesn't
  exist on `code_mappings` (only `created_at` is). pytest caught it
  immediately. Fixed in helper.
- **Test pollution: `_apply_bcct_rows` change leaked B-CODE / C-CODE
  / PE-001 materials into growatt-vn**. The `derive_from_bcct` ran
  during BCCT confirm tests and the cleanup fixture didn't know about
  materials. Updated `test_bcct_confirm_flow.py` cleanup to delete the
  test customs_codes from materials.
- **Server compound `pkill … && nohup …` killed by parent shell.**
  Two attempts where the shell exited 144. Fixed by simply launching
  `nohup … &` standalone, then waiting + curling separately.
- **Initial staleness partial template tried date/datetime polymorphism
  with `':' in strftime('%H:%M')` heuristic** — broken for date type
  which always renders 00:00 in time. Replaced with helper-side
  pre-formatting via `isinstance(when, datetime)`.

## How to resume

```bash
cd ~/workspace/client/data-hub
# Server probably still up on :8754. Restart cleanly:
pkill -f 'uvicorn app.main' && \
  nohup uv run uvicorn app.main:app --port 8754 --host 127.0.0.1 \
    > /tmp/dh_server.log 2>&1 & disown

# Tests
uv run pytest -q                                            # 132 passed, 15 skipped
DATA_HUB_REAL_DATA_DIR=/tmp/dh_real_data uv run pytest -q   # +15 real-data

# Login: admin@data-hub.local / admin123 (role=dev)

# Quick UI tour
# - any tab → top staleness bar
# - /clients/growatt-vn/catalog → Source filter chips + badges
# - seed a BCCT row with new code, refresh catalog → ⚠ alarm + filter
```

## Sprint B (continuing autopilot)

Sprint B will be in a separate session log (this one closes when A
ships). Plan from here:

1. B0 — survey BCQT-System for LLM optimization, notification, and
   chat-agent patterns. Output 3 short briefs.
2. B1 — notification system. Build it in Data Hub more refined than
   what's in BCQT-System.
3. B2 — chat-agent with strict ACL (LLM cannot access data outside
   the user's authorized scope).
4. B3 — SSO (M9 deliverable #4) if runway permits.

Pacing target: 10:30 AM SGT close. As of A complete: 03:26, ~7h runway.
