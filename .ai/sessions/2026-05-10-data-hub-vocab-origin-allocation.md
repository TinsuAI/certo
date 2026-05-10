# Session Summary: Data Hub Vocabulary And Origin Allocation

Date: 2026-05-10

## What Was Done
- Migrated CO to the current Data Hub vocabulary and contracts:
  - `/client-config` replaces the deprecated config endpoint,
  - `DATA_HUB_SERVICE_TOKEN` replaces the old runtime token key,
  - `material_identity` replaces `product_identity`,
  - Data Hub BOM reads now use artifact naming and artifact endpoints.
- Updated Data Hub adapter tests, policy guardrails, runtime settings UI, docs, and feature notes to remove stale Data Hub vocabulary.
- Updated BOM and C/O origin UI vocabulary from visible “version” language to artifact/composition language where it reflects Data Hub BOM artifacts.
- Kept compatibility aliases for existing saved case/local fallback fields such as `bom_version_id`, `bom_product_version_id`, and `aggregate_version_id`.
- Migrated local runtime config from `DATA_HUB_API_TOKEN` to `DATA_HUB_SERVICE_TOKEN` so CO can call strict-auth Data Hub locally.
- Ran browser E2E with Data Hub SSO:
  - logged in through Data Hub,
  - opened Growatt C/O index,
  - opened Data Hub-backed BOM page,
  - created smoke case `E2E-DH-220630` (`co-case-e44fe2065b62`),
  - opened Origin,
  - calculated sheet `SD00.0010600`,
  - verified no console/page/HTTP 500 errors.
- Fixed origin warning summary and column control buttons after AJAX shell replacement by reinitializing interactions after `[data-co-case-shell]` replacement.
- Investigated why the smoke origin sheet showed many warnings:
  - initial symptoms: 107 missing stock/unit-value/material-name warnings, 122 conservative origin warnings,
  - root cause: CO stock allocation in Data Hub mode was still using customs/display code (`DAYTINHIEU`, `LK-DAY2`) instead of `material_identity.internal_code` (`012.0002700`, `018.0644700`) used by BOM rows,
  - fix: `resolve_allocation_code()` now prefers `material_identity.internal_code` when present.
- Verified after fix and CO server restart:
  - missing stock/unit-value/material-name warnings disappeared for the smoke case,
  - remaining warnings are origin classification gaps from source data,
  - LVC recalculated from `63.13%` with missing evidence to `48.94%` with allocated evidence.
- Released the origin calculation lock for `co-case-e44fe2065b62`.
- Full verification: `uv run pytest` passed with `190 passed`.

## Decisions Made
- Treat Data Hub `material_identity.internal_code` as the correct CO allocation key when present. This preserves Data Hub as the authority for mapping customs/display codes to BOM/internal material codes.
- Keep declaration/line/source-row as the identity of actual stock evidence. Material code only selects candidate lots; allocation output still records `source_row`, transaction key, declaration number, and line number.
- Keep legacy `version_*` fields as compatibility aliases rather than doing a risky full local schema migration in the same pass.
- Do not use Data Hub code-mapping endpoints for C/O BOM resolution; mappings are evidence, not the line-level identity contract.

## What Didn't Work
- Direct curl to Data Hub initially failed because Data Hub was not listening. After the user started Data Hub, JWKS worked and strict-auth `/v1/hub/dncxs` required a bearer token as expected.
- CO could not read Data Hub after the vocabulary migration until the local runtime override was migrated from `DATA_HUB_API_TOKEN` to `DATA_HUB_SERVICE_TOKEN`.
- Browser screenshot after `Tính bảng kê` briefly showed `Đang tính...`; reload showed the backend had completed. This was a transient button state in the screenshot, not a server hang.
- Warning filters and column controls appeared dead after calculation because AJAX shell replacement dropped direct DOM event listeners. Rebinding after shell replacement fixed it.
- The first browser retest of the allocation fix still showed old warnings because the running CO server process had not picked up the Python resolver change. Restarting the CO dev server resolved it.

## Open Items
- Data Hub/material catalog still needs origin classification evidence for Growatt NVL if C/O should stop defaulting all NVL to conservative non-origin.
- The large hidden origin form should be replaced with JSON payload endpoints; see `.ai/features/2026-05-08-client-side-origin-calculation.md`.
- Confirm whether duplicate finished-product codes can occur in one dossier. If yes, origin sheet state needs a stable line identity instead of product-code keys.
- Decide whether to keep or remove local smoke case `co-case-e44fe2065b62`.
- Unrelated dirty/untracked artifacts remain in the worktree and were intentionally left alone.
