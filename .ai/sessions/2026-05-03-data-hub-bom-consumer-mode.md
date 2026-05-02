# Session: Data Hub BOM Consumer Mode

## What Was Done
- Refreshed CO project context from `AGENTS.md`, `.ai/STATUS.md`, `.ai/DECISIONS.md`, and recent session summaries.
- Started/reused the CO dev server at `http://127.0.0.1:8001`; Data Hub was already available at `http://127.0.0.1:8754`.
- Researched current Data Hub BOM API state and confirmed the prior "flattening not ready" assumption was stale:
  - Data Hub now exposes `/v1/hub/products`, `/bom/latest`, `/bom/versions`, pinned `/bom`, `/bom/proposals`, and `/proposals/{proposal_id}`.
  - Data Hub excludes `non_flattened` from `/bom/latest` and returns `409 dual_source_variants` when multiple calculation-ready variants exist.
  - Live local Data Hub had BOM data for `growatt-vn`, `johnson-vn`, and technical flattening examples under `ui_flat_test`.
- Created `.ai/features/2026-05-03-co-bom-data-hub-api-port.md` with the CO port scope, decisions, risks, and plan.
- Extended `app/data_hub_client.py` with BOM API methods and policy-approved endpoint constants:
  - `list_bom_products`
  - `list_bom_versions`
  - `get_bom_latest`
  - `get_bom_version`
  - `submit_bom_proposal`
  - `get_bom_proposal`
  - `DataHubBomVariantConflict`
- Added `app/bom_service.py` as a service boundary:
  - local mode delegates to `app.bom_store`
  - Data Hub mode adapts Data Hub BOM products/versions/rows to the current `bom_workspace` template shape
  - Data Hub mode synthesizes an aggregate version to preserve existing case/template compatibility
- Wired `app/main.py` to call `bom_service.workspace`, `bom_service.update_config`, `bom_service.process_upload`, and `bom_service.template`.
- Made canonical shared-data UI read-only in Data Hub mode:
  - BOM page shows Data Hub read-only notice and hides canonical upload/config controls
  - catalog page/table hide upload/template controls in Data Hub mode
  - BCCT page hides upload/template controls in Data Hub mode
  - direct catalog/BCCT template routes now call `require_local_source_writes()` and return `409` in Data Hub mode
- Enabled local Data Hub source mode in the ignored runtime config (`DATA_HUB_ENABLED=1`), without committing the runtime file.
- Fixed a Data Hub-mode C/O case crash discovered during live smoke: blank invoice numbers no longer call Data Hub `/v1/hub/bcct/invoice-matches`, avoiding a provider `422`.

## Decisions Made
- CO should consume Data Hub BOM only through `app/data_hub_client.py`; no raw `/v1/hub/*` strings elsewhere.
- The first CO BOM port should be read-only and compatibility-oriented. Preserve existing templates by adapting Data Hub payloads into `bom_workspace` before redesigning the C/O origin UI.
- Data Hub remains the owner of canonical BOM upload, parsing, technical flattening, staff decisions, and BOM version materialization.
- CO-owned workflow uploads remain in CO: supporting files, C/O case workbook parsing, case records, and generated evidence/dossier exports.
- Existing CO-local BOM data remains intact and usable when `DATA_HUB_ENABLED=0`; this session did not migrate or delete it.
- Blank invoice matching should be a no-op in CO before calling Data Hub because the provider requires `invoice_no`.

## What Didn't Work
- The previous handoff said Data Hub did not yet implement technical flattening. Live OpenAPI, docs, code, and smoke checks showed Data Hub had since implemented flattening and the BOM read contract.
- The first full Python suite run failed the Data Hub endpoint guardrail because adapter endpoint literals used `{product_path}` instead of the approved `{product_code}` template. The fix was to use approved constants plus a URL-encoding helper.
- After enabling Data Hub mode locally, browser smoke showed `/co-case` could 500 when the case had no invoice number. The root cause was CO calling `/invoice-matches` with missing `invoice_no`; fixed by skipping the provider call for blank invoices.
- UI initially still showed catalog/BCCT upload/template controls even though backend POSTs were blocked. Templates were updated so Data Hub mode is visibly read-only for Data Hub-owned source/master data.

## Open Items
- Persist case-level Data Hub BOM selections and compact row snapshots. Current work preserves the existing in-memory compatibility shape but does not yet make Data Hub `version_id` binding a durable case-level artifact.
- Add explicit C/O origin-step UX for `dual_source_variants`. The BOM page can surface conflicts, but case binding still needs a first-class selection flow.
- Verify/fix Data Hub provider provenance for approved CO proposals before relying on proposal materialized versions for legal traceability.
- Decide whether Data Hub BOM product/version endpoints need pagination before larger real-client rollouts.
- Existing pre-session uncommitted discovery artifacts remain outside this commit unless the user asks to include them:
  - `.ai/features/2026-05-02-co-bom-data-hub-migration.md`
  - `.ai/features/2026-05-02-data-hub-bom-flattening-instructions.md`
  - `.ai/sessions/2026-05-03-data-hub-bom-flattening-plan.md`
- Existing unrelated Node legal lookup `raw-binary` test failures were not revisited.
