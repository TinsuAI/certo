# Session 2026-06-05 — VNG case verification + deploy topology correction

## What Was Done
- Confirmed the dev server was already running (`npm run co:serve`, `:8001`, Postgres mode,
  live reload). Data Hub also up locally on `:8754`. No restart needed.
- **Discovered the real deployment topology.** The user said there are "2 instances (demo +
  prod)" — my memory only documented one (`barry-co.tinsu.ai` labelled "demo"). Probed DNS +
  `ssh tinsu docker ps` + `/etc/cloudflared/config.yml` + CI `ci.yml` and found:
  - **PROD** — `barry-co.tinsu.ai` → `co-app-1` (`:8755`) + `data-hub-app-1` (`:8754`,
    `ttdatahub.tinsu.ai`). `/home/tinsu/co`, compose project `co`. Real johnson-vn data.
  - **DEMO/nightly** — `demo-co.tinsu.ai` → `nightly-co-app-1` (`:8765`) + `nightly-dh-app-1`
    (`:8764`, `demo-datahub.tinsu.ai`). `/home/tinsu/tinsu-deploy`, project `nightly`,
    `docker-compose.nightly.yml` + `.env.nightly`. Snapshot of prod DBs, rebuilt on merge.
  - CI `Deploy demo` job deploys PROD, then `continue-on-error` rebuilds nightly via
    `tinsu-deploy/scripts/rebuild-app.sh co`.
- **Verified VNG reset case (`co-case-ede4d913bafa`) on BOTH instances:**
  - DB check (both `co-db-1` and `nightly-co-db-1`): rev 36, `payload->>'status'`=`open`,
    `payload->>'locked'` empty, identical `updated_at` → in sync.
  - UI check (Playwright, logged in as `claude-check@local`): both prod and demo loaded
    `/clients/johnson-vn/co-case/co-case-ede4d913bafa/origin` at HTTP 200, rendered identically.
    Header: case `CO-JOHNSON-VN-VNG26010020-EDE4`, Form B, chile, **TRANG THÁI = "Có TP không
    đạt"**, chip "Thứ tự sheet đã đổi — cần tính lại". Interactive buttons live
    (`Reset`/`Chốt`/`Load BOM`/`Xuất bảng kê HQ`). Shortfall driven by rows "Chưa phân loại
    xuất xứ" (101/30/43 per sheet) tạm tính là không xuất xứ.
  - Screenshots saved to `.ai/screenshots/2026-06-05-vng-verify/` (`prod-origin.png`,
    `demo-origin.png`, `prod-header.png`; gitignored) + helper scripts `verify.mjs`,
    `inspect.mjs`.
- Updated memory `demo-deployment-urls` + MEMORY.md index to record the two-stack topology.

## Decisions Made
- **Verify via deployed instances, not local.** The two reset cases (VNG, SCI) only exist on
  prod/demo; local `johnson-vn` carries unrelated test fixtures. Confirmed with the user before
  touching prod (read-only: open + render, no `Chốt`/lock).
- **Did not click `Chốt`.** Locking/issuing VNG is a client go/no-go, not an engineering step.
  Left the case `open` and unlocked on both instances.
- **Read-only recompute through the UI rather than reverse-engineering the container compute
  path.** The origin sheet renders computed results on load; that plus the live interactive
  buttons is sufficient evidence the case is re-runnable. Avoided poking the internal calc API
  on prod.

## What Didn't Work
- **ESM + NODE_PATH for Playwright.** `import { chromium } from 'playwright'` under `node
  script.mjs` with `NODE_PATH` set fails (`ERR_MODULE_NOT_FOUND`), and the absolute-path
  named import fails too (CJS module). Fix: `import pkg from
  '<npx>/node_modules/playwright/index.js'; const { chromium } = pkg;`.
- **Initial SQL assumed `co_case_states.case_id` and `co_cases.status`.** Neither exists:
  `co_case_states` is keyed per-client (whole-workspace payload), and `co_cases` has no
  `status` column (status lives in `payload->>'status'`). Corrected the queries.
- **Guessing nightly hostnames** (`nightly-co.tinsu.ai`, etc.) — none resolve. The real demo
  hostname `demo-co.tinsu.ai` came from `/etc/cloudflared/config.yml` (`→ localhost:8765`).

## Open Items
- VNG: awaiting client go/no-go to lock+issue. No code work pending.
- SCI: stays stale until VGM/MPL Mẫu-16 BOMs land in Data Hub.
- Batch 1 #2/#4: need client input.
- Optional: calc snapshot path loading material catalog; DH `a8a3816` echo deploy to demo DH.
</content>
</invoke>
