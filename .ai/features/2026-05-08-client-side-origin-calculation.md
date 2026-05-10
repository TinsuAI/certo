# Feature: Client-Side Origin Sheet Calculation

## Scope
Move the expensive origin-sheet interaction model away from full-form POST/re-render for every action. When a user opens a C/O case origin step, CO preloads one calculation dataset for the case: invoice/export product rows, selected BOM rows, material catalog rows, CO stock rows, form/PSR lane, current persisted sheet states, and source/BOM snapshot metadata. The browser calculates/recalculates sheet results locally for the active sheet and updates the visible grid immediately.

Add an explicit Save/Persist action for calculated sheet changes. Until Save, browser state is draft-only. Save sends a compact JSON payload with changed products/sheet states/source snapshot IDs, not thousands of hidden form fields. Export and final lock still use persisted server state only.

This does not move Data Hub ownership into CO. Data Hub remains the source for BCCT/catalog/BOM identity data; CO only consumes a prepared case calculation payload through existing adapters.

## Decisions
- Keep Python/server calculation as the canonical implementation first. Porting the current logic to browser should be done with parity tests, not by rewriting behavior ad hoc.
- Add a JSON calculation payload endpoint instead of encoding all product/material/allocation rows as hidden inputs. The current template emits product/material/allocation hidden fields for every row, which is the immediate cause of large-field failures and slow DOM/form handling.
- Use client-side calculation for preview responsiveness, but keep server-side validation on Save/Lock/Export. The server must reject stale saves if source snapshot, BOM snapshot, origin order, or locked-sheet state changed.
- Split actions:
  - Calculate sheet: local browser compute only, marks sheet dirty/calculated locally.
  - Save: persists changed calculated sheet(s) and sheet states.
  - Lock/Open lock: server action with sequence validation; can accept only sheet id + revision, not full case form.
  - Export: reads persisted case only, blocks dirty/stale/unlocked sheets.
- Replace product-code keyed state later if duplicate finished-product codes are allowed; current state uses product code as sheet identity.

## Risks
- Parity risk: origin calculation currently lives in Python (`prepare_case_origin_sheet`, `origin_product_from_invoice_match`, `origin_material_from_bom_row`, allocation helpers). A JS port can drift on decimals, rounding, allocation ordering, warnings, and LVC labels.
- Concurrency risk: sequential CO stock allocation depends on prior locked sheets. If browser calculates against a stale preload while another tab/session changes sheet order or lock state, Save must detect revision mismatch.
- Audit risk: customs-origin evidence should not become an unaudited client-only value. Persisted calculation should store source snapshot IDs and enough allocation evidence to explain which import lots were consumed.
- Payload size risk: preloading all stock/BOM rows for large cases can be heavy. The endpoint should scope to case invoice products and selected BOM product codes only.
- Security/trust risk: never trust client-calculated results blindly. Server should recompute or validate the changed sheet on Save/Lock, at least for locked/exportable states.
- Current workaround risk: raising form parser max_fields only masks the bug. It should be removed once JSON payload replaces hidden fields.

## Open Questions
- Do we want exact browser/server parity by sharing a calculation engine? Options: port to TypeScript with golden fixtures, compile a Python-like core to WASM later, or keep server canonical and use client-side only as optimistic preview.
- What is the acceptable Save behavior: save one active sheet only, or save all dirty sheets in one batch?
- Should Lock automatically Save + server-validate first, or require an explicit Save before Lock?
- How large can growatt-vn cases get in practice: max finished products, BOM rows per product, stock lots per material?
- Is duplicate finished-product code in one dossier possible? If yes, sheet identity must be declaration_no + line_no + item_code or generated line id, not product code.

## Implementation Plan
1. Add `GET /clients/{client_id}/co-case/{case_id}/origin/calculation-payload` returning scoped JSON: case header, products, sheet states, origin order, invoice matches, BOM rows, material rows, stock rows, form lane, source snapshot and revision.
2. Add `POST /clients/{client_id}/co-case/{case_id}/origin/save` accepting JSON patches for changed sheets plus expected revision/snapshot IDs. Server validates sequence, stale source, and product identity before persisting.
3. Move lock/reopen/release to small JSON/form actions that do not parse the full origin table.
4. Port the calculation core to a browser module with golden tests generated from Python fixtures for: single lot, multi-lot, shortage, previous-sheet consumption, missing unit value, mixed currency, BOM override.
5. Refactor the template to render visible table from JSON state and remove most per-material/per-allocation hidden inputs.
6. Keep the existing server calculate route temporarily as fallback/debug until parity tests pass and real browser UX is verified.
