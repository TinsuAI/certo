# 2026-05-02 — CO API Contract And Agent Guardrails

## What Was Done

- Picked up the interrupted Data Hub session after the previous agent stopped mid-work.
- Reviewed the CO-facing API endpoint additions in this repo and identified logic risks around mutating auth, BOM proposal context, invoice matching, and ambiguous API semantics.
- Added a Chat Agent technical settings toggle.
  - Commit: `89b108a agent: add technical enable toggle`
- Hardened CO/Data Hub API guardrails.
  - Commit: `52aa9f2 api: harden CO contract guardrails`
  - Real JWT is now mandatory for BOM proposal writes.
  - `parent_version_id` is required for CO or `modified_for_case` BOM proposals.
  - Invoice token matching now filters in SQL before applying the row cap.
  - `co-config` and `source-summary` responses now include explicit semantic flags.
- Added the consumer API contract and scoped agent knowledge base.
  - Commit: `d418361 docs: add API contract and scoped agent knowledge`
  - `docs/API_CONTRACT.md` documents auth, endpoint catalog, response rules, CO-specific semantics, and the contract-first process for new endpoints.
  - `docs/agent_knowledge/data_hub.md` is the curated source searched by Chat Agent.
  - `search_knowledge_base` now searches only `docs/agent_knowledge/**/*.md`, not `.ai/*`.
- Verified full test suite after the changes: `204 passed, 15 skipped`.

## Decisions Made

- Keep dev reads convenient, but make writes strict.
  - Read routes may still accept non-empty legacy bearer tokens when `api_auth_strict=false`.
  - BOM proposal writes always require a valid Data Hub JWT because write corruption risk is higher than dev friction.
- Treat `docs/API_CONTRACT.md` as the source of truth for Data Hub consumers.
  - CO/BCQT agents should not invent Data Hub calls from raw table shape or inferred payloads.
  - Any new endpoint request must start as a contract change with provider tests.
- Mark incomplete CO semantics explicitly instead of hiding them.
  - `co-config` declaration-type filters are `unconfigured`.
  - `source-summary.co_stock_row_count` is `raw_import_rows_unfiltered`, not usable CO stock.
- Make Chat Agent knowledge safe by curation, not by role-only blocking.
  - Staff can use `search_knowledge_base`, but only against the curated public-support docs folder.

## What Didn't Work

- A first-pass fix hid `search_knowledge_base` from non-admin/non-dev users. That reduced leakage but made the tool less useful. It was replaced with a folder scope: `docs/agent_knowledge/`.
- Reviewing the sister CO repo was the wrong direction for this request. The user clarified that the review should cover changes made inside Data Hub only.
- Letting CO use Data Hub "fully" without a written API contract leaves CO agents guessing from raw rows. That is the main corruption risk the new contract process is meant to reduce.

## Open Items

- CO/BCQT agents still need to be pointed at `docs/API_CONTRACT.md` in their own workflow/context files.
- Service-account JWTs and explicit service scopes are not implemented yet. Current strict write auth uses real user JWTs and current client ACL.
- Data Hub does not yet expose real per-client CO declaration-type configuration or computed CO stock. Current fields are deliberately marked as unconfigured/raw.
