# Sister-app note — Data Hub BOM presets (Phase 3b, 2026-05-07)

**From:** Data Hub (`~/workspace/client/data-hub`)
**To:** CO maintainers
**Action required:** opt-in, not blocking. CO can adopt at its own pace.
**Posted by:** Phase 3b session, see Data Hub
`.ai/features/2026-05-06-phase-3-resolver-profiles/brief.md`.

## What landed

Data Hub now supports a **preset** abstraction for BOM resolution.
Endpoints (all under `/v1/hub/`):

- `POST /presets` — create
- `GET /clients/{c}/products/{p}/presets` — list alive
- `PATCH /presets/{id}` — partial update
- `POST /presets/{id}/tombstone` — retract (no DELETE per immutability)

The single-BOM read endpoint `GET /products/{p}/bom` accepts new
query hints (precedence highest first):

  artifact_id > preset_id > case_id > shape > default

Where:
- `artifact_id`: existing raw pin. No resolver invoked.
- `preset_id`: new. Resolves via `bom_presets`.
- `case_id`: new. Matches `bom_artifacts.context->>'case_id'`.
- `shape`: new. One of `raw_graph` / `shallow` / `full_flat`.

Response carries `resolution_trail` (list of strings) when any
resolver hint was used — explains each pick step for audit / debug.

Error codes (all structured JSON; `detail.error` carries the enum):
`preset_not_found`, `preset_scope_mismatch`, `case_not_found`,
`no_artifact_for_shape`, `no_alive_artifacts`, `dual_source_variants`.

## Why this matters for CO

Today CO either:
1. Pins `artifact_id` from a previous successful resolution.
2. Calls `/bom/latest` and hits 409 on dual-source.

After 3b, CO can:
- Pin a `preset_id` per case → single name resolves to one artifact
  even if the underlying artifact_id rotates.
- Use `?case_id=co_xxx` to retrieve a CO-modified artifact bound to
  that case (typed via `intent='modified_for_case'`,
  `context->>'case_id'`).
- Provide explicit `?shape=` to disambiguate dual-source instead of
  carrying retry logic for the 409.

Sourcing-choice semantics inside a preset (jsonb) are **not yet wired
into the resolver** — that's Phase 3+ scope. For 3b a preset just
pins an artifact + name + provenance. Phase 3+ will make the resolver
honor `sourcing_choices` overrides during materialization.

## What CO can do now

**Option A — adopt presets** for production CO cases:
1. On case creation, POST a preset bound to the relevant
   `bom_artifacts.artifact_id`. Name convention: `co-case-{case_id}`.
2. Switch resolver call from `?artifact_id=` to `?preset_id=`.
3. On case modification (CO edits BOM via existing proposal flow),
   the resulting `modified_for_case` artifact lives under the same
   preset + a fresh artifact_id (or new preset, your call).

**Option B — keep raw pin**, ignore presets for now. Old endpoint
behavior unchanged. Add preset usage when 3+ ships sourcing override.

## Sister-app coordination details

- **Auth**: presets endpoints use the existing user JWT path
  (`bearer` from CO's service account if authorized; otherwise admin
  JWT). No new scopes needed (`hub:read` for reads, write goes
  through user-JWT path).
- **Pre-MVP wipe**: Data Hub is queued for one-shot wipe + ingest
  fresh post-Phase-3 (memory `project_reingest_pending.md`). CO's
  stored `bv_*` artifact IDs (and any `bp_*` presets) will become
  invalid after the wipe — acceptable pre-MVP. Plan around this.

## References

- Spec: `.ai/features/2026-05-06-phase-3-resolver-profiles/brief.md`
- Data Hub session: 2026-05-07 — Phase 3b implementation
- API contract update: `docs/API_CONTRACT.md` § Presets
- Resolver implementation: `app/stores/bom.py::resolve_bom_artifact`
