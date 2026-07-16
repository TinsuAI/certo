# Feature spec: CO-owned client config (allocation_code + co_stock) editable in DH source-mode (#14)

**Issue:** TinsuAI/co #14 — VN-origin onboarding blocker: allocation strategy hard-defaults to `same_as_customs_code` in DH mode; growatt-vn technical BOMs never match on-spot lots.
**ADR:** `.ai/DECISIONS.md` → [2026-07-16] "Client config ownership is partitioned…".
**Status:** ready for `/implement` (`/tdd` per slice).

## Problem (verified)

In DH source-mode (`DATA_HUB_ENABLED=1`), `DataHubSourceStore.get_client_config` (`data_hub_client.py:668`) = `migrate_config({**default_config(client), **dh_config})`, and `save_client_config` raises read-only (`:673`). DH's payload carries only declaration-type (`bcct`) fields, so `allocation_code.strategy` falls to `default_config`, which gives `description_regex` **only** for the legacy id `"growatt"` — every other id, including real `growatt-vn`, gets `same_as_customs_code`.

Measured on the live DH Postgres (38,287 growatt-vn import lots; real regex `\(([A-Z0-9][A-Z0-9._/-]{3,})\)` applied to `goods_name`):

| strategy | distinct BOM codes matched |
|---|---|
| `same_as_customs_code` (current) | **101 / 2,236 (4.5%)** |
| `description_regex` (correct) | **2,145 / 2,236 (96%)** |

`material_identity.internal_code` is null on **0 / 38,287** rows, so the `resolve_allocation_code` short-circuit (`client_config_store.py:126`) never fires — the strategy is the whole lever. Per-client: Johnson must stay `same_as_customs_code`, so no blanket default flip.

## Ownership model (the fix)

Partition `client_config` by section owner:

- **Data Hub owns `bcct`** (declaration-type preset — master data; the config form already renders it read-only).
- **CO owns `allocation_code` + `co_stock`** — they parameterize CO's own `resolve_allocation_code` / co_stock derivation; no DH consumer reads them.

Reuse the existing local `client_configs` store (`app_state_store.py:96-144`, `barry_co` Postgres) — it already has `validate_config` (incl. regex-compile), version increment, and hash. **No new overlay blob.**

In DH source-mode:
- `get_client_config` → read the local saved config as **base**, overlay DH's `bcct` section on top.
- `save_client_config` → write the **CO-owned sections** to the local store instead of raising; `bcct` edits stay rejected.

## Slices for `/tdd` (dependency order)

### S1 — DH-mode config read/write reshape (`app/data_hub_client.py`)
`DataHubPortfolioService`/`DataHubSourceStore`:
- `get_client_config(client)`: `local = app_state_store.get_client_config(client)` (falls back to `default_config` + persist when no row); `dh = self.data_hub.get_client_config(client["id"])`; return `migrate_config({**local, "bcct": {**local["bcct"], **dh_bcct_section(dh)}}, client)`. DH `bcct` wins over local `bcct`; CO sections come from local.
- `save_client_config(client, config)`: split — CO-owned sections (`allocation_code`, `co_stock`) go to `app_state_store.save_client_config` (which validates + versions + hashes); reject any attempt to change `bcct` (keep it DH-sourced). Must not raise for CO-owned edits.
- File-mode (no `BARRY_DATABASE_URL`) fallback: use the existing file `client_config_store` for the CO-owned sections so tests/offline dev still work.
**Tests:** in DH-mode with a stubbed DH client, saving `allocation_code.strategy=description_regex` for growatt-vn persists and is read back through `get_client_config`; DH's `bcct` still overrides local `bcct`; a `bcct` edit via `save_client_config` is rejected.

### S2 — config-route gate fix (`app/routers/pages.py:248-336`)
Today the route upserts overlay fields (`:262-312`) then hits `require_local_source_writes()` (`:313`) which 409s unconditionally in DH mode — a partial save then error. Restructure so:
- CO-owned config fields (`allocation_code_strategy`, `description_regex`, `allocation_code_fallback`, `co_stock_lot_policy`) route through `portfolio_service.save_client_config` (now allowed in DH mode via S1) and return success.
- Only a `bcct`/declaration-type change trips the read-only gate.
**Tests:** POST the config form in DH mode changing only allocation fields → 200 + persisted, no 409; POST attempting a declaration-type change → 409; the three existing overlays (`bang_ke`/`export`/`co_stock_overrides`) still save.

