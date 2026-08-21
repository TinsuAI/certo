# Session: 2026-05-02 — Client-config refactor (Hướng B)

Continuation from `2026-05-02-co-api-contract-agent-guardrails.md`. The
previous session shipped CO contract guardrails + a deprecation plan for
`co-config`. This session executed the rename + master-data extraction
end-to-end, plus built the cross-app change-notification mechanism the
user explicitly asked for.

11 pieces, 3 commits, 1 UX iteration after manual test feedback.

## What was done

### Discovery
- `/discover` produced
  `.ai/features/2026-05-02-client-config-refactor-and-contract-versioning.md`.
- Read the CO codebase carefully: found 3 real `config.json` files
  (`growatt`, `do-thanh`, `johnson`) under
  `barry-CO-main/data/local/client-config/clients/*/`. CO already had a
  full UI at `/clients/{id}/config` and store at
  `app/client_config_store.py` — meaning Data Hub UI was net-new, not a
  re-skin. Drove the architecture conversation toward Hướng B1 (Data Hub
  builds new UI for master fields; CO drops the master rows from its
  UI; CO keeps Nhóm B runtime fields).
- Resolved 5 open questions inline with the user before coding:
  backfill from CO JSON (yes, automatic), grace window (2 weeks fixed),
  BCQT pre-emption (only `fiscal_year_start_month`), notification
  granularity (only `## Breaking:` entries), seed location
  (`data/seeds/`).

### Schema + storage (Piece 1, commit `d29c0a3`)
- Migration 019 creates 3 tables: `hub.declaration_type_catalog`,
  `hub.client_type_presets`, `hub.client_config`. Schema-only — no
  inline seed.
- Seeds at `data/seeds/declaration_types.yaml` (20 codes — 12 import +
  8 export, sourced from existing CO codebase + Thông tư 38/2015) and
  `client_type_presets.yaml` (4 system: dncx/sxxk/gia_cong/manual).
- `app/seed_master_data.py` — idempotent loader called from app
  startup AFTER `apply_migrations()`. Skips if target table is non-empty.
- Stores: `app/stores/{declaration_types,client_type_presets,client_config}.py`.
  Key invariants in `client_config.upsert()`: bumps `config_version` on
  content change, computes `config_hash = sha256(canonical_json)[:16]`,
  no-op save (same hash) does NOT bump version. `apply_preset()` is
  snapshot — copies preset's CURRENT defaults into the client row.
- `pyyaml>=6.0.3` added to deps.
- 14 unit tests in `tests/test_client_config.py` cover seed load, CRUD,
  snapshot-no-cascade (verified by mutating preset after apply), no-op
  save, normalization (case + whitespace + dedup), system-preset delete
  guard, fiscal year validation.

### Admin UIs (Pieces 2 + 3)
- `app/routes/master_data.py` — routes for
  `/admin/declaration-types` (list/add/inline-edit/disable) and
  `/admin/client-type-presets` (list/add/inline-edit/delete).
- Templates `app/templates/admin/{declaration_types,client_type_presets}.html`.
- Linked from `/admin/users` page header.
- System preset delete is store-level guarded (raises ValueError);
  template hides delete button for system presets. Belt-and-suspenders
  intentional.

### Per-client UI (Piece 4)
- `app/routes/client_config_ui.py` mounted at
  `/clients/{id}/declaration-config`. Two POST endpoints:
  `/declaration-config` for manual save, `/declaration-config/apply-preset`
  for snapshot-from-preset.
- Template uses checkbox grid for declaration types (one cell per code,
  multi-column auto-fit).
- Initial CSS bug — `.checkbox-grid` had no rule defined, codes
  rendered inline-crammed. **User flagged in manual test.** Added
  proper grid CSS (`app/static/css/app.css:2250+`) with
  `repeat(auto-fit, minmax(280px, 1fr))` + cell hover/checked states +
  dark-mode variants.

### API (Pieces 5 + 6 + 7)
- `GET /v1/hub/dncxs/{id}/client-config` — new, slimmed shape (master
  fields only; no `co_stock`, no `allocation_code`).
