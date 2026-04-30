# Session Summary: 2026-05-01 — Autopilot MVP scaffold

## What was done

User invoked autopilot mode to build a working web app + API matching barry-CO-main UX (excluding CO dossier workflow), with file-upload + storage, and SSO. User went to sleep mid-session expecting to wake up to a running app.

**Day's design work** (before autopilot):
- Read CO + BCQT-System `.ai/DECISIONS.md`, ran 2 audit subagent passes (CO + BCQT schema reconstruction).
- Wrote discovery brief + read-API contract; ran 3 critique rounds via `/critic` agent.
- Locked architecture amendments: BCCT single-writer for MVP, BOM proposal-queue (auto-only), two-axis (actor, intent) provenance, point-of-use binding for BCCT→BOM, tracking-code-mode dual-code reality (per-DNCX immutable + N-N code_mappings + Growatt batch-aggregate resolver).
- Verified design assumptions against `barry-CO-main` and `bcqt-growatt` actual code via Explore agents — discovered `code_system_mode` is decorative in CO, RVC threshold modification doesn't exist yet (greenfield in Data Hub), CO has no HTTP API (auto-rule criterion #2 dropped from MVP), and Growatt's actual N-N algorithm in `bcqt-growatt/settlement/code_map.py` (ported verbatim).

**Autopilot build** (this session):

Wave 1 — Foundation + Schema (commit `scaffold`):
- `pyproject.toml` (Python 3.12, FastAPI, Jinja2, psycopg, argon2, openpyxl, uv).
- 6 SQL migrations: `dncxs/users/sessions`, `materials`, `code_mappings + resolutions`, `file_uploads`, `bcct_rows`, `bom (8 tables incl. proposal queue)`.
- Migration runner ported verbatim from CO; `hub` schema enforced.
- Routes scaffold: 5 entity routers + auth + theme.

Wave 2 — Auth + DNCX (same commit):
- Argon2 password hashing, session cookies, seed admin.
- DNCX list/new/edit/detail with `code_resolution_mode` immutability.

Wave 3 — Parsers + uploads + screenshots (commit `wave3`):
- Excel parsers for Materials, BQD, BCCT (with Growatt regex inherited verbatim from `bcqt-growatt/settlement/load.py`), BOM (3 profiles).
- LocalFS storage backend with `FileBackend` interface for S3 phase 2.
- BOM proposal queue with 5-condition auto-rule + composite normalized_hash idempotency.
- 23 pytest tests (Growatt regex parity, parsers, idempotency).
- Playwright screenshot script for 12 light + 4 dark pages.

Wave 4 — Resolver + JSON API (commit `wave4`):
- Code resolution worker porting Growatt's NB↔HQ algorithm (identity, bqd_unique, bcct_qty_pick, fallback bases). Triggers post-upload + manual button.
- 11-endpoint public read API at `/v1/hub/...` with bearer token auth.
- 5 resolver tests (28 passing total).

Wave 5 — Audit views + nav extension (commit `wave5`):
- `/proposals` list + `/proposals/{id}` detail with full audit trail (failed_conditions, context, proposed rows).
- Code mappings page now shows BQD pairs + Resolutions panels side-by-side.
- Top nav extended; screenshots refreshed.

Wave 6 — Uploads audit (this commit):
- `/uploads` page filterable by DNCX + module; shows parse_status, error messages.

## Decisions made (locked, see `.ai/DECISIONS.md`)

1. Tech stack inherited from CO without debate (FastAPI/Jinja/psycopg/raw SQL).
2. BCCT writes only from Data Hub UI in MVP (no CO write-back yet).
3. BOM writes only via proposal queue (auto-only MVP; manual + hybrid phase 2).
4. Per-deployment `bom_proposal_mode` config; per-DNCX `code_resolution_mode` immutable.
5. Auto-rule criteria are speculative and to be tuned against first real CO modification flow.
6. Code mappings store N-N via composite PK; resolutions materialized via batch-aggregate algorithm (Growatt port).
7. Two-axis BOM provenance (`actor`, `intent`); `latest` is a query, not state; tombstoning replaces deletion.
8. BCCT row carries `bom_version_id` for point-of-use binding (not yet auto-populated; reserved for first BCCT-from-shipment flow).

## What didn't work / open

- `_PAT_F1` Growatt regex doesn't match all real-world goods-name shapes (`CU-WIRE-2.A1` failed because of dashes). The verbatim regex from `bcqt-growatt` works for the standard `#&` prefix pattern. Real Growatt data may need additional patterns; defer until validated against actual files.
- `code_resolution` runs synchronously inside the upload handler. Will block on big uploads. Background job needed.
- Bearer token auth on the public API accepts any non-empty token in MVP. Real JWT scope check is part of phase-2 SSO design.
- No cross-app SSO yet. Current auth is single-deployment, single-agency.
- BOM `growatt_multi_workbook` and `johnson_sap_exploded` profile parsers exist but only `manual_flat` was tested end-to-end against synthetic data.

## Open items for next session

1. **Test against real Growatt data** at `~/workspace/client/bcqt-growatt/data/`. Validate parsers + resolver at scale.
2. **SSO design pass** (M9 deliverable #4) — token model, cross-app cookie sharing, role/scope matrix.
3. **Service-discovery** for auto-rule criterion #2 (CO case validation) — currently dropped; reinstate when CO API exists.
4. **Manual + hybrid review modes** for BOM proposals (phase 2 per epic plan).
5. **Background resolver job** to avoid blocking uploads.
6. **Production deployment** (M9 deliverable #6) — systemd, pg_dump backup, reverse proxy.

## How to run

```bash
cd ~/workspace/client/data-hub
uv sync
sudo -u postgres createdb data_hub -O vp 2>/dev/null  # if not done
uv run uvicorn app.main:app --port 8754
# Open http://127.0.0.1:8754, login admin@data-hub.local / admin123
uv run python scripts/seed_demo.py    # upload synthetic Growatt data
uv run python scripts/screenshot.py   # capture UI to data/screenshots/
uv run pytest                          # 28 tests
```

## Files of note

- `app/main.py` — app + auth + theme (~140 lines)
- `app/auth.py` — argon2 + session cookie + seed (~140 lines)
- `app/database.py` — migration runner ported from CO
- `app/routes/{api,bcct,bom,code_mappings,dncxs,materials,proposals,uploads}.py`
- `app/parsers/{bcct,bom,code_mappings,goods_name,materials}.py`
- `app/stores/{bom,code_resolution,uploads}.py`
- `app/storage/__init__.py` — FileBackend interface + LocalFSBackend
- `db/migrations/001-006_*.sql`
- `tests/test_*.py` — 28 tests
- `scripts/seed_demo.py` — synthetic Growatt-shape Excel uploads
- `scripts/screenshot.py` — Playwright UI capture
- `data/screenshots/*.png` — 16 light + 4 dark UI screenshots

## What looks good in screenshots

- DNCX list (light + dark) with mode tags
- Materials list with category filter, populated table for Growatt
- Code mappings with BQD + Resolutions panels
- BCCT list with internal_code parsed from Growatt-style goods names
- BOM versions list showing parent + co_modified child
- Proposals list with 1 approved + 2 rejected (audit trail)
- Proposal detail with failed_conditions + context + proposed rows
- Login screen
