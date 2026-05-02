# Project Status

**Date:** 2026-05-02

## Current State

Data Hub is a working MVP web app with upload preview-confirm flows, SSO/JWT auth, read APIs, BOM proposals, chat agent, and CO-facing contract guardrails. The latest full suite is green: `204 passed, 15 skipped`.

Current external-consumer position:
- CO/BCQT should use Data Hub only through documented HTTP APIs, not direct `hub` schema reads/writes.
- Read APIs still support dev-permissive bearer mode when `api_auth_strict=false`.
- Mutating BOM proposal API now always requires a real Data Hub JWT and current client edit ACL.
- The current API contract is documented in `docs/API_CONTRACT.md`.
- Chat Agent knowledge search is scoped to curated markdown under `docs/agent_knowledge/` and no longer searches `.ai/*`.

Worktree was clean before this handoff update.

## Recent Changes

- `89b108a agent: add technical enable toggle`
  - Added a technical settings toggle to enable/disable the Chat Agent.
  - Agent runtime and routes now respect the setting.
  - Added regression coverage for the toggle.
- `52aa9f2 api: harden CO contract guardrails`
  - Required real JWT for `POST /v1/hub/products/{product_code}/bom/proposals`.
  - Enforced `parent_version_id` for CO/`modified_for_case` BOM proposals.
  - Fixed invoice matching to apply SQL token filters before the 500-row cap.
  - Clarified `co-config` and `source-summary` semantics in API payloads.
- `d418361 docs: add API contract and scoped agent knowledge`
  - Added `docs/API_CONTRACT.md` as the source of truth for sister-app consumers.
  - Added curated `docs/agent_knowledge/data_hub.md`.
  - Reworked `search_knowledge_base` so staff can use it safely without exposing internal AI notes.

## Next Steps

1. Give CO/BCQT agents `docs/API_CONTRACT.md` and require contract-first changes for any new Data Hub endpoint.
2. When CO needs a new endpoint, add or update the provider contract and Data Hub tests first, then implement the consumer call.
3. Add service-account JWT/scopes later if CO needs non-user machine auth. Today the real-JWT path is user-based.
4. Replace `co-config` declaration-type placeholders and `source-summary.co_stock_row_count` semantics when Data Hub has real per-client CO declaration rules and stock calculation.
5. Keep `docs/agent_knowledge/` curated; do not copy internal handoff, strategy, credentials, or deployment details into it.

## Blockers

None.

## Notes for Next AI Session

- Respond in Vietnamese with full accents when the user writes Vietnamese.
- The user explicitly corrected that review/fix work in this session should happen in this repo, not in the CO repo. Do not jump to `barry-CO-main` unless the user asks for cross-repo changes.
- For endpoint requests from CO/BCQT, use `docs/API_CONTRACT.md` as the gate: define use case, request/response shape, auth/client scoping, pagination, precision, idempotency, and provider tests before consumer code depends on it.
- The intentional auth trade-off is: dev-permissive reads for speed, strict JWT writes for corruption prevention.
- `co-config` is currently a compatibility envelope, not a full CO business-rule source. `source-summary` is source-record coverage, not computed usable CO stock.
