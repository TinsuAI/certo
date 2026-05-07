# Feature: Phase 3 — BOM resolver + presets + sourcing_choice intent

**Captured:** 2026-05-06
**Vocab updated:** 2026-05-07 — uses canonical terms from `.ai/GLOSSARY.md`
(artifact / preset / shape / strategy). Old terms (version / profile)
appear only when referencing pre-rename DB state.

**Prerequisite:** vocab rename pass (mig 031, see
`.ai/features/2026-05-07-bom-vocab-rename/brief.md`) ships before 3a.
This brief assumes the rename has already landed: `bom_artifacts`,
`bom_presets`, `artifact_id`, etc.

**Estimate:** 25-35h core (resolver + presets + sourcing) + 10-15h
adapter bundle + 6-9h UI upload bundle = ~50h end-to-end if shipped as
one super-feature. Recommend split into 3a/3b/3c (see Open Q1).

## Goal

BCQT/CO can call `/v1/hub/products/{p}/bom?preset_id=X&shape=Y` (or
provide a `case_id` for CO modified-for-case artifacts) and get **one**
deterministic artifact with full provenance — replacing today's path
where consumers either pin `artifact_id` blindly or hit 409 on
dual-source.

## Scope

### In

1. **Resolver core** — extend `app/stores/bom.py` (D1). Inputs:
   `client_id`, `product_code`, optional `preset_id`, optional
   `shape ∈ {raw_graph, shallow, full_flat}`, optional `case_id`.
   Output: `(artifact_id, shape, resolution_trail)` or structured 4xx
   with reason.

2. **Resolution-precedence rule**:
   - `preset_id` (most specific — already pins an artifact).
   - `case_id` (returns the proposal-derived `modified_for_case`
     artifact bound to that case).
   - `shape` (filter to that shape; tie-break on
     `bom_variant_id`+`btp_sourcing` per material classification).
   - default ≡ today's `latest_flattened_artifacts` semantics.

3. **`bom_presets` CRUD** (schema renamed from `bom_resolution_profiles`
   in mig 031; underlying columns from mig 030):
   - `POST /v1/hub/presets` — create
   - `GET /v1/hub/clients/{c}/products/{p}/presets` — list alive
   - `PATCH /v1/hub/presets/{id}` — update sourcing_choices/name/notes
   - `POST /v1/hub/presets/{id}/tombstone` — retract (no DELETE per
     immutability principle)
   - UI page under `app/routes/clients.py` — list + edit per (client, product).

4. **`shape` query param** on `/latest` and `/bom`. When `shape=raw_graph`
   the response shape changes (returns `edges` not flat `rows`); document
   in `docs/API_CONTRACT.md`.

5. **`btp_sourcing` populator + UI**:
   - `scripts/detect_dual_source_btps.py` — auto-classify from
     BCCT (E11/E15/E13 import qty for a code → purchased) ∪ BOM
     (code appears as `parent_code` in `bom_edges` → self_produced)
     ∪ both → `dual_source`.
   - Catalog UI surfaces `btp_sourcing` column with staff override.
   - Resolver consults this when materializing/picking shallow.

6. **`derive_btp_shallows.py` post-ingest hook** for Johnson-shape
   deep-tree raw uploads (see "Modular adapters" entry in BACKLOG.md).
   For each intermediate `parent_code` in `bom_edges` that is `btp_sx`,
   materialize a `bom_artifacts` row keyed to it (status per
   `auto_derive_shallow_from_raw` policy). Closes the 0/342 vs 144/147
   shallow-decomposability gap.

7. **Modular ingest adapters** (BACKLOG.md "Modular BOM ingest adapters"):
   - `app/parsers/bom/adapters/{growatt,johnson,default}.py`
   - Adapter contract: `detect(file) -> match_score`,
     `parse(file) -> list[bom_artifact_payload]`, `post_ingest_hooks: [...]`
   - Selection by `client_id` + filename heuristics; UI override per upload.

8. **UI BOM upload v3 wiring** (BACKLOG.md "UI BOM upload — wire up v3"):
   - `bom_variant_id` field in upload form (multi-supplier-batch;
     hidden when default per GLOSSARY rule)
   - Auto-materialize raw → shallow + full_flat post-confirm,
     gated by `clients.auto_derive_shallow_from_raw`
   - Auto-bootstrap BTP roster
   - Shape badge in preview
   - Multi-role warning when adding a BTP that already appears in BCCT exports
   - Playwright E2E across upload → mapping → parse → preview → confirm

