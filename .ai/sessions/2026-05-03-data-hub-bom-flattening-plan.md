# Session: Data Hub BOM Flattening Plan

## What Was Done
- Refreshed the CO project state from `.ai/STATUS.md`, `.ai/DECISIONS.md`, and recent session summaries.
- Started the CO dev server earlier in the session and verified `/` redirected with `303` to `/auth/login` because `CO_AUTH_REQUIRED=1`; CO was no longer listening at handoff.
- Fast-forward merged `sprint/postgres-source-indexes-20260430` into `main`. No push was performed.
- Explained the current CO/Data Hub BOM ownership:
  - CO currently stores BOM state locally/Postgres.
  - Data Hub owns shared BOM directionally, but CO has not migrated to Data Hub BOM APIs.
- Investigated the sibling Data Hub repo enough to answer whether it can already support CO BOM migration:
  - Data Hub has BOM schema, read APIs, proposal API, upload preview, and local BOM data.
  - Data Hub does not yet implement a full technical BOM graph flattener.
- Created `.ai/features/2026-05-02-co-bom-data-hub-migration/brief.md` describing the future CO migration path after Data Hub BOM is ready.
- Created `.ai/features/2026-05-02-data-hub-bom-flattening-instructions.md`, a detailed implementation prompt for a Data Hub agent.
- Iteratively strengthened the Data Hub BOM flattening prompt with user feedback:
  - Store both BOM TP and BOM BTP.
  - Support both `flattened` and `non_flattened` versions.
  - Preserve non-flattened/unresolved data instead of rejecting or dropping it.
  - Treat BCCT import evidence as purchased/imported BTP that can be leaf/NVL for that context.
  - Support dual-source codes and allow TP A to have multiple valid flattened variants when BTP B can be purchased as leaf or self-produced through a child BOM.
  - Add UOM alias and conversion requirements, including global conversions and client-specific overrides.
  - Require staff confirmation for high-risk decisions instead of silently choosing.
  - Add structured BOM version identity conventions so version records show kind, flatten status, source, strategy, channel, lineage, and display label.
  - Require stable English machine codes in DB/API and Vietnamese UI/i18n rendering.

## Decisions Made
- Do not migrate CO to Data Hub BOM yet. Data Hub must implement technical-to-flat BOM conversion first.
- Data Hub, not CO, should own canonical BOM flattening and BOM BTP storage.
- CO should later keep only case-level BOM bindings/snapshots/proposal IDs, not canonical BOM source-of-truth data.
- Data Hub should store `non_flattened` versions with explicit unresolved reasons; calculation consumers should not silently use them.
- Dual-source classification is context-dependent, not a global code property.
- UOM conversion must prefer catalog canonical UOM and use structured conversion tables. Missing or ambiguous conversions become unresolved/non-flattened, unless staff-confirmed rules exist.
- High-risk BOM decisions must be previewed and confirmed by staff before materialization.
- DB/API values should be stable English machine codes; Vietnamese belongs in UI/i18n only.

## What Didn't Work
- Initial assumption that Data Hub was ready to be the complete BOM owner was too broad. It has BOM storage/API, but not the technical flattening engine needed for CO migration.
- The first migration prompt did not explicitly cover BOM BTP, non-flattened storage, dual-source variants, UOM conversion, staff confirmation, version identity, or i18n. These were added through review.
- A Data Hub explorer sub-agent was started but ran too long; it was shut down. Direct targeted reads and DB checks were enough to confirm the key state.

## Open Items
- In the Data Hub repo, implement `.ai/features/2026-05-02-data-hub-bom-flattening-instructions.md`.
- After Data Hub implementation, update CO to consume Data Hub BOM through `app/data_hub_client.py` only.
- Decide which existing CO-local BOM versions are legal/business data to migrate versus demo/dev artifacts to archive.
- Existing `npm test` legal lookup `raw-binary` failures remain unrelated and unresolved.
