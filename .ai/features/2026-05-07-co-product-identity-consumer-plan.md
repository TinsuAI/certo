# Feature Plan: Consume Data Hub Product Identity in CO

Date: 2026-05-07

## Context

Data Hub has implemented the BCCT BOM product identity contract requested in `.ai/api-requests/2026-05-07-bcct-bom-product-resolution.md`. CO previously used a temporary `code-mappings` bridge so Growatt display code `BIENTAN.17` could load BOM product `PV01.0117500`. That bridge should now be removed because `code-mappings` is many-to-many evidence, not line-level identity.

## Live Validation

- CO can reach Data Hub at `http://127.0.0.1:8754` with configured service auth.
- `GET /v1/hub/bcct?client_id=growatt-vn&include_product_identity=true` returns `product_identity` for Growatt rows.
- Validated `BIENTAN.17` rows resolve to `PV01.0117500` with `resolution_status=resolved` and `resolution_source=goods_name_embedded_code`.
- `GET /v1/hub/bcct/invoice-matches` returns `product_identity` on invoice-filtered rows.
- CO invoice-only case context currently preserves the field.
- CO declaration-driven case context currently drops the field because it calls `list_bcct()` without `include_product_identity=true`.
- CO still calls Data Hub `code-mappings`; one live context returned `401` for that endpoint, so the new implementation should not depend on it.
- Direct `/bom/latest` for `PV01.0117500` returns `409` because multiple flattened variants exist. This is expected; CO should keep using `DataHubBomService.workspace()` and existing per-case BOM artifact/version binding instead of assuming one latest artifact.
- `DataHubBomService.workspace({"id": "growatt-vn"}, ["PV01.0117500"])` returned 3 product versions/options and 274 BOM rows for the resolved product.

## Implementation Plan

1. Add CO adapter helpers in `app/data_hub_client.py`.
   - Make `invoice_matches()` pass `include_product_identity=true` explicitly.
   - Add `bom_product_code_from_product_identity(row)` that returns a BOM product code only for `resolved` identity.
   - Keep normalization generic; do not parse `goods_name` in CO.

2. Preserve product identity in declaration-driven matching.
   - In `DataHubPortfolioService.co_case_source_context()`, call `list_bcct(client_id, include_product_identity="true")` for case origin context.
   - Keep broad workspace/source-summary list views lightweight unless they need product identity.
   - Add tests proving `match_case_bcct_exports()` output still contains `product_identity`.

3. Replace temporary BOM code candidate resolution.
   - Update `co_case_bom_product_codes()` to add resolved `product_identity.bom_product_code` before display/customs codes.
   - Remove `code_mappings` dependency from BOM workspace prefetch paths after tests cover Data Hub product identity.
   - Keep case-local manual BOM TP overrides for unresolved or operator-corrected sheets.

4. Bind origin sheets to resolved BOM product codes.
   - In `prepare_case_origin_products()`, use resolved `product_identity.bom_product_code` as the BOM lookup key while retaining the display code as the sheet/product code.
   - In `attach_origin_bom_product_codes()` and `resolve_bom_product_code()`, prefer persisted case override, then resolved Data Hub identity, then display code only when it already exists in the BOM workspace.
   - Keep existing BOM artifact/version selection behavior because a resolved product code can still have multiple flattened BOM variants.
   - Do not fall back to `code-mappings`.

5. Surface unresolved identity states without Data Hub mutation.
   - Treat `ambiguous`, `missing`, and `unverified` as requiring case-local operator selection or showing the existing missing-BOM state.
   - Do not write selections back to Data Hub unless a future mutating contract is approved.

## Tests

- Add adapter tests for explicit `include_product_identity=true` on `invoice_matches()`.
- Add Data Hub portfolio tests for declaration-authoritative matching preserving `product_identity`.
- Replace the existing `code-mappings` bridge test with a `product_identity` resolver test for `BIENTAN.17 -> PV01.0117500`.
- Add negative tests for `ambiguous`, `missing`, and `unverified` statuses not auto-selecting a BOM product.
- Run `uv run pytest tests/test_data_hub_integration.py tests/test_co_demo.py tests/test_data_hub_policy.py`.
- Run full `uv run pytest` after implementation.

## Rollout Notes

- This is a CO consumer-only change. Do not add Data Hub endpoints from this repo.
- Keep raw `/v1/hub/*` endpoint strings confined to `app/data_hub_client.py`.
- After implementation, remove references to the temporary `code-mappings` bridge from status docs and tests.
