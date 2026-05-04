# Data Hub BOM Flattening Implementation Instructions

Use this document as the implementation prompt for Claude Code in the Data Hub repo:

```text
You are working in /home/vp/workspace/client/data-hub.

Goal: implement technical BOM to calculation-ready BOM flattening in Data Hub before CO migrates to Data Hub-owned BOM.

Current known state:
- Data Hub already stores BOM versions and proposal records.
- Data Hub has BOM parsers in app/parsers/bom.py for manual_flat, growatt_multi_workbook, and johnson_sap_exploded.
- These parsers currently parse workbook layout into rows. They do not implement a full technical-BOM graph flattener.
- Data Hub upload flow currently parses -> previews -> create_version. It does not have a dedicated flattening stage.
- CO will migrate later. Do not change the CO repo in this task.

Mandatory context to read first:
- Data Hub:
  - AGENTS.md
  - .ai/STATUS.md
  - .ai/DECISIONS.md
  - docs/API_CONTRACT.md
  - app/parsers/bom.py
  - app/routes/bom.py
  - app/stores/bom.py
  - db/migrations/006_bom.sql and later BOM-related migrations
  - tests/test_parsers.py
  - tests/test_real_data_external.py
- Old CO reference implementation:
  - /home/vp/workspace/client/barry-CO-main/app/bom_store.py
  - /home/vp/workspace/client/barry-CO-main/app/workflow_state_store.py
  - /home/vp/workspace/client/barry-CO-main/db/migrations/005_workflow_state.sql
  - /home/vp/workspace/client/barry-CO-main/tests/test_co_demo.py BOM-related tests

Use old CO code as domain reference, not as code to copy blindly. Preserve Data Hub ownership, API contract discipline, and append-only versioning.

## Domain Terms

- TP: finished product.
- BTP: semi-finished product / sub-assembly.
- NVL: raw/imported material used for calculation.
- BCCT: customs declaration source rows. Import declarations are evidence that a code can be purchased/imported.
- Technical BOM: a parent-child manufacturing structure that may include BTP and may require graph expansion.
- Flattened BOM: a calculation-ready version whose terminal nodes are all resolved to leaf materials or purchased/imported BTP treated as leaf.
- Non-flattened BOM: a stored version that still contains unresolved BTP/sub-assembly/material nodes. It is preserved for audit/review and must not be silently treated as calculation-ready.

## Scope

Implement a technical BOM flattening layer in Data Hub:
- Parse technical BOM rows.
- Build a BOM graph.
- Store BOM TP and BOM BTP versions.
- Produce flattened output where possible.
- Preserve non-flattened output where unresolved nodes remain.
- Surface the result in upload preview before confirm.
- Keep existing manual_flat behavior backward compatible.

Out of scope:
- CO migration.
- Direct consumer writes to the hub Postgres schema.
- Public API invention for CO beyond existing documented Data Hub contract unless a contract change is explicitly required and documented.
- Guessing material roles without evidence.

## Core Rules

### 1. Store BOM TP and BOM BTP

Data Hub must store both finished-product BOMs and semi-finished-product BOMs.

Rules:
- Do not drop BTP just because it is not a final exported product.
- If a code appears as a component in another BOM and also has its own BOM, store that child BOM as its own BOM product/sub-assembly version.
- Keep lineage so a TP version can show which BTP version/path was used during flattening.

### 2. Support Two BOM Version Statuses

There are two calculation statuses:
- flattened: all terminal nodes are resolved.
- non_flattened: at least one branch still has unresolved nodes.

Important:
- non_flattened data must be stored, not discarded.
- non_flattened versions must carry explicit unresolved reasons and review_required metadata.
- CO/BCQT calculations must use flattened versions only unless a future approved contract says otherwise.
- Do not overload existing actor/intent fields to represent this. Add explicit fields if needed, for example:
  - flatten_status
  - source_bom_kind
  - flatten_strategy
  - flatten_context
  - unresolved_nodes
  - classification_evidence

### 3. Graph Identity

Do not key the graph only by product_code.

Graph identity should include:
- product_code
- bom_code when available
- bom_variant_id when available

If variant fields are absent, use a deterministic default such as "default", but do not merge variants when source data distinguishes them.

### 3A. BOM Version Naming And Identity Convention

Every BOM version must be self-describing. Looking at a version record should make it clear what kind of version it is, whether it is flattened, where it came from, and what calculation strategy it represents.

Required identity fields/concepts:
- `version_id`: immutable opaque ID.
- `client_id`.
- `product_code`.
- `bom_code`.
- `bom_variant_id`.
- `version_no`: monotonic within a stable graph key.
- `source_bom_kind`: for example `manual_flat`, `technical_raw`, `technical_flattened`, `technical_non_flattened`, `co_modified`, `staff_edit`.
- `flatten_status`: `flattened`, `non_flattened`, or `not_applicable`.
- `flatten_strategy`: for example `manual_flat_as_provided`, `technical_exploded`, `purchased_btp_as_leaf`, `self_produced_btp_exploded`, `mixed_confirmed`.
- `source_channel`: for example `agency_upload`, `staff_form`, `co_proposal`, `migration`, `seed`.
- `source_upload_id` or source proposal/migration ID.
- `parent_version_id` when derived from another version.
- `lineage`: parent chain / child BOM versions used.
- `display_label`: human-readable label for UI, derived from fields above.

Recommended display label convention:
- `{product_code} · {bom_variant_id} · v{version_no} · {source_bom_kind} · {flatten_status} · {flatten_strategy}`
- Example: `TP-A · default · v3 · technical_flattened · flattened · self_produced_btp_exploded`
- Example: `TP-A · purchased-B · v4 · technical_flattened · flattened · purchased_btp_as_leaf`
- Example: `BTP-B · default · v2 · technical_non_flattened · non_flattened · missing_child_bom`

Rules:
- Do not use display_label as a database key.
- Do not encode business meaning only in display_label; every part must exist as structured fields.
- Do not overload `actor` or `intent` to represent version kind or flattening. `actor` answers who/what created it; `intent` answers why; the fields above answer what artifact it is.
- Version numbering must not mix unrelated variants. If `bom_variant_id` or `flatten_strategy` creates a distinct variant, either version_no must be scoped to that variant key or the UI must show enough structured identity to avoid confusion.
- "Latest" must be a query constrained by status and strategy. A generic latest-by-product is unsafe when dual-source or non_flattened variants exist.

### 3B. Language And I18n Rule

Persist stable English machine codes in the database and API payloads.

Rules:
- Do not store Vietnamese UI text as source-of-truth data.
- Enum/code fields must use stable English codes, for example `flattened`, `non_flattened`, `purchased_btp_as_leaf`, `self_produced_btp_exploded`, `uom_conversion_missing`, `bcct_import`.
- UI should translate codes into Vietnamese through i18n dictionaries.
- Audit/provenance should store structured codes plus evidence. Human-readable Vietnamese text should be derived at render time.
- If display_label is persisted, it is secondary/cache only and must not be used for business logic.
- Tests should assert code values, not Vietnamese labels.

### 4. Dual-Source Codes Are Normal

A code can appear in multiple roles over time:
- imported material/BTP in BCCT,
- self-produced BTP with its own BOM,
- exported finished product,
- component input for another product,
- recycled/reworked/version-changed material.

Do not assume one code has exactly one global role.

Classification must be evidence-based and context-aware.

### 5. BCCT Import Evidence Rule

If a component code appears in BCCT import declarations for the client, it can be treated as purchased/imported BTP for that context and therefore used as a leaf material for flattening.

This rule does not erase any child BOM for the same code. Keep both facts:
- It can be a purchased/imported leaf in one context.
- It can be exploded through its child BOM in a self-produced context.

Evidence scope:
- BCCT import evidence must be scoped to the same client.
- Use import declarations only. Export evidence alone does not prove the code can be treated as purchased/imported leaf.
- Preserve the evidence used, such as declaration type, declaration date/year if available, and matched code field.
- If a future transaction/case date is available, prefer evidence available at or before that date. If no transaction date is available during canonical BOM upload, record that the evidence is generic current client evidence.

### 6. Component Classification Decision Order

For each component in a BOM path:

1. If the source row/context explicitly says purchased, imported, outsourced, or "do not explode", treat it as leaf.
2. Else if BCCT import evidence exists for that code and there is no explicit self-produced instruction in this BOM path, treat it as purchased BTP / leaf material.
3. Else if a child BOM exists in the same upload, explode it.
4. Else if a current child BOM exists in Data Hub, explode it.
5. Else if catalog marks it as active imported/NVL material, treat it as leaf.
6. Else keep it unresolved and mark the version non_flattened.

For every decision, preserve classification evidence, for example:
- bcct_import
- child_bom_same_upload
- child_bom_current_db
- catalog_imported_nvl
- explicit_self_produced
- explicit_purchased
- unresolved_missing_child_bom

### 7. Dual-Source Flattening Variants

If TP A uses BTP B and B has both BCCT import evidence and a child BOM, both flattened variants can be valid:

1. purchased/imported B as leaf:
   - A -> B
   - B is terminal because it is purchased/imported.
   - flatten_strategy = purchased_btp_as_leaf

2. self-produced B exploded through B's BOM:
   - A -> B -> NVL children
   - flatten_strategy = self_produced_btp_exploded

Rules:
- Do not overwrite or merge these variants.
- Store separate versions/variants with explicit flatten_strategy and provenance.
- Both may have flatten_status = flattened if no unresolved nodes remain.
- Preview must show the dual-source branch and require staff to confirm which variant(s) to publish.
- Consumers must bind to a specific BOM version/variant, not generic latest-by-product, when dual-source variants exist.

The component classification decision order defines the default branch for a single output. It must not suppress valid alternate dual-source variants. If both purchased and self-produced paths are valid, generate both candidate variants and let preview/confirm decide which one(s) to publish.

### 8. Same-Upload Precedence

When one upload contains both TP and BTP BOMs:
- Parse all rows first.
- Build the full graph for the pending upload.
- Use BTP BOMs from the same pending upload before older Data Hub versions when flattening TP in that upload.
- Confirm should materialize versions consistently so TP provenance points to the BTP source used.

### 9. Quantity And UOM Rules

Quantity multiplication:
- Normalize units before multiplying quantities across graph levels.
- Prefer the canonical UOM from the client catalog/material registry for each code.
- Multiply quantities only after converting source row UOMs into the canonical UOM for the relevant material/BTP.
- Preserve numeric precision. Avoid lossy float behavior if the surrounding code supports Decimal.
- Preserve the original quantity/unit values and converted quantity/unit values in provenance.

UOM model requirements:
- Build or extend a standard UOM table with canonical unit codes and aliases.
- Support unit aliases, including Vietnamese labels, English labels, punctuation/case variants, and common abbreviations.
- Build or extend a conversion table for concrete unit conversions.
- Support client-specific conversion overrides because the same unit label may be context-dependent by client/product/material.
- Conversion lookup order should be:
  1. Exact client-specific conversion for `(client_id, material_or_product_code, from_uom, to_uom)` if available.
  2. Client-specific conversion for `(client_id, from_uom, to_uom)`.
  3. Global standard conversion for compatible units.
  4. Alias-only normalization when units are equivalent.
  5. No conversion available.

UOM conversion behavior:
- If catalog has canonical UOM for the code, convert to that UOM.
- If catalog has no canonical UOM, use the BOM row UOM but mark provenance as `canonical_uom_missing`.
- If a conversion exists, apply it and record conversion evidence: source, factor, from_uom, to_uom, and whether it was client-specific or global.
- If multiple conversions match with the same precedence, do not choose silently; mark unresolved with reason `uom_conversion_ambiguous`.

If a conversion is required and no conversion rule exists:
- Do not guess.
- Keep that branch unresolved.
- Mark flatten_status = non_flattened.
- Add unresolved reason uom_conversion_missing.

### 10. Cycle And Error Handling

Cycle handling:
- Detect cycles in the BOM graph.
- Reject the affected flatten operation with a clear error, or store a non_flattened/review_required version only if the chosen design preserves the cycle evidence safely.
- Do not publish a version that silently drops cycle branches.

Missing child BOM:
- Do not drop the row.
- Store it as unresolved in non_flattened output with reason missing_child_bom unless BCCT/catalog evidence supports treating it as leaf.

Silent corruption is worse than a blocked upload. If confidence is low, keep review_required/non_flattened instead of pretending the output is flattened.

### 11. Staff Confirmation Gates

Many BOM decisions are business decisions, not parser decisions. They must be shown in preview and confirmed by staff before materializing versions. Do not silently choose defaults for these cases.

Must require explicit staff confirmation:
- Publishing any non_flattened/review_required version.
- Choosing purchased_btp_as_leaf vs self_produced_btp_exploded for a dual-source component.
- Treating a component as purchased/imported leaf because BCCT import evidence exists while a child BOM also exists.
- Using current Data Hub child BOM version when the child BOM is not present in the same upload.
- Choosing among multiple possible child BOM versions/variants for the same component.
- Applying any UOM conversion that is not pure alias-equivalent normalization.
- Applying global UOM conversion when no client-specific conversion exists.
- Proceeding when catalog canonical UOM is missing.
- Proceeding when BCCT import evidence is generic current-client evidence because no transaction/case date is available.
- Publishing a new version whose row count, component set, or converted quantity changes materially from the previous version.
- Resolving duplicate/conflicting source rows for the same graph key.

Can be automatic without special confirmation:
- Exact alias normalization where from_uom and to_uom are equivalent canonical units.
- Exact client-specific conversion for the same client and material/product code, if it is active and unambiguous.
- Treating a component as leaf when catalog clearly marks it as active imported/NVL and no child BOM exists.
- Exploding a child BOM from the same pending upload when no dual-source/import evidence conflict exists.

Implementation requirement:
- The flattener should return a list of decision records, not only flattened rows.
- Each decision record should include decision_type, chosen_action, alternatives, evidence, confidence/status, and whether staff_confirmation_required is true.
- Preview must render staff_confirmation_required decisions clearly before confirm.
- Confirm must persist the confirmed decisions in version context/provenance.
- Tests must assert that high-risk decisions are not materialized without confirmation.

## Data Model Requirements

If current schema is insufficient, add a migration.

The implementation must store:
- Raw/technical parsed rows or enough parsed-source payload for audit.
- Flattened rows.
- Non-flattened/unresolved rows.
- BTP BOM versions.
- Canonical UOM and converted quantity where conversion was applied.
- UOM alias/conversion evidence.
- Staff-confirmed decision records.
- Structured version identity fields and display labels.
- Stable English machine codes for statuses, strategies, reasons, and evidence.
- flatten_status.
- flatten_strategy.
- unresolved_nodes with reason codes.
- classification_evidence.
- Parent chain / component path provenance.
- flatten_method and flatten_method_version.
- Source upload ID and source row references when available.

Keep Data Hub BOM versions append-only. Do not update existing versions in place to change flatten outcome.

## Upload Flow Requirements

Add explicit upload/profile mode for technical BOM flattening. Do not hide flatten behavior behind manual_flat.

Existing manual_flat:
- Must stay backward compatible.
- Should still create versions as it does today unless a deliberate migration changes that behavior with tests.

Technical flatten mode:
- Parse workbook.
- Build graph.
- Classify components.
- Generate flattened and non_flattened outputs.
- Stash everything in pending preview.
- Preview before confirm.
- Confirm creates Data Hub BOM versions for both TP and BTP as applicable.

Preview must show:
- Parsed technical summary.
- BTP BOMs detected.
- Flattened output sample.
- Non-flattened/unresolved rows.
- Counts by product/BTP/status.
- Staff confirmation decisions and required choices.
- Dual-source decisions.
- Classification evidence for ambiguous branches.
- UOM conversion issues.
- Which variants will be published.

## API And Consumer Contract

Do not change CO in this task.

If public BOM API responses need to expose flatten_status, flatten_strategy, or unresolved_nodes, update docs/API_CONTRACT.md and provider tests.

Consumer rules:
- CO and BCQT must be able to distinguish flattened vs non_flattened versions.
- Calculation consumers must not accidentally use non_flattened versions.
- For dual-source variants, consumers must bind to an explicit version/variant.

## Tests First

Write failing tests before implementation for:

1. Simple 2-level flatten.
2. Multi-level quantity multiplication.
3. UOM alias normalization converts equivalent units to catalog canonical UOM.
4. Client-specific UOM conversion takes precedence over global conversion.
5. UOM mismatch with available conversion produces flattened rows with conversion evidence.
6. UOM mismatch without conversion produces non_flattened with uom_conversion_missing.
7. Ambiguous UOM conversion produces non_flattened with uom_conversion_ambiguous.
8. BTP BOM is stored as its own version.
9. TP using BTP resolves to NVL when child BTP BOM exists.
10. TP remains non_flattened when child BTP BOM is missing and no import/catalog leaf evidence exists.
11. A component with BCCT import evidence and no explicit self-produced context is treated as leaf, even if it has appeared as a product elsewhere.
12. A dual-source component with both BCCT import evidence and child BOM is surfaced in preview with classification evidence.
13. Explicit self-produced context forces explosion through child BOM.
14. TP A using dual-source BTP B can publish two valid flattened variants: purchased_btp_as_leaf and self_produced_btp_exploded.
15. A code that is exported as TP and also used as input for another product does not break graph identity or flattening.
16. Cycle detection.
17. Same-upload BTP version takes precedence over older DB BTP version.
18. Dual-source branch cannot be materialized without explicit confirmation.
19. Non_flattened/review_required version cannot be materialized without explicit confirmation.
20. Global UOM conversion without client-specific conversion appears as staff_confirmation_required.
21. Exact alias normalization does not require special confirmation.
22. BOM version records include structured identity: source_bom_kind, flatten_status, flatten_strategy, source_channel, lineage, and display_label.
23. Generic latest-by-product does not accidentally select non_flattened or wrong dual-source variant.
24. Stored statuses, strategies, reasons, and evidence use stable English machine codes, not Vietnamese UI labels.
25. Existing manual_flat tests remain green.
26. Upload preview/confirm creates expected versions, statuses, evidence, decisions, and rows.
27. Public API tests if response shape changes.
28. Real-data smoke tests gated behind DATA_HUB_REAL_DATA_DIR when fixtures are available.

## Suggested Implementation Sequence

1. Discovery pass:
   - Read current Data Hub BOM schema/routes/store/parser.
   - Read old CO BOM store and tests for domain behavior.
   - Write a short feature brief if the implementation shape differs from this prompt.

2. Schema pass:
   - Add explicit flatten fields/tables if current hub.bom_versions and hub.bom_version_rows cannot safely hold the required metadata.
   - Keep migrations small and reversible where possible.

3. Flattener core:
   - Implement pure functions/classes for graph building, classification, flattening, cycle detection, and status output.
   - Keep this independent from FastAPI routes.

4. Store integration:
   - Extend app/stores/bom.py to materialize versions with flatten metadata.
   - Preserve append-only and idempotency behavior.

5. Upload integration:
   - Add explicit technical flatten mode.
   - Route through pending preview.
   - Confirm materializes versions only after staff review.

6. API/docs:
   - Expose flatten metadata only if needed by current public endpoints.
   - Update docs/API_CONTRACT.md and tests when public contract changes.

7. Verification:
   - Run targeted BOM tests.
   - Run full Python suite.
   - Run gated real-data smoke if fixtures are configured.

## Acceptance Criteria

Implementation is not done until:
- Technical BOM can produce flattened versions with complete provenance.
- BTP BOMs are stored as first-class versions.
- Non-flattened output is stored with explicit unresolved reasons.
- Dual-source BTP can produce separate valid variants without merging.
- BCCT import evidence can classify purchased/imported BTP as leaf.
- UOM conversion normalizes aliases, prioritizes catalog canonical UOM, supports client-specific conversion, and never silently produces wrong quantities.
- High-risk classification, variant, non_flattened, and UOM decisions require staff confirmation and are persisted as provenance.
- BOM version identity is structured and self-describing; UI labels are derived from structured fields, not the source of truth.
- DB/API values use stable English machine codes; Vietnamese belongs in UI/i18n rendering.
- Same-upload BTP precedence is tested.
- Existing manual_flat behavior remains green.
- Public API contract, if changed, is documented and tested.

Report back with:
- Schema/code changes.
- Exact flatten vs non_flatten semantics.
- How BOM BTP is stored.
- How dual-source decisions are represented.
- What is still unsupported.
- Test commands and results.
```

