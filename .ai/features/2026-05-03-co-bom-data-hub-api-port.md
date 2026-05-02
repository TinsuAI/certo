# Feature: CO BOM Data Hub API Port

## Scope
Port CO's BOM read and case-binding behavior to Data Hub when
`DATA_HUB_ENABLED=1`.

In scope:
- Read Data Hub BOM products, versions, rows, unresolved evidence, and
  staff decisions through `app/data_hub_client.py`.
- Keep canonical BOM upload, technical flattening, and BOM staff confirmation
  in Data Hub.
- Make CO's BOM page a Data Hub-backed read-only viewer in Data Hub mode.
- Bind C/O cases to explicit Data Hub BOM `version_id` values and snapshot the
  calculation rows used by the case.
- Submit case-specific modified BOM proposals through Data Hub's
  `/v1/hub/products/{product_code}/bom/proposals` endpoint.

Out of scope:
- Direct `hub` schema writes from CO.
- Reimplementing technical BOM flattening in CO.
- Moving C/O case state to Data Hub.
- Porting canonical BOM upload/config UI into CO. Those actions remain in
  Data Hub.

## Current Data Hub Contract
Data Hub now has enough BOM API for a CO read port:

- `GET /v1/hub/products?client_id=...`
  Lists products with BOM metadata:
  `{items: [{product_code, n_versions, latest_version, last_published}]}`.

- `GET /v1/hub/products/{product_code}/bom/latest?client_id=...`
  Returns `{version, rows, unresolved, decisions}` for one calculation-ready
  latest version. It excludes `flatten_status='non_flattened'`. If multiple
  dual-source variants are live, it returns `409 {error: "dual_source_variants",
  variants: [...]}` and CO must force an explicit user selection.

- `GET /v1/hub/products/{product_code}/bom/versions?client_id=...[&actor=][&intent=]`
  Lists version metadata for one product. No pagination today.

- `GET /v1/hub/products/{product_code}/bom?client_id=...&version_id=...`
  Fetches a pinned version. This can return `non_flattened`, so CO must reject
  those for calculation unless the workflow is only displaying evidence.

- `POST /v1/hub/products/{product_code}/bom/proposals`
  Submits a CO case-specific proposal. Requires valid JWT. Service tokens need
  `bom:propose`. Body shape:
  `{client_id, actor: "co_system", intent: "modified_for_case",
  parent_version_id, context, rows}`. Response shape:
  `{proposal_id, status, version_id, decision_reason, failed_conditions}`.

- `GET /v1/hub/proposals/{proposal_id}`
  Fetches proposal audit data when the caller can view the client.

Live local Data Hub smoke showed:
- `growatt-vn`: 212 product codes, 293 BOM versions.
- `johnson-vn`: 2 product codes, 2 BOM versions.
- `ui_flat_test`: technical flattened examples including dual-source and
  non-flattened scenarios.

## Decisions
- Treat Data Hub BOM as ready for a CO read-only MVP port.
- Keep Data Hub API literals inside `app/data_hub_client.py`; update
  `tests/test_data_hub_policy.py` only after adding approved BOM endpoints.
- Preserve CO's current template shape behind an adapter first. Data Hub lacks
  CO's aggregate BOM version model, so CO should synthesize a compatibility
  workspace before attempting a wider UI redesign.
- Use `version_id` as the binding key. Do not use `version_no` as an identity
  because Data Hub scopes it by product and BOM variant.
- In Data Hub mode, canonical BOM upload/config/template routes should stop
  writing local BOM state and instead point staff to Data Hub.
- For C/O calculation, pinned Data Hub versions with
  `flatten_status='non_flattened'` are not usable.

## Risks
- Dual-source variants require explicit CO UX. Silently picking the first
  variant would create wrong origin evidence.
- Data Hub's per-product model does not match CO's aggregate BOM version model.
  The adapter must either synthesize an aggregate or the case UI must bind each
  product directly.
- Data Hub BOM endpoints currently have no pagination. This is acceptable for
  first Growatt-sized smoke, but may need a contract extension for larger
  clients.
- Data Hub serializes decimal values as JSON numbers in current responses.
  If RVC needs exact decimal transport, request a string-decimal contract.
- Approved CO proposals currently appear to materialize through the default
  `create_version()` path unless Data Hub overrides provenance in a later fix.
  Before CO relies on proposal provenance, verify that approved proposals get
  `source_bom_kind='co_modified'` or equivalent and `source_channel='co_proposal'`.
- Proposal validation does not yet validate that `context.case_id` exists in CO.
  This is acceptable for MVP if CO stores proposal IDs on the case, but it is
  not full cross-system referential integrity.

## Port Plan
1. Add Data Hub BOM adapter methods and tests.
   - `list_bom_products(client_id)`
   - `list_bom_versions(client_id, product_code, actor=None, intent=None)`
   - `get_bom_latest(client_id, product_code)`
   - `get_bom_version(client_id, product_code, version_id)`
   - `submit_bom_proposal(client_id, product_code, parent_version_id, rows, context)`

2. Add a CO BOM service boundary.
   - Local mode delegates to `app.bom_store`.
   - Data Hub mode adapts Data Hub API payloads into the existing
     `bom_workspace` structure.

3. Port the BOM page.
   - Render Data Hub product/version rows.
   - Hide local upload/config controls in Data Hub mode.
   - Show Data Hub version metadata: `source_bom_kind`, `flatten_status`,
     `flatten_strategy`, `display_label`, decisions, and unresolved evidence.

4. Port C/O case binding.
   - On the origin step, bind each product to an explicit Data Hub BOM
     `version_id`.
   - Handle `409 dual_source_variants` by surfacing a required selection.
   - Store selected version IDs and compact row snapshots in CO case state.

5. Add proposal flow after read binding is stable.
   - Submit `modified_for_case` proposals with current user JWT.
   - Bind approved `version_id` to the case.
   - Show rejected proposal reasons without mutating local BOM.

## Open Questions
- Should CO keep a synthetic aggregate BOM selector for backwards
  compatibility, or move the origin step directly to per-product Data Hub
  version selection?
- Should proposal writes wait until Data Hub provenance for approved CO
  proposals is confirmed?
- Is the current no-pagination BOM product/version contract sufficient for
  real clients beyond Growatt, or should CO request paged endpoints before
  porting the page?
- Which existing CO-local BOM versions are legal records that need migration
  instead of archive/removal?
