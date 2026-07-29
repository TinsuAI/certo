# Operator Runbook

Operational knowledge for running, deploying, diagnosing, and hand-seeding CO in production and
nightly. Consolidated from `.ai/STATUS.md` ("Notes for Next AI Session") and `CLAUDE.md`. This is a
reference, not a change log — when an operational fact changes, update it here.

Conventions used below:
- **Host alias `tinsu`** — the deploy host reached via `ssh tinsu` (SSH config on the operator box).
- **Prod app** — `barry-co` (hostname `barry-co.tinsu.ai`), container `co-app-1`.
- **Nightly app** — `demo-co` (hostname `demo-co.tinsu.ai`), container `nightly-co-app-1`.
- Container names and hostnames are documented here but must be re-vetted before any in-container write
  (see each op). No credentials or service tokens appear in this file.

---

## 1. Deploy & verify

Deploy is CI/CD-driven from `origin/main`. Do not deploy by hand.

1. Merge / push to `origin/main` (via the normal PR flow; pushing `main` from the operator box triggers
   prod CD — `git-guardrails` gate `ask`s before `git push` / `gh pr merge`).
2. CI/CD runs build → tests → the **`Deploy demo`** job. When green, both prod `barry-co` and nightly
   `demo-co` are advanced to the pushed `git_sha`.
3. Verify each host reports the expected commit:
   - Prod: `curl -s https://barry-co.tinsu.ai/version`
   - Nightly: `curl -s https://demo-co.tinsu.ai/version`
   Check `git_sha` matches `origin/main`. The endpoint also returns `build` timestamp. `/version` is served
   by `app/routers/pages.py:38`; `git_sha` comes from the `CO_GIT_SHA` env baked at build time
   (`app/version.py:53`).
4. Docs-only commits still advance `git_sha` (CI re-runs `Deploy demo` with no app change), so a `git_sha`
   bump after a docs push is expected and harmless.

### CI-skip-token hazard

Never put the GitHub Actions CI-skip directive (the bracketed skip token) **anywhere** in a commit
message — not quoted, not negated, not inside prose or a `grep` example. GitHub matches the token anywhere
in the message and skips the **entire** pipeline, so the deploy never runs and prod stays on the old
commit. If you must refer to it in a commit body, do not spell it literally. (Memory:
`ci-skip-token-in-commit-msg`.)

Related git-message hazard: the local guardrail hook substring-matches the whole command string, so a
`git commit -m` whose message merely *names* a blocked pattern (e.g. `reset --hard` in prose) is blocked
too. Work around it with `git commit -F <file>`.

---

## 2. Prod perf diagnosis (read-only in-container harness)

Reusable pattern that root-caused the 2026-07-27 case-open 524 (measured 124.88s / 74 BCCT pages) and
verified the fix live (0.31s shipment path, 15.69s substitute path). Use it to measure a cold DH-backed
path inside the prod container, before and after a change, without mutating any case.

Why in-container and not over HTTP: prod is behind SSO, so an external HTTP probe cannot reach a guarded
route. Run the route's underlying pull logic directly in the container instead.

Why not the access log: the app access log has **no** request duration, and a Cloudflare 524 still logs
`200 OK` once the origin finally finishes. Do not use the access log to time slow requests.

### Harness shape

`ssh tinsu` → `docker exec -i co-app-1 /app/.venv/bin/python -` piping a short script that:
1. builds a client with `data_hub_client_from_env()` (`app/data_hub_client.py:1067`) — this picks up the
   prod service token from the container's config file, no token in the harness;
2. wraps `client._get` (`app/data_hub_client.py:509`) to count HTTP calls per path and time each call;
3. calls the pull under test, then prints per-path call counts and total wall time.

Template (adapt per investigation — this exact script is **not** checked in; **UNVERIFIED — confirm the
call signature and client shape against current `app/data_hub_client.py` before running**):

