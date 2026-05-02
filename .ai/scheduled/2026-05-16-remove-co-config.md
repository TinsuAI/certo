# Scheduled removal: /v1/hub/dncxs/{id}/co-config

**Sunset date:** 2026-05-16
**Status:** Awaiting CO cutover confirmation. Do NOT execute before then.
**Owner:** Data Hub agent

## Pre-conditions

Before running this removal, confirm:
1. CO has shipped its migration PR and is calling `/v1/hub/dncxs/{id}/client-config` in production for ≥ 7 days with no errors.
2. No `Bearer` log entries for `/co-config` in the last 7 days from CO or BCQT.
3. User has greenlit the removal.

If any pre-condition fails, postpone — do NOT cut the endpoint while consumers still depend on it.

## What to remove

In `app/routes/api.py`:
- The deprecated `api_co_config` endpoint handler.
- The `_co_config(client)` helper function (now unused).

In `docs/API_CONTRACT.md`:
- The "GET /v1/hub/dncxs/{client_id}/co-config (deprecated)" section.
- Any remaining references to `co_stock`, `allocation_code`, `lot_policy` in CO consumer rules.

In `docs/API_CHANGELOG.md`:
- Append entry: `## 2026-05-16 — Breaking: remove /co-config endpoint (sunset)` with migration confirmation.

## Steps for the executing agent

1. Search for references:
   ```
   git grep "co-config\|api_co_config\|_co_config" -- app/ docs/
   git grep "co_stock_row_count\|co_stock\|allocation_code" -- app/
   ```
2. Delete the deprecated route + helper.
3. Update the contract + changelog.
4. Run full test suite: `uv run pytest -q`. All green required.
5. Run `scripts/announce_breaking_change.py --confirm` to fan out the final removal notification.
6. Open a PR titled "api: remove deprecated /co-config endpoint (sunset 2026-05-16)" with body linking back to this file and the original change at `docs/API_CHANGELOG.md`.
7. Do not auto-merge — human review.

## After execution

Delete this file once the removal PR is merged.
