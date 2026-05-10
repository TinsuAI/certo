# Feature Plan: Consume Data Hub Material Identity in CO

Date: 2026-05-07

## Context

Data Hub now exposes BCCT BOM resolution through `material_identity`. CO consumes that contract directly and no longer uses the temporary code-mapping bridge that once mapped Growatt display code `BIENTAN.17` to BOM product `PV01.0117500`.

## Live Validation

- Data Hub endpoint is `GET /v1/hub/bcct?client_id=growatt-vn&include_material_identity=true`.
- Validated `BIENTAN.17` rows resolve to `PV01.0117500` with `resolution_status=resolved` and `resolution_source=goods_name_embedded_code`.
- `GET /v1/hub/bcct/invoice-matches` returns `material_identity` on invoice-filtered rows.
- CO invoice-only and declaration-driven case context preserve `material_identity`.
- CO no longer calls Data Hub code-mapping endpoints for BOM resolution.
- Direct `/bom/latest` for `PV01.0117500` returns `409` because multiple flattened variants exist. This is expected; CO should keep using `DataHubBomService.workspace()` and existing per-case BOM artifact binding instead of assuming one latest artifact.
- `DataHubBomService.workspace({"id": "growatt-vn"}, ["PV01.0117500"])` returned 3 product artifacts/options and 274 BOM rows for the resolved product.

## Implementation Status

1. Added CO adapter helpers in `app/data_hub_client.py`.
   - Make `invoice_matches()` pass `include_material_identity=true` explicitly.
   - Add `bom_product_code_from_material_identity(row)` that returns a BOM product code only for resolved material identity.
   - Keep normalization generic; do not parse `goods_name` in CO.

2. Preserved material identity in declaration-driven matching.
   - In `DataHubPortfolioService.co_case_source_context()`, call `list_bcct(client_id, include_material_identity="true")` for case origin context.
   - Keep broad workspace/source-summary list views lightweight unless they need material identity.
   - Add tests proving `match_case_bcct_exports()` output still contains `material_identity`.

3. Replaced temporary BOM code candidate resolution.
   - Update `co_case_bom_product_codes()` to add resolved `material_identity.bom_product_code` before display/customs codes.
   - Removed code-mapping dependency from BOM workspace prefetch paths.
   - Keep case-local manual BOM TP overrides for unresolved or operator-corrected sheets.

4. Bound origin sheets to resolved BOM product codes.
   - In `prepare_case_origin_products()`, use resolved `material_identity.bom_product_code` as the BOM lookup key while retaining the display code as the sheet/product code.
   - In `attach_origin_bom_product_codes()` and `resolve_bom_product_code()`, prefer persisted case override, then resolved Data Hub identity, then display code only when it already exists in the BOM workspace.
   - Keep existing BOM artifact selection behavior because a resolved product code can still have multiple flattened BOM variants.
   - Do not fall back to mapping evidence.

5. Surface unresolved identity states without Data Hub mutation.
   - Treat `ambiguous`, `missing`, and `unverified` as requiring case-local operator selection or showing the existing missing-BOM state.
   - Do not write selections back to Data Hub unless a future mutating contract is approved.

## Tests

- Add adapter tests for explicit `include_material_identity=true` on `invoice_matches()`.
- Add Data Hub portfolio tests for declaration-authoritative matching preserving `material_identity`.
- Replace the existing mapping-bridge test with a `material_identity` resolver test for `BIENTAN.17 -> PV01.0117500`.
- Add negative tests for `ambiguous`, `missing`, and `unverified` statuses not auto-selecting a BOM product.
- Run `uv run pytest tests/test_data_hub_integration.py tests/test_co_demo.py tests/test_data_hub_policy.py`.
- Run full `uv run pytest` after implementation.

## Rollout Notes

- This is a CO consumer-only change. Do not add Data Hub endpoints from this repo.
- Keep raw `/v1/hub/*` endpoint strings confined to `app/data_hub_client.py`.
- After implementation, remove references to the temporary mapping bridge from status docs and tests.