9. **Cross-app coordination**:
   - Sister-app note for CO + BCQT: new `?preset_id` and `?shape`
     params; behavior change on dual-source.
   - No new auth scopes needed (`hub:read` covers preset reads;
     preset writes go through existing user-JWT path, not
     service-account).

### Out

- **Manual / hybrid proposal modes.** Phase 4. Today MVP is auto-only.
- **Preset sharing across products.** Each preset is per-(client,product).
- **Multi-role catalog flag.** Tracked separately in
  `project_bom_code_multirole.md` memory; Phase 4+.
- **Inventory ledger / consumption-aware resolution.** Phase 6+.
- **Resolver on-demand BTP shallow derivation.** All derivation lives
  at ingest time (decision R7 below).
- **`/v1/hub/presets/{id}/preview`.** Could let CO see a preset's
  resolved BOM without committing — defer to Phase 4 unless a real
  caller needs it.

## Decisions

### D1. Resolver lives in `app/stores/bom.py` (extend, not new module).

`stores/bom.py` already owns artifact queries + provenance reads.
Adding `resolve(client_id, product_code, *, preset_id=None, shape=None,
case_id=None)` keeps the BOM-data API surface in one file. New module
would split the read API across two stores for no gain.

### D2. Resolver returns provenance trail, not just artifact_id.

Response includes a `resolution_trail` list explaining each decision:
`["preset=X pinned artifact_id=A"]` or
`["case_id=C → proposal=P → artifact_id=A"]` or
`["shape=full_flat, dual_source on BTP B, picked self_produced_btp_exploded variant"]`.
Critical for CO/BCQT debugging and for customs-audit "why did you use
this BOM in this dossier".

### D3. `derive_btp_shallows` runs at ingest, not at resolver query time.

Post-hook approach. Trade-off: slower upload (acceptable — uploads are
async-friendly), but resolver stays fast + provenance is materialized
once. On-demand derivation would force resolver to do graph walks per
query and complicate caching.

### D4. Preset points at one `artifact_id` (already in mig 030 schema,
column renamed in mig 031).

A preset is "this artifact, interpreted under these sourcing choices".
Preset cannot reference multiple artifacts. If user wants a different
artifact → new preset (cheap; presets are small).

### D5. Tombstoned artifacts remain reachable via preset.

Mig 030 already enforces `on delete restrict` on
`bom_presets.artifact_id` (after rename). Resolver returns the
tombstoned artifact when called via preset (with a warning in
resolution trail). Customs-audit reproduction requires this.

### D6. Phase 3 ships in 3 sub-phases (not one mega-merge).

- **3a (~10h):** `btp_sourcing` populator + catalog UI + resolver
  consults sourcing (still no presets yet). Solves "shallow
  re-materializes correctly when BTPs are classified".
- **3b (~12h):** presets CRUD + UI + resolver respects `preset_id` +
  `case_id`. Solves "CO/BCQT explicit BOM choice".
- **3c (~25h):** modular adapters + `derive_btp_shallows` post-hook +
  UI BOM upload v3 wiring + Playwright E2E. The "everything else".

Each sub-phase is independently shippable + reviewable. Sister apps
adopt at the 3b boundary.

### D7. Don't add a `bom_shape` column on `bom_artifacts`.

Already-decided in mig 030 comment block: `bom_shape()` is a Python
helper deriving from `flatten_status`+`flatten_strategy`. ~625 caller
references depend on the existing two columns. Schema redundancy
buys nothing; existing helper works.

## Risks

### R1. Backward-compat on `/latest` for un-migrated CO/BCQT.

Today /latest returns 409 on dual-source. Phase 3 introduces preset/
shape disambiguation but old clients won't send those params → still
hit 409. Mitigation: documented forcing-function. Alternative
(rejected): pick a "default preset" implicitly — masks the choice.

### R2. `bom_change_requests` already has `materialized_artifact_id`
(after mig 031 rename) linking proposal → artifact. Resolver `case_id`
lookup must walk `context->>'case_id'` on `bom_artifacts` (jsonb GIN
index? add as mini-migration if hot). Acceptance: simple seq scan
first, profile later if slow.

### R3. `derive_btp_shallows` could explode the artifact count.