### S3 — forced full re-derivation on CO-config change (`app/co_stock_materializer.py`, `app/web/co_case_context.py`)
A CO-config change touches no DH source row, so the delta path (`co_case_context.py:3672-3683`) re-derives nothing and the existing snapshot keeps stale codes. Add a CO-config fingerprint:
- New column `co_config_fingerprint text` on `co_stock_refresh_state` (migration). Fingerprint = stable hash of **both CO-owned sections** (`allocation_code` **and** `co_stock`), NOT of `config_hash` (which embeds `updated_at`, regenerated every DH-mode call, `co_stock_materializer.py:194`). Covering `co_stock` too is required: a `line_level → manual_review` `lot_policy` change also alters derivation (`co_stock_derivation.py:40-41` forces `requires_review`) but leaves the `allocation_code` dict untouched — an `allocation_code`-only fingerprint would miss it and no-op. (`aggregate` is already caught by the `delta_safe` guard at `:3661-3662`; `manual_review` is not.)
- `record_refresh_state(...)` writes it; `read_refresh_state` returns it.
- In `_refresh_co_stock_delta_or_full`, add `config_current = state.co_config_fingerprint == fingerprint(current_config)` to the delta guard alongside `schema_current`; mismatch → `_full_refresh`.
**Tests:** given a snapshot stamped under `same_as_customs_code`, changing the strategy to `description_regex` then refreshing runs a **full** re-derivation (not delta); same for a `line_level → manual_review` `lot_policy` change; an unchanged config with no new BCCT rows still takes the delta no-op.

### S4 — seed growatt-vn + pin its effective strategy
- Data change: set growatt-vn's CO-owned `allocation_code.strategy = description_regex` (default `description_regex` regex + `same_as_customs_code` fallback) through the new save path (the current path raises in DH+DB prod).
- Regression test pinning growatt-vn's **effective** strategy = `description_regex` after onboarding, and that a sample lot `... (920.0042600)` resolves `allocation_code=920.0042600`.

## Non-goals (this ticket does NOT do)
- **Option A** (DH-side `allocation_code` config / API contract) — rejected in ADR.
- Removing the `client["id"] == "growatt"` special-case in `default_config` — the next embedded-code client still defaults to 4.5%. **BACKLOG belt:** surface a `requires_review` allocation count on the config page so a wrong strategy is visible before a case fails.
- The display-only mixed-origin shortfall note in #14 (shortfall rides the first split part) — separate, non-blocking fix.

## Risks / rollout
- **Silent no-op if S3 is skipped** — the fix appears not to work on the 60k-row snapshot. S3 is not optional.
- **Saved-case rebind veto (T0 prerequisite):** S1–S4 do **not** touch `allocation_line_matches_stock` (`co_case_context.py:1097`), which hard-vetoes a lot match when a persisted saved-line `allocation_code` differs from the re-derived one. A strategy change re-derives `allocation_code`, so any client **with saved cases** would orphan those lines from their lots. growatt-vn is safe only because it has no saved cases yet. **Ticket T0 must ship before any strategy change on a client that has saved cases.**
- **Local config resurrection:** reading local config as base means any stale `client_configs` row now takes effect. Confirm the other 4 clients' local rows before deploy; growatt-vn/johnson/demo-furniture are the live ones.
- **Migration:** additive column only; existing rows get `co_config_fingerprint=NULL` → treated as mismatch → one forced full refresh per client on next refresh (acceptable, self-healing; mirrors the 9f38afa schema-version bump).
- **B→A reversibility:** if DH later owns `allocation_code`, it's one ownership-line move (drop the section from local base, let DH's win) — no merge-behavior rewrite.

## Verification (fill at implement time)
- [ ] Full suite pass count (before → after).
- [ ] growatt-vn effective strategy = `description_regex`; a Tính on a growatt-vn case matches ~96% of BOM codes (not ~4.5%), sheets leave `bom_loaded` shortage-park.
- [ ] Config form in DH mode saves allocation fields without 409; declaration-type edit still 409s.