- `GET /v1/hub/dncxs/{id}/co-config` — kept serving but with
  `Deprecation: true`, `Sunset: Sat, 16 May 2026 00:00:00 GMT`,
  `Link: rel="successor-version"` headers (RFC 8594). Master fields now
  read from `hub.client_config`; CO-runtime fields keep returning
  hardcoded placeholders during grace.
- `GET /v1/hub/dncxs/{id}/source-summary` — dropped
  `co_stock_row_count` + `co_stock_row_count_semantics` entirely.
  `client_config` sub-payload reshaped to match `/client-config`.
- `docs/API_CONTRACT.md` updated: new "Client Config (master data)"
  section + deprecated `co-config` section.
- Test fixture `test_client_config_and_source_summary_endpoints`
  rewritten to assert new shape + headers.

### Operations (Piece 8 + 9, commit `e2d116e`)
- `docs/API_CHANGELOG.md` — append-only changelog with explicit
  heading conventions (`## YYYY-MM-DD — Breaking|Additive|Cosmetic:`).
  Only `Breaking:` entries trigger notifications. First entry documents
  the rename + sunset.
- `app/notifications.py:notify_api_contract_changed()` — fan-out helper
  reading the user table for active dev/admin users.
- `scripts/announce_breaking_change.py` — CLI parses latest Breaking
  entry, fires notify_many. Dry-run by default; `--confirm` to send.
- `scripts/backfill_client_config_from_co.py` — reads CO JSON files
  via curated `CLIENT_ID_MAP` (`growatt` → `growatt-vn`, etc.), seeds
  `hub.client_config` rows. Idempotent: skips clients already
  configured. Already applied: 2 clients seeded; johnson-vn skipped
  (had a manual config from Piece 4 testing).

### Coordination (Piece 10 + 11)
- `.ai/sister-app-notes/2026-05-02-co-migrate-to-client-config.md` —
  detailed migration steps for a CO agent to execute in
  `barry-CO-main`: switch endpoint, drop master rows from CO UI, move
  CO-runtime config to local store only, update test fixtures.
- `.ai/sister-app-notes/2026-05-02-bcqt-client-config-available.md` —
  one-page note for BCQT to add to its DECISIONS.md.
- `.ai/scheduled/2026-05-16-remove-co-config.md` — removal artifact
  with pre-conditions + execution steps + post-execution cleanup. NOT
  auto-scheduled. User runs `/schedule` if desired.

### Manual test feedback iteration
User reported 2 issues during manual test:
1. **Checkbox grid was inline-crammed** → Fixed via CSS (see Piece 4).
2. **Apply preset → manual edit should clear preset_key** → User
   wants "tự cấu hình" semantics. Fixed: `POST /declaration-config`
   route now hardcodes `preset_key=None` regardless of submitted form
   value. Added hint in zone-head + a regression test
   (`test_apply_preset_then_manual_edit_clears_preset`).

## Decisions made

- **YAML over XML for seeds.** User suggested XML; recommended YAML
  because the project is Python-only, no XML tooling, YAML diffs cleaner
  in PR review.
- **Snapshot semantics, not live FK.** When client picks preset, copy
  defaults into client row. Subsequent preset edits do NOT cascade.
  Reason: contract stability — sister apps cache by `config_hash`; a
  preset edit silently flipping every client's hash at once would
  invalidate every consumer cache without per-client audit. Manual
  re-apply is explicit.
- **System presets non-deletable.** Seeded presets (`dncx`/`sxxk`/etc.)
  protect the foundation. Can disable or edit, not delete.
- **Manual save = self-config (preset_key cleared).** Any submission
  through the "Lưu cấu hình" button drops the preset link, even if
  values match preset defaults. Re-establishing the preset link
  requires the explicit Apply-preset button.
- **Notification on `## Breaking:` only.** Additive + Cosmetic entries
  silent. Sister-app dev/admin users would tune out notifications if
  every doc edit fired one.
- **Grace window 2 weeks fixed (Sunset 2026-05-16).** Not tied to CO's
  release cycle to avoid open-ended deprecation.
- **`fiscal_year_start_month` only for BCQT pre-emption.** Rejected
  speculative additions (BCQT column mappings = BCQT runtime,
  `customs_unit_code` = no concrete demand). Avoid bloating the shared
  master schema.