Johnson has 342 BTPs across 246 alive artifacts; derivation could mint
342 new shallow rows per upload. Mitigation: only mint where
`btp_sourcing != 'purchased_only'` (purchased BTPs don't need shallow
of their own — they're terminal). Sourcing must be populated BEFORE
derivation runs; ordering in adapter post-hook chain matters.

### R4. Preset UI is a new surface for non-trivial CRUD.

Sourcing-choices jsonb editor is the hard part — staff has to pick
per-BTP whether to use purchased/self-produced/dual when the BOM has
overlap. Lean on the catalog-page sourcing column as the source of
truth; preset editor only overrides defaults.

### R5. Multi-role codes (per `project_bom_code_multirole.md` memory).

A code can be TP+BTP+NVL simultaneously. Resolver must not assume
single-role. Today `materials.category` is single-valued — a known
impoverishment. Phase 3 works within this constraint; phase 4+ may
add multi-role flags.

### R6. Adapter selection by filename heuristics is fragile.

Growatt vs Johnson detection from filename alone has been observed to
miss-classify when supplier files are renamed by the agency. Mitigation:
UI lets staff override at upload; default `default.py` adapter is
"best-effort, fail-loud".

## Open Questions

### Q1. Sub-phase split: confirm 3a/3b/3c order or rearrange?

Recommendation: 3a first (smallest, lowest risk, immediate value via
correct shallow re-materialization). 3b second (changes API contract,
needs sister-app coord). 3c last (largest, can be parallelized once
adapter contract is stable).

### Q2. `derive_btp_shallows.py` placement — adapter post-hook (chosen
in D3) vs separate CLI run by staff (deliberate)?

Going with post-hook auto. Open to switching if R3 explosion is real.

### Q3. Default preset per existing TP (Growatt + Johnson)?

If yes: Phase 3 also lands a one-shot script that creates `default`
preset per (client, product) seeded from the latest published artifact
+ inferred sourcing choices. Lets sister apps call with a known
preset_name from day 1.
Lean: yes for the 41 Growatt + ~250 Johnson products that already
have alive published artifacts. Cheap; concrete onboarding aid.

### Q4. Does CO need `?preset_id` from day 1, or stays on `?artifact_id` pin?

`?artifact_id` keeps working. Preset is additive convenience. CO can
adopt at its own pace. Confirm with CO repo's STATUS — if no consumer-
side cycles available, ship Phase 3 server-side and let CO migrate
when ready.

### Q5. `case_id` lookup — index now or wait for evidence of slowness?

Lean: skip the GIN index for now. `bom_artifacts` for any client+product
is small (< 100 rows in practice); seq scan acceptable. Add if a
preset shows >50ms p99.

### Q6. Preset name conventions?

Today schema allows freeform per (client, product). Suggest convention
in docs: `default`, `co-case-{case_id}`, `settlement-{year}`. Don't
enforce in DB — staff workflows differ.

## Manual test plan

After 3a:
- Run `detect_dual_source_btps.py` on Growatt-VN. Verify ≥1 BTP gets
  `dual_source` classification (known: Growatt has at least the 14
  orphan BTPs + several rework cases).
- Re-run `materialize_shallow_and_full_flat.py` for one Growatt TP.
  Verify shallow now stops at `purchased_only` BTPs and explodes
  `self_produced_only` ones.

After 3b:
- Create a preset via API for `growatt-vn / SD00.0010600`. Pin to
  current artifact, set 1 sourcing override.
- `GET /v1/hub/products/SD00.0010600/bom?preset_id=…` — assert
  deterministic artifact + resolution trail contains "preset=… pinned".
- Tombstone the underlying artifact. Preset still resolves; trail
  contains warning.

After 3c:
- Upload a Johnson raw file via UI. Confirm shape badge appears in
  preview; auto-derive shallow lands as `draft`; BTP roster grows
  by N; multi-role warning fires for any code seen in BCCT exports.
- Playwright E2E green.

## Done criteria

- 3a: `btp_sourcing` populated for ≥80% of Growatt + Johnson BTPs;
  catalog UI shows column; resolver consults sourcing in shallow
  re-materialize.
- 3b: preset CRUD endpoints documented in `docs/API_CONTRACT.md`;
  resolver provenance trail surfaces in `/v1/hub/products/.../bom`
  responses; sister-app note posted at
  `.ai/sister-app-notes/2026-MM-DD-bom-resolver-v3.md`.
- 3c: 4 adapters registered + selectable; `derive_btp_shallows.py`
  post-hook fires on Johnson uploads; Playwright E2E for UI upload
  flow committed under feature folder.
- All sub-phases: `/rev` clean (or known-deferred items moved to
  BACKLOG.md); test count grows; `STATUS.md` + `DECISIONS.md` updated.

## Suggested next step

Land vocab rename pass (mig 031) first — see sibling brief
`.ai/features/2026-05-07-bom-vocab-rename/brief.md`. After rename
ships and CI is green: confirm sub-phase split + Q3 default-preset
question with user, then `/tdd` for sub-phase 3a (resolver + sourcing
populator + catalog UI). Estimated 10h, single bundled commit.
