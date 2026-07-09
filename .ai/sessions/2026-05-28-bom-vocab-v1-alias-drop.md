# 2026-05-28 (evening) — BOM vocab v1 URL alias drop (BACKLOG C.3)

Short follow-up session on top of the PM CO-API-trio shipment. User
picked C.3 off the STATUS Next Steps list. ~30-minute job as the
BACKLOG entry estimated.

## What Was Done

Closed BACKLOG entry C.3 "Drop BOM vocab v1 aliases" end-to-end in
one commit `b7f5081` pushed to main and auto-deployed to demo.

**Removed:**

- `_alias_artifact_detail` handler — `app/routes/bom.py` (was
  `GET /clients/{c}/bom/version/{id}` → 308 → `.../bom/artifact/{id}`).
- `_alias_artifacts_list` handler — `app/routes/bom.py` (was
  `GET /clients/{c}/bom/{p}/versions` → 308 → `.../bom/{p}/artifacts`).
- `_alias_api_bom_versions` handler — `app/routes/api.py` (was
  `GET /v1/hub/products/{p}/bom/versions` → 308 →
  `.../bom/artifacts`).
- 3 redirect tests in `tests/test_bom_vocab_rename.py` (schema +
  ID-prefix tests retained per the file's own ship plan).
- Section `#### GET /v1/hub/products/{p}/bom/versions` in
  `docs/API_CONTRACT.md`.

**Added:**

- Breaking changelog entry in `docs/API_CHANGELOG.md` dated
  2026-05-28 — fires `api_contract_changed` notification to CO +
  BCQT operators.
- Sister-app note
  `.ai/sister-app-notes/2026-05-28-bom-vocab-v1-aliases-removed.md`
  + INDEX entry + INDEX "Open coordination items" closed.

**Modified:**

- `.ai/BACKLOG.md` C.3 entry collapsed to a SHIPPED line.

**Verified:**

- `uv run pytest -q` → 1,260 passed, 15 skipped (`−3` from 1,263).
- Local dev server `:8754`: 3 alias paths return 404, canonical
  `.../artifacts` paths return 401 (auth-required, alive).
- Demo `100.84.189.87:8754` post-deploy: alias path returns 404,
  healthz 200, `git log -1` at `b7f5081`.

## Decisions Made

**Removal trigger #2 ("zero alias hits in 24h server logs")
was treated as evidence-gated rather than strictly verifiable.**
The BACKLOG entry assumed long-lived server logs; demo reality is
`restart: unless-stopped` containers that lose stdout history on
every CI deploy, and nginx access.log is `www-data:adm 0600` with no
sudo for the deploy user. Decided to ship anyway because:

1. The only callers that could hit these paths are sister apps —
   `grep -rn "bom/version\|bom/versions"` in `barry-CO-main/app` and
   `BCQT-System/app` returned zero hits each.
2. Aliases lived 3 weeks (2026-05-07 → 2026-05-28) — longer than
   the "one release grace" commitment in the original brief.
3. Demo is internal-only, so external-bookmark risk is bounded to
   Tinsu staff browser tabs which 404 recovers from gracefully.

User opted for "drop now (A)" over "wire structured log persistence
then wait 24h (B)" after I surfaced the trade-off.

**Changelog category = Breaking, not Cosmetic.** The aliases
returned 308 yesterday and return 404 today. That's a status-code
change that breaks any caller still on the old URL. Used the
`Breaking:` heading so the in-app notification system fires for CO
+ BCQT operators. (No actual code-side breakage expected since both
consumers were grepped clean, but the contract status is what
triggers notification, not actual breakage observed.)

**Kept the test file alive, didn't delete it.** The file has 5
retained tests (schema rename + ID prefix) that should stay
forever — they're the canary against accidental schema regression.
Updated its docstring to reflect what's there now.

## What Didn't Work

**Pre-flight log grep on demo turned up nothing useful.** Tried:

- `docker logs data-hub-app-1 --since 48h` — returned 7 lines.
  Container had been started 9 min ago by an unrelated restart.
- `/var/log/nginx/access.log` — currently empty since May 14,
  rotated copies require root.
- No application access-log file is volume-mounted.

This is the gap that drove the "evidence-gated rather than strict"
decision above. If we ever want strict log-based removal triggers,
need a persistent access-log volume on demo first.

**First server-restart attempt left workers up with stale code.**
After editing the routes and running `kill $(pidof uvicorn)`, the
alias path still returned 308. Diagnosed: only the master process
was killed; one of the existing data-hub workers (started 2 days
ago at PID 877047) had not been picked up by `pidof`. Fixed by
`pkill -f "uvicorn app.main:app --host 127.0.0.1 --port 8754"`
(narrow pattern — there are sister-app uvicorns running on :8000,
:8001, :8200 that must NOT be touched).

## Open Items

- **Persistent demo access log** would be useful infrastructure
  for future alias-drop / endpoint-deprecation cycles. Not urgent
  enough to file as a backlog item right now; remember if/when the
  next removal trigger needs it.
- **CO + BCQT migration was already done** by the time this ran —
  good. If a future renaming pass ships with a similar grace, the
  pre-flight grep in consumer repos is the strongest evidence we
  have given the demo log gap.
- **Container restart count** — `data-hub-app-1` shows `restarts=0`
  + uptime ~9 min when checked. That's consistent with
  `restart: unless-stopped` not having had to restart, but the
  uptime is the GitOps deploy boundary, not container health. Just
  noting for next session — restart count alone is not a reliable
  "has been stable since the last deploy" signal.