- **3-commit split.** (1) backlog updates, (2) feature code, (3) ops +
  coordination. Each independently revertable. Single feature commit
  for the schema+UI+API because reverting parts mid-stack would orphan
  references.
- **No /schedule for the removal agent.** User-driven action; the
  removal artifact in `.ai/scheduled/` is the dropping-off point.

## What didn't work / surprises

- **Initial brief recommended Hướng B but underspecified UI ownership.**
  Had to re-read the CO codebase mid-discovery when user pointed out CO
  already has a working config UI. Resulted in a sharper Hướng B1 vs B2
  vs B3 framing — the user picked B1.
- **`preset_key` hidden input in the form was wrong.** First template
  pass passed `preset_key` through hidden input on save → manual
  edits preserved the preset link incorrectly. Fixed by removing the
  hidden input + making the route always set `preset_key=None` on
  manual save path.
- **Checkbox grid CSS was missing entirely.** Added template classes
  (`checkbox-grid`, `checkbox-cell`) without verifying the CSS file
  contained matching rules. User caught it on first browser render.
  Lesson: when introducing new template CSS classes, grep the
  stylesheet for matching definitions before declaring the UI done.
- **Manual edit semantics ambiguous in initial design.** First version
  preserved `preset_key` through hidden input on every form submit. The
  user articulated the right semantic clearly: snapshot-then-edit ≠
  preset-membership. Made the implementation match: preset_key only set
  via the dedicated apply-preset path.
- **Backfill name mapping.** CO uses `growatt`/`do-thanh`/`johnson`;
  Data Hub uses `growatt-vn`/`do-thanh-vietnam-2614`/`johnson-vn`.
  Hardcoded `CLIENT_ID_MAP` in the backfill script. If a future CO
  client isn't in the map, the script skips with a warning rather than
  guessing.
- **Hub.users LEFT JOIN edge case for service-account audit.** When
  notifications fire from the script, no user_id is set, so updates
  go in as 'system'. Acceptable for now; will be cleaner once
  service-account JWTs land (see backlog).

## Open items

Carried forward to STATUS.md "Next Steps":

1. CO migration PR — agent picks up
   `.ai/sister-app-notes/2026-05-02-co-migrate-to-client-config.md`.
2. BCQT one-line entry in its DECISIONS.md.
3. Schedule `/co-config` removal after CO confirms cutover.
4. Decide whether to overwrite johnson-vn config from CO (currently
   has the `sxxk` config from manual testing, not the original
   `manual` from CO).
5. Earlier backlog items unchanged: dev-permissive read auth
   promotion, service-account JWTs.

## How to resume

```bash
cd ~/workspace/client/data-hub
uv run uvicorn app.main:app --host 127.0.0.1 --port 8754 --reload
# admin@data-hub.local / admin123

# Tests
uv run pytest -q                                   # 219 passed

# UI smoke
# /admin/declaration-types       — catalog
# /admin/client-type-presets     — presets
# /clients/johnson-vn/declaration-config  — per-client editor

# API smoke
TOKEN=$(curl -sf -X POST http://127.0.0.1:8754/v1/auth/token \
  -H "Content-Type: application/json" \
  -d '{"email":"admin@data-hub.local","password":"admin123"}' \
  | python3 -c 'import sys,json; print(json.load(sys.stdin)["access_token"])')
curl -sf http://127.0.0.1:8754/v1/hub/dncxs/johnson-vn/client-config \
  -H "Authorization: Bearer $TOKEN" | python3 -m json.tool
curl -sfi http://127.0.0.1:8754/v1/hub/dncxs/johnson-vn/co-config \
  -H "Authorization: Bearer $TOKEN" | head -10  # check Deprecation header

# Notification flow (already fired once this session)
uv run python scripts/announce_breaking_change.py            # dry-run
uv run python scripts/announce_breaking_change.py --confirm  # send

# Backfill (already applied; idempotent re-run)
uv run python scripts/backfill_client_config_from_co.py --confirm
```

Database state: 20 declaration types (catalog), 4 system presets, 3
clients with non-empty client_config rows, 1 fired
`api_contract_changed` notification in `hub.notifications`.
