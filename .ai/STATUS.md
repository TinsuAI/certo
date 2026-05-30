# Project Status

## Current State
- Branch `main` at `ea25b36`, pushed to `tinsu/main`. Deployed to prod at
  `https://barry-co.tinsu.ai` (healthz 200, container healthy).
- Local CO dev at `http://127.0.0.1:8001` — server is currently running
  (`npm run co:serve`). Log at `/tmp/barry-co-8001.log`.
- Local suite **380 passed + 7 skipped** (6 new claim_id tests).
- **Uncommitted in working tree:** timing instrumentation added to
  `co_case_light_context` in `app/main.py` for `/origin` perf diagnosis.
  Not meant to ship — remove or keep for measurement, then decide fix.

## Recent Changes (2026-05-29/30 session)

| Commit | Topic |
|---|---|
| `2b9c535` | Guard `data_hub_target_url` against empty deep-link — only emit when a real DH page exists; 4 templates wrap the "Mở DH" button in `{% if data_hub_target_url %}` |
| `24d4731` | **Claim ID stability** — `claim_id_for` keyed on `material_code` (not BOM position); `_build_claim_rows` sums qty on collision (fixes latent under-claim). 6 DB-free unit tests + 3 Postgres-gated e2e tests pass. Brief: `.ai/features/2026-05-29-claim-id-stability.md` |
| `cdbeef2` | STATUS update |
| `5d34ed8` | CI: nightly CO stack refresh after prod deploy (on-merge trigger) — user committed separately |
| `ea25b36` | CI: self-pull tinsu-deploy before nightly refresh — user committed separately |

## Next Steps

1. **`/origin` perf diagnosis** (IN PROGRESS) — timing instrumentation is live
   in the local dev server. Measure cold vs warm:
   - Open a case detail page → click **Origin** tab (cold hit)
   - Click Origin again (warm hit)
   - Read log: `grep '\[origin-timing\]' /tmp/barry-co-8001.log`
   - Key question: is the bottleneck `source=fresh` (DH BCCT pagination) or
     `bom_workspace` (DH BOM fetch), and what's the split?
   - After measurement: remove timing lines from `app/main.py` before shipping.

2. **Origin lock TTL cleanup** (60-min stale lock) — deferred, no code yet.

3. **Customs FX historical backfill** — deferred, no code yet.

4. **Seed missing CO forms** — D/E/AK/AANZ/AJ/RCEP/UKVFTA/VK/VC/VJ.

5. **HS↔form coherence + criteria token validation** (MED).

6. **`can_view_client` short→long fallback** — investigated; confirmed **not a
   real prod bug**. UI only generates long-form (`growatt-vn`) client IDs from
   `client["id"]` which comes from DH canonical. 403 only hits typed/bookmarked
   short URLs. `clients` table in prod Postgres is empty — clients loaded live
   from DH. No action needed unless a short-URL entry point is added.

7. **Prod CO↔DH backend auth cutover** — deferred by user (low risk, one
   company only). Cutover steps in previous STATUS.

8. **Open decision:** unique constraint at DB level for new claim identity
   `(client_id, case_id, sheet_product_code, source_row, material_code)`.
   Currently app-only. See `.ai/features/2026-05-29-claim-id-stability.md`.

## Notes for Next AI Session

- **Memory** at `/home/vp/.claude/projects/-home-vp-workspace-client-barry-CO/memory/` — read `MEMORY.md` first.
- **Test on local by default.** Only touch prod when explicitly told.
- **Demo URLs** (in memory, not in repo): `barry-co.tinsu.ai`, `ttdatahub.tinsu.ai`.
- **Prod test account**: `claude-check@local` / `claude-temp-2026`. Short client
  IDs (e.g. `/clients/growatt`) return 403 on prod — use long form `growatt-vn`.
- **Local dev** writes to `/tmp/barry-co-8001.log`.
- **Prod deploy**: SSH `tinsu`, `cd /home/tinsu/co && git pull && docker compose up -d --build app`.
- **DH local**: runs at `:8754` with `--workers 4`, no `--reload`. Restart
  manually if DH schema/code changes.
- **Timing instrumentation** left uncommitted in `app/main.py`:
  `[origin-timing]` log lines in `co_case_light_context`. Remove before
  shipping. Measure first: run dev server, open a case, click Origin cold then
  warm, `grep '[origin-timing]' /tmp/barry-co-8001.log`.
- **`can_view_client`** — explored and confirmed non-issue for prod. UI always
  uses canonical long-form client IDs from DH. Short-form is seed/demo only.
  Do not add fuzzy-match fallback — that trades correctness for convenience.
- **Claim ID migration note**: claims locked before `24d4731` use the old
  positional hash. They're replaced automatically on next lock/release — stock
  math stays correct throughout (re-lock deletes by case+sheet, not by
  claim_id). No manual action needed.
- **BOM workspace cache** (`bom_service.py`): in-process dict, TTL 60s, keyed
  on `(base_url, client_id, token, sorted_product_codes, case_id)`. Preload
  warms it only when `bom_product_codes` is non-empty (i.e. case has products
  and invoice matches). If cold /origin is still slow after source_context
  warms, the bottleneck is likely BOM fetch — consider warming full-client BOM
  unconditionally in preload when case has products.