```python
import time, collections
from app.data_hub_client import data_hub_client_from_env

client = data_hub_client_from_env()
counts, times = collections.Counter(), collections.Counter()
_orig = client._get
def _timed(path, params=None):
    t = time.perf_counter()
    r = _orig(path, params)
    dt = time.perf_counter() - t
    counts[path.split("?")[0]] += 1
    times[path.split("?")[0]] += dt
    return r
client._get = _timed

# resolve the target client/case dicts, then call the read-only pull under test, e.g.:
#   client.co_case_source_context(client_dict, case_dict, skip_heavy_context=True)
#   client.origin_invoice_matches(client_dict, case_dict, client_config)
#   client.material_catalog(client_dict)

for p, n in counts.most_common():
    print(f"{n:4d}  {times[p]:7.2f}s  {p}")
```

### Read-only-safe vs write

Safe to call on prod (they only read from Data Hub, no case-record write):
- `co_case_source_context` (`app/data_hub_client.py:872`)
- `origin_invoice_matches` (`app/data_hub_client.py:956`)
- `material_catalog` (`app/data_hub_client.py:858`)

**Never on prod:** `preload_co_case_origin_context` (`app/routers/co_case.py:289`) — it **writes** the case
record (persists `source_snapshot`). Running it on prod mutates real johnson-vn case state.

### Engineering lesson

When a narrow replacement for a heavy DH pull is introduced, audit **every** call site of the heavy pull.
The origin tab moved to `origin_invoice_matches` in 2026-05, but the shipment light path and the substitute
modal each kept the full `co_case_source_context` pull for over a year — two separate 524s from the same
root omission.

---

## 3. Data safety

- **Prod holds real agency data** — johnson-vn cases and Growatt cost-allocation live in prod `co-db-1`.
  **Never seed or test against prod.** Use nightly (`demo-co`) or a local dev DB for any experiment.
- **Local dev = auth-off + DB-mode.** `.env` sets `CO_AUTH_REQUIRED=0`, `BARRY_DATABASE_URL` → local
  Postgres `barry_co`, `DATA_HUB_ENABLED=1` → local Data Hub on `:8754`. Start with `npm run co:serve`
  (uvicorn `--reload` on `:8001`, watches `app/` `*.py`/`*.html`/`*.css`).
- **Nightly is the safe target** for any in-container write experiment. Run it on nightly first, confirm,
  then prod.
- The local `barry_co` DB uses schema `co` — `psql` needs `set search_path=co;`. The `public` schema is
  stale legacy data that looks plausible but is not what the app reads. (Memory:
  `local-barry-co-db-schema-co`.)
- Test env split: full file-mode (no `.env`) runs the pure suite; DB-mode and in-container e2e need `.env`.

---

## 4. Common ops

### Refresh tồn (co_stock re-derivation)

The "Refresh tồn" action re-materializes a client's `co_stock` snapshot. It normally takes the **delta**
path and does not rewrite unchanged rows. It is forced to a **full** re-derivation when the config
fingerprint (`co_config_fingerprint`, hashing the CO-owned `allocation_code` + `co_stock` sections) or the
derivation schema version changes — that is the self-healing mechanism behind the allocation-strategy seed
and the suppliers-screen backfill. The programmatic entry point is `_refresh_co_stock_delta_or_full(client)`
(`app/web/co_case_context.py:3683`), over `refresh_co_stock_for_client` (`app/co_stock_materializer.py:78`).

Cold-start note for a newly seeded demo company: after the company first appears in CO, run Refresh tồn
once, or "thiếu đơn giá" will block Chốt. (Memory: `demo-company-seed-co-datahub`.)

### Run the growatt-vn allocation seed in-container

Script: `scripts/seed_growatt_vn_allocation.py` (on `origin/main` since `b98156a`; the calibrated regex
version). It flips growatt-vn's CO-owned allocation strategy to `description_regex` with the calibrated
pattern `\(\s*([A-Z0-9]+\.[A-Z0-9]+)\s*\)`, then forces one full co_stock re-derivation. Idempotent — a
no-op when strategy/regex/fallback already match the target.

