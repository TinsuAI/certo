# Sister-app note — Data Hub BOM vocab rename (2026-05-07)

**From:** Data Hub (`~/workspace/client/data-hub`)
**To:** CO maintainers
**Action required:** medium-priority migration before alias removal.
**Posted by:** rename pass session, see Data Hub
`.ai/features/2026-05-07-bom-vocab-rename/brief.md`.

## What changed in Data Hub

Schema + code aligned with canonical 4-tier ontology
(`.ai/GLOSSARY.md` § "BOM model — canonical vocabulary"):

| Concept | Old | New |
|---|---|---|
| Storage row | `bom_versions` | `bom_artifacts` |
| Detail rows | `bom_version_rows` | `bom_artifact_rows` |
| Saved interpretation | `bom_resolution_profiles` | `bom_presets` |
| Storage row id | `version_id` | `artifact_id` |
| Lineage parent | `parent_version_id` | `parent_artifact_id` |
| Materialized FK | `materialized_version_id` | `materialized_artifact_id` |
| FK in presets | `bom_version_id` | `artifact_id` |
| Preset id | `profile_id` | `preset_id` |
| ID prefix (new rows) | `bv_*` | `ba_*` |

Existing `bv_*` IDs persist untouched. Forward-only.

## Impact on CO

CO has 28 references to old names per local grep:

```bash
grep -rn "bom_version" ~/workspace/client/barry-CO-main --include="*.py"
```

Most are in CO's own per-shipment BCCT linkage to Data Hub artifact
IDs (stored as `bom_version_id` in CO's `co` schema). These ID values
remain valid post-rename — only the column name in CO is misleading
now (CO column says `bom_version_id` but the value points at Data
Hub's renamed `bom_artifacts.artifact_id`).

## What CO needs to do

### Required before alias removal (no deadline yet)

1. **Update API consumer code** to use new vocab:
   - Endpoint: `GET /v1/hub/products/{p}/bom/artifacts` (was
     `/bom/versions`)
   - Query param: `?artifact_id=` (was `?version_id=`) — Phase 3
     adds `?preset_id=` (was `?profile_id=`).
   - Response **outer key** for single-BOM endpoints (`/bom/latest`,
     `/bom?artifact_id=…`): **breaking change** — old: `{"version":
     {…}, "rows": […]}`, new: `{"artifact": {…}, "rows": […]}`.
     No alias here (option (a) — ships in same release as URL alias
     period). Update parsing as `data["artifact"]["artifact_id"]`.
   - Response field inside that envelope: `artifact_id` (was
     `version_id`), `artifact_no` (was `version_no`),
     `parent_artifact_id` (was `parent_version_id`).

2. **Optional: rename CO's local `bom_version_id` column** to
   `bom_artifact_id` in CO's schema for vocab consistency. Forward-
   compatible — CO's column name is internal to CO's schema.

### Grace period

Data Hub serves both old and new URLs for one release. Old URLs
return `308 Permanent Redirect` to new URLs. Most HTTP clients
follow redirects automatically; CO's existing code likely keeps
working. Run a manual smoke after Data Hub deploys to confirm.

Removal milestone: when CO + BCQT confirm migration, Data Hub
removes alias routes (BACKLOG.md "Drop BOM vocab v1 aliases").

### Not required

- No data migration. No re-issue of stored IDs.
- No urgency. CO can adopt at its own pace within the grace window.

## References

- Data Hub mig: `db/migrations/031_rename_bom_to_artifact_and_preset.sql`
- Brief: `.ai/features/2026-05-07-bom-vocab-rename/brief.md`
- Glossary: `.ai/GLOSSARY.md` § "BOM model — canonical vocabulary"
- Decision entry: `.ai/DECISIONS.md` § "2026-05-07 BOM vocab rename"
