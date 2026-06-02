# Project Status

## Current State
- **Big refactor landed + live.** `app/main.py` split **8017 → 167 lines** (pure app
  factory) into `app/web/` (templating, deps, client_context gate, co_case_context
  closure) + `app/routers/` (auth, settings, customs_fx, catalog, co_case, bom, bcct,
  co_stock, cost_allocation, pages). The 3 large stores also split (all <1000 lines):
  source_store 1724→912, source_index_store 1394→938, bom_store 1251→976 (+5 new
  modules). Pure code-movement, zero behavior change. Full structure + method + the
  monkeypatch-namespace tax: `.ai/sessions/2026-06-02-main-monolith-split.md`.
- **Git/deploy:** `main` = `aa55480` = `origin/main`. **Demo (tinsu) deployed at
  `2a04f4a`** — CI/CD all green (tests / docker / Deploy demo), no Docker Hub gotcha.
  `tinsu/main` is 1 docs-only commit behind `main` on purpose (avoided a redeploy for
  a STATUS line). `refactor/split-main` branch ref still exists (fully merged) — safe
  to `git branch -d`.
- **Verified:** 419 pytest green; local browser e2e 20/20 pages + substitute flow;
  **prod browser e2e 17/17** (SSO login, auth-filtered client list, origin SPA with
  300 substitute triggers). Scripts in `.ai/scripts/` (untracked).
- **Client feedback batch 1 — #1/#3/#5/#6 DONE + live; #2/#4 need client input** (NOT
  touched this session). Tracker: `.ai/features/2026-06-01-client-feedback-batch1/brief.md`.
  - #2 "mở" load lâu — fixed earlier; needs client to confirm it feels fast now.
  - #4 substitute "chưa phù hợp" — CO heuristic dropped; real lever = DH ranking →
    needs 3-5 bad-example codes from client to file a DH API request.

## Recent Changes (this session)
22 commits on `main` (was `refactor/split-main`, fast-forward merged). All refactor,
all green at each step. Highlights:

| Commit | Topic |
|---|---|
| `877507d` | extract templating → `app/web/templating` |
| `fb071fa`/`9291f12`/`6bad08e`/`c465c63` | routers: auth, settings, customs_fx, catalog |
| `7cea6f4`/`dcf8733`/`94d672f` | shared client_context gate → `app/web/client_context` + `deps` |
| `11e91e5` | co_case 114-helper closure → `app/web/co_case_context` |
| `42529a9` | 30 co-case routes → `app/routers/co_case` |
| `0c1b39e` | bom/bcct/co_stock/cost_allocation routers |
| `12a31cd` | drop 181 dead imports from main |
| `c80da9a` | slim main.py to factory (+ `app/routers/pages`) |
| `bf70f8a`/`1ae2040`/`2dfd663`/`262567b` | split the 3 large stores |
| `2a04f4a`/`aa55480` | merge docs; pushed + demo redeployed |

## Next Steps (priority order)
1. **(optional) Tidy refactor leftovers:** `git branch -d refactor/split-main`;
   decide whether to commit the `.ai/scripts/*.cjs` e2e smoke scripts as tooling.
2. **Close batch 1 — needs client input** (email draft `C:\temp\toss\barry-co-email-update-batch1.txt`):
   #2 confirm "mở" speed; #4 collect 3-5 wrong-substitute examples → file
   `.ai/api-requests/2026-06-01-substitute-ranking-quality.md`.
3. **Older deferred (technical, unstarted):** origin lock TTL cleanup (60-min stale
   lock, `co_case_store.py:ORIGIN_CALCULATION_LOCK_TTL_MINUTES`); customs FX historical
   backfill (admin runs `refresh_customs_exchange_rates(history_start_date=...)`); seed
   missing CO forms (D/E/AK/AANZ/AJ/RCEP/UKVFTA/VK/VC/VJ — Form Index still shows only
   B/CPTPP/EUR.1/AI, confirmed via prod e2e); HS↔form coherence + criteria token
   validation; claim-identity DB unique constraint (user-deferred).
4. **Optional refactor follow-ups:** the re-export shim in `main.py` exists only for
   `app.main.X` test imports — could repoint tests to source modules and drop it;
   `PostgresSourceIndexStore` (~840 lines) is one cohesive class left intact.

## Blockers
- **#4** blocked on client supplying concrete bad-example material codes.

## Notes for Next AI Session
- **Refactor invariant:** `app/web/*` and `app/routers/*` must NEVER import `app.main`
  (one-way: main → routers/web). `main.py` re-exports moved symbols so `app.main.X`
  keeps working. When relocating a module global that tests swap **wholesale**
  (`monkeypatch.setattr(main, "X", fake)` / `patch.object`), patch the NEW namespace
  (`app.web.co_case_context.X` / `app.routers.<dom>.X`) with the same instance — see
  memory `main-split-refactor`.
- **Deploy gotcha:** don't re-add forced Docker Hub pulls / `# syntax=` to the
  Dockerfile — demo server can't reach `registry-1.docker.io`. Green tests + red
  "Deploy demo" = server infra, not code. Memory `deploy-docker-hub-frontend-gotcha`.
- **Push semantics:** push to `tinsu/main` redeploys the demo (self-hosted runner,
  job "Deploy demo"); `origin` push is CI-only. Watch with `gh run list -R TinsuAI/co`.
- **Dev server:** restart with `CO_AUTH_REQUIRED=0 nohup npm run co:serve > /tmp/co-serve.log 2>&1 &`
  on `:8001` (uvicorn `--reload`; it dies/restarts during heavy commits — re-check).
  DH at `127.0.0.1:8754`. Postgres mode (`BARRY_DATABASE_URL`) so snapshot paths are live.
- **E2E recipe:** Playwright via npx cache —
  `PWDIR=$(dirname "$(ls -d ~/.npm/_npx/*/node_modules/playwright|head -1)"); NODE_PATH="$PWDIR" node <script.cjs>`
  (CJS + async IIFE; ESM `import` does NOT honor NODE_PATH). Prod login: SSO email/password
  `claude-check@local` / `claude-temp-2026` (manager, growatt-vn+johnson-vn). Always use
  `-vn` client ids. Memory `browser-test-recipe`.
- **Shell quirks:** `ls`/`grep` aliased oddly in this zsh — use `command ls`/`command grep`;
  zsh does NOT word-split `$var` (use arrays in loops). `.pyc` are git-tracked.
- **New memory this session:** `main-split-refactor`.