## Review Notes

This prompt is intentionally strict because BOM flattening is source-of-truth logic. The high-risk failure mode is silent corruption: treating a BTP as exploded when it was purchased, treating a purchased BTP as self-produced, multiplying incompatible UOMs, or publishing "latest" without variant binding.

Review conclusions:
- The prompt now separates calculation readiness (`flatten_status`) from provenance (`actor`/`intent`) and from strategy (`flatten_strategy`).
- It explicitly stores both TP and BTP BOMs.
- It handles dual-source codes as context-dependent facts, not global classifications.
- It covers the valid case where TP A has two flattened variants because BTP B may be purchased as leaf or self-produced via child BOM.
- It blocks the most dangerous UOM ambiguity by requiring canonical catalog UOM, aliases, global conversions, client-specific conversions, and explicit unresolved status when conversion is missing or ambiguous.
- It prevents silent business decisions by requiring explicit staff confirmation for dual-source, non_flattened, ambiguous variant, generic evidence, material change, and non-trivial UOM decisions.
- It requires structured BOM version identity so users and consumers can tell what each version is, instead of guessing from raw version numbers.
- It keeps DB/API values stable and English-coded while leaving Vietnamese wording to the UI/i18n layer.
- It gives Data Hub implementation work before CO migration and keeps CO out of scope.