`scripts/` is **not** in the Docker image, so run it piped over stdin (the script is stdin-safe and does
not import the code default):

```
docker exec -i co-app-1 /app/.venv/bin/python - < scripts/seed_growatt_vn_allocation.py           # prod
docker exec -i nightly-co-app-1 /app/.venv/bin/python - < scripts/seed_growatt_vn_allocation.py    # nightly
```

Run via `ssh tinsu`. Pull a fresh checkout on the operator box first so the piped file is the `origin/main`
version.

**Vet before running (mandatory):**
1. Confirm the container names are still `co-app-1` / `nightly-co-app-1` (`docker ps` on `tinsu`) —
   **UNVERIFIED from this repo; confirm before running.**
2. Check growatt-vn for **locked cases** — the full re-derivation rewrites stock `allocation_code`, which
   changes what locked claims resolved against. As of the seed date growatt-vn had 0 cases / 0 claims, so
   there was nothing to orphan; re-confirm this is still true before running.
3. Seed **nightly first**, confirm, then prod. johnson-vn is untouched by this seed (it must stay
   `same_as_customs_code`).

Optional flags: `--client <id>` (default `growatt-vn`), `--no-refresh` (save config but skip the forced
re-derivation; the next Refresh tồn will then go full).

### Flag VN-origin NCC on the suppliers screen

For growatt-vn only, flag its two Vietnam on-spot suppliers (Phụ lục X, pure E15) so their materials get
VN-origin treatment. Screen: `/clients/growatt-vn/suppliers`
(`app/routers/pages.py:356`; flip POST at `:372`).

Flag these two:
- `CONG TY TNHH MINGJIE VIET NAM`
- `CONG TY TNHH MINGHUI VIET NAM`

**Verify each spelling against the live BCCT `consignee_name`** before flipping — flag the exact string as
stored. **Never flag the Hong Kong namesake `MINGJIE INDUSTRIAL (HK)`** — it is a distinct supplier and
must stay unflagged.

Johnson = **0** flagged suppliers (all-VNM treatment is correct for Johnson). This is a manual UI step, not
a seed script (two rows). (Memory: `vn-origin-materials-are-e15-onspot-imports`.)

### Rollback (allocation strategy)

To revert the growatt-vn allocation seed: set the strategy back to `same_as_customs_code` and run Refresh
tồn. The config fingerprint mismatch forces a full re-derivation back to the old codes. For growatt-vn
there was no case/claim state to unwind at seed time — re-confirm that before relying on this.

---

## 5. Known pending manual steps (from STATUS)

These are user-manual production ops, not code. They are the only open items on the growatt-vn onboarding
track as of 2026-07-30. Verify current state before acting — STATUS may have advanced.

1. **Run the calibrated regex seed on prod + nightly.** `scripts/seed_growatt_vn_allocation.py` (`b98156a`,
   calibrated regex) has been applied **locally only**. Prod and nightly growatt-vn ran an earlier seed
   (2026-07-17 AM, `d74e8fb`) that set `description_regex` with the **broad** default pattern, which
   over-matches lot descriptions carrying two parentheticals (a manufacturer part number plus the internal
   code) and blanks those lots as ambiguous. Running the calibrated seed updates the regex and forces a
   full re-derivation. Follow the vet-first steps in section 4.
2. **Flag the two growatt-vn NCC on the suppliers screen** (Mingjie VN + Minghui VN) — see section 4.
   Not yet done on prod.

Standing items from earlier sessions (audit locked SHORTAGE sheets in prod; the `missing_price` one-belt
hole) were closed 2026-07-11 and are not pending.

Optional follow-up (not required): `DEFAULT_DESCRIPTION_REGEX` (`app/client_config_store.py`) is still the
broad over-matching pattern used by the demo `growatt` client; calibrating the default too is a deferred
choice, not a pending prod step.
