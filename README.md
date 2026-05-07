# Data Hub

Tinsu AI master records management product for customs compliance agencies.
One of three apps in the Tinsu AI portfolio (Data Hub + BCQT-System + CO-System).

**Status:** MVP scaffold (2026-05-01). Core CRUD + uploads + read API working.

## Quick start

Postgres must be running locally.

```bash
sudo -u postgres createdb data_hub -O $USER  # one-time
uv sync
uv run uvicorn app.main:app --port 8754
```

Open http://127.0.0.1:8754. Default admin: `admin@data-hub.local / admin123`
(set via `DATA_HUB_SEED_EMAIL` / `DATA_HUB_SEED_PASSWORD` env vars).

### Demo data

```bash
uv run python scripts/seed_demo.py    # synthetic Growatt-shape uploads
uv run python scripts/screenshot.py   # Playwright UI capture → data/screenshots/ (gitignored)
```

### Tests

```bash
uv run pytest    # 28 tests (parsers + idempotency + resolver)
```

## Architecture

- **Stack:** Python 3.12 + FastAPI + Jinja2 + psycopg 3 + Postgres + raw SQL migrations.
- **Auth:** session-cookie based, argon2 password hashing.
- **Storage:** `FileBackend` interface; LocalFS implementation. S3-compat phase 2.
- **Schema:** single `hub` Postgres schema, role-per-app deferred to phase 2.

## Modules

| Module | Routes | Purpose |
|---|---|---|
| DNCX | `/dncxs/*` | Master directory of customer enterprises |
| Materials (Danh Mục) | `/materials/*` | NVL/SP/BTP registry per DNCX |
| Code mappings (BQD) | `/code-mappings/*` | N-N internal↔customs code translation per DNCX |
| BCCT | `/bcct/*` | Customs declaration registry |
| BOM | `/bom/*` | Bill of materials with 8-table versioning |
| Proposals | `/proposals/*` | BOM-write proposal audit trail |
| Uploads | `/uploads` | File-upload audit log |
| API | `/v1/hub/*` | JSON read API for sister apps (bearer auth) |

## Read API

Bearer token auth. 11 endpoints under `/v1/hub/`:

```
GET  /v1/hub/dncxs
GET  /v1/hub/dncxs/{dncx_id}
GET  /v1/hub/materials?dncx_id=X[&category=][&status=]
GET  /v1/hub/materials/{customs_code}?dncx_id=X
GET  /v1/hub/bcct?dncx_id=X[&year=][&direction=][&declaration_no=]
GET  /v1/hub/bcct/{transaction_key}?dncx_id=X
GET  /v1/hub/code-mappings?dncx_id=X
GET  /v1/hub/code-mappings/resolutions?dncx_id=X
GET  /v1/hub/products?dncx_id=X
GET  /v1/hub/products/{product_code}/bom/latest?dncx_id=X
GET  /v1/hub/products/{product_code}/bom/versions?dncx_id=X[&actor=][&intent=]
GET  /v1/hub/products/{product_code}/bom?dncx_id=X[&artifact_id=]
GET  /v1/hub/proposals/{proposal_id}
POST /api/v1/hub/products/{product_code}/bom/proposals
```

## Environment

```
DATA_HUB_DATABASE_URL=postgresql:///data_hub
DATA_HUB_FILES_ROOT=data/files
DATA_HUB_SEED_EMAIL=admin@data-hub.local
DATA_HUB_SEED_PASSWORD=admin123
```

## Documentation

- `.ai/STATUS.md` — current state + next steps
- `.ai/DECISIONS.md` — architecture decisions (BCCT single-writer, BOM proposal queue, etc.)
- `.ai/features/epic-2026-05-01-data-hub-mvp.md` — full MVP plan + waves
- `.ai/features/2026-05-01-data-hub-read-api.md` — read-API contract design
- `.ai/sessions/` — session summaries
- `~/workspace/client/BCQT-System/.ai/DECISIONS.md` "2026-04-30 PM — Data Hub 3-app architecture" — canonical architecture decision (with 2026-05-01 BCCT amendment)
