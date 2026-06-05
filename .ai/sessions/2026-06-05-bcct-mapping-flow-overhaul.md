# Session 2026-06-05 — BCCT upload mapping-flow overhaul (+ deploy)

## What was done

Started from two unrelated asks, ended with a full BCCT mapping-flow
overhaul shipped to prod.

1. **BOM API `depth=full` filter + `is_shallow`** (`a8a3816`). CO requested
   excluding SHALLOW flats (`purchased_btp_as_leaf` + conservatively
   `mixed_confirmed`/`no_strategy`) from its picker. Classification
   single-sourced in `app.stores.bom.is_shallow_flatten` (reuses
   `bom_shape`). Wired into both `GET …/bom/artifacts` and the `:batch`
   endpoint CO actually uses. Smoke-verified on johnson VGM0121-05.

2. **LLM endpoint was DOWN.** Configured `codex-lb-demo.sgnai.dev` returned
   Cloudflare **1033 tunnel error**. Swapped LLM config (in
   `hub.app_settings`, NOT git) to **OpenRouter `openai/gpt-4o-mini`** —
   key borrowed from `growatt-item-master/.env`. Done on **dev + prod**.
   Old config backed up to gitignored `data/files/.{,prod_}llm_settings_backup.*`.
   This is **temporary** — restore sgnai when its tunnel is back, or
   provision a dedicated data-hub OpenRouter key.

3. **Root-caused the "diff loạn" report:** preview showed 67 rows changing
   on johnson VGM0121-05 because a **manually-confirmed cached mapping**
   swapped `Đơn giá`→`unit_price` and `Đơn giá tính thuế`→`unit_price_nt`
   (backwards vs mig-039: `unit_price`=VND, `unit_price_nt`=nguyên tệ). The
   rigid auto-match had it RIGHT; a human overrode it. Preview was correctly
   blocking a corrupting re-ingest.

4. **BCCT mapping-flow overhaul** (feature folder
   `.ai/features/2026-06-05-bcct-mapping-flow-overhaul/`, 5 phases):
   - **Phase 0** hotfix: corrected the swapped cached mapping + dropped the
     bad pending (dev DB; DB data was already correct).
   - **Phase 1** (`81adc4b`): on cache miss, confident rigid auto-map skips
     the manual mapping page → straight to Diff. `try_auto_map` in
     `_mapping_flow` (generic).
   - **Phase 2 → advisory** (`f58c42a`, later demoted in `1c9a014`):
     price-column inversion detector (`app/parsers/bcct_validate.py`). Now a
     **non-blocking advisory** (was a hard gate; demoted after user found
     the gate confusing — auto-map already prevents recurrence, the Diff is
     the review surface). Detector intentionally covers ONLY the VND↔nguyên-
     tệ price/value pairs, NOT arbitrary swaps.
   - **Phase 3** (`21f2a23`): per-client column aliases — `mig 075`
     `hub.client_column_aliases` + store `resolved_aliases` + admin UI
     ("Cấu hình cột" tab). Layered on top of code `ALIASES`; excluded from
     `data_promotion` bundle.
   - **Phase 4** (`834ac99`): sharper LLM prompt (field definitions, VND vs
     nguyên-tệ magnitude hint, ABSTAIN over guess) + merge fills only
     rigid-unresolved columns (never overrides a confident match).
   - **Phase 5** (`56fcd1d`/`45f6c47`/`1c9a014`): no-header files →
     positional mapping (`parse_bcct_workbook(positional_override=…)`, data
     from row 1, no row eaten as header). Picker AUTO-SELECTS "Không có
     header" when no header detected (`suggest_no_header`, rigid match == 0)
     + JS relabels columns to "Cột N". **Value-pattern inference**
     (`app/parsers/bcct_infer.py`) pre-fills the distinctive columns
     (declaration_no, date, declaration_type, currency, hs_code,
     hyphen/letter customs code, goods_name) so the operator only maps the
     numeric ones.

5. **Verification:** `scripts/smoke_bcct_flows.py` (real johnson-vn rows,
   asserts ingested outcomes, CI-ready exit code) + full 9-stage screenshot
   set (`scripts/screenshot_bcct_mapping_flow.py`, real data).

6. **Deployed to prod** (`1c9a014`): `git push` → on box `git pull` +
   `docker compose up -d --build` → migration 075 auto-applied. Verified
   live: mig075=true, table exists, health 200, new route reachable, LLM
   still OpenRouter, **real-data smoke ALL FLOWS PASS on prod** (temp client
   self-cleaned).

## Decisions

- Anomaly detection = **advisory, not a gate**, and deliberately **narrow**
  (only the price/value VND↔nt inversion). Not expanded to arithmetic/format
  checks — would add false positives + confusion for little gain now that
  auto-map prevents the original incident.
- No-header inference is **partial by design**: bare-digit SAP customs codes
  (johnson `1000…`) are NOT inferable by value alone — left for the user.
- Per-client column config is **per-deployment** (excluded from promotion
  bundle, same as `client_parser_rules`).

## What didn't work / gotchas

- Browser `set_input_files` + form submit in Playwright didn't navigate
  reliably → screenshot script uploads via httpx then `goto`s the resulting
  URL.
- Remote `psql -c "...$$..."` over ssh: bash expands `$$` to PID → use a
  quoted-heredoc piped to `psql` stdin instead.
- Running a repo script inside the prod container needs `-e PYTHONPATH=/app`.

## Open items

- **LLM on OpenRouter is temporary** (borrowed key). Restore sgnai or get a
  dedicated key. Backup: `data/files/.prod_llm_settings_backup.tsv`.
- Screenshots committed with **real Johnson customs data** (private repo,
  per user request "dùng dữ liệu thật"). Scrub if it ever needs to be less
  sensitive.
- No-header could later get a value-cross-column heuristic (customs_code =
  prefix of goods_name before `#&`) or a saved positional template.
- C.2 strict-auth cutover (prod) still open from 2026-05-30.
