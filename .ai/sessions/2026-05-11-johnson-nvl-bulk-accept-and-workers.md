# Session 2026-05-11 — Johnson NVL bulk-accept + embeddings + 4-worker dev

Follow-up to the same-day `co-bearer-and-bom-description` session.
Driven by user investigation of a specific Johnson BOM artifact, then
broadened to fill out the entire NVL catalog and run the embedding
pipeline.

## What Was Done

### Investigation: artifact `ba_Vvkg7JQ2eSQ6XZe8` (MPL0109-39)

User asked why so many NVL in this artifact's flatten weren't in
catalog or BCCT. Suspected BTP_SX bị lẫn. Audit:
- 208 distinct codes in `bom_artifact_rows`.
- 111 in catalog, 97 missing.
- Of the 97: 0 in BCCT, 0 appear as `parent_code` in any Johnson
  bom_edges, 0 are TP roots. 97/97 are pure leaf-only child codes.
- Conclusion: not BTP_SX bị lẫn. Pure NVL leaves Johnson never imported
  (VN-domestic supply or free-supplied parts).
- catalog_candidates feed was empty for johnson-vn — `refresh_candidates`
  hadn't been run since the BOM ingest. Ran it: 1207 candidates
  surfaced, including the 97.

### A.7 backfill on existing Johnson BOM (commit 41c8f72)

`scripts/backfill_johnson_bom_description.py`:
- Walks 106 Johnson SAP XLSX in
  `data/source_inventory/johnson-vn/2026-05-07-updated/Johnson/TECHNICAL BOM - JOHNSON/`.
- Parses with the A.7-enhanced `parse_sap_indented_raw_edges`.
- In-place UPDATEs `bom_edges.payload` to add `description`, matched by
  `(artifact_id, source_row_no)`. Idempotent.
- 27,848 / 27,848 TP raw edges populated.
- BTP slice artifacts skipped (their bom_edges have NULL source_row_no
  per session 2026-05-11 dedup fix). Candidate refresh UNIONs across
  all alive artifacts, so TP-raw side is enough for sample_text.

Then ran `refresh_candidates('johnson-vn')` — 1207 entries with
sample_text populated for the 97 orphan codes.

### Bulk-accept 97 → catalog (commit 41c8f72 cont'd)

`scripts/accept_nvl_candidates_from_artifact.py`:
- Filters: candidate.client matches, code in target artifact's
  bom_artifact_rows, status=pending, bom_role=nvl_leaf, not in materials.
- Accepts each via `accept_candidate(category='nvl', status='active',
  name=sample_text, uom=candidate.uom)`.
- 97/97 accepted with descriptions like `Round Steel;Round;20CrMo;φ26;;`
  (SAP Object description).

After: 208/208 codes in `ba_Vvkg7JQ2eSQ6XZe8` have catalog entries.

### Broad sweep + embedding (commit 1459678 + live ops)

User asked to fill all NVL leaves across full_flat, accept, run embed.
Extended the script with `--all-full-flat` mode (mutually-exclusive arg
group):
- Selects every distinct `material_code` from any alive
  technical_flattened+flattened bom_artifact_rows.
- Same accept filter (status=pending + bom_role=nvl_leaf + not in
  materials).
- Ran on Johnson: 1110/1110 NVL leaves accepted. Catalog NVL count
  8244 → 9451.

Then `scripts/embed_materials.py --client johnson-vn --commit`:
- 1207 dirty materials (97 + 1110 from this session, hash mismatch).
- OpenRouter `text-embedding-3-small`, dim=1536, batch_size=100.
- 35.1s total, 61.4 items/s, no failures.
- Final: 9451 / 9451 Johnson NVL have `description_embedding`.

### Dev server 4 workers (commit fce752d)

User direction: "dev server luon start voi 4 workers". Implemented:
- Killed existing `--reload` server.
- Started new with `--workers 4`, no `--reload` (uvicorn flags
  mutually exclusive).
- Verified parent + 4 worker processes via uvicorn log
  ("Started server process" × 4 + "Application startup complete" × 4).
- Updated `AGENTS.md` (CLAUDE.md symlinks to this) Build & Run section.
- Updated memory `feedback_dev_server_at_session_start.md`.

## Decisions Made

1. **In-place jsonb UPDATE instead of wipe + re-ingest.** A.7 parser
   change only adds an optional `description` key to bom_edges.payload.
   No semantic change to qty/parent/child. Doesn't violate
   `project_bom_immutable_principle` (which is about DELETE / version
   edits). Idempotent UPDATE was 100× faster than a wipe-and-reingest
   cycle (~5s vs ~5-10min) and didn't create stale FK references.

2. **Backfill only TP raw artifacts, skip BTP slices.** BTP slices came
   from `derive_btp_shallows._subtree_edges` which nulled out
   source_row_no (per 2026-05-11 dedup fix). Match key would be lossy
   `(parent_code, child_code, qty)` and BTP slices share these across
   parent TPs anyway. Candidate refresh's UNION over all alive
   artifacts means TP-raw side covers the use case. Cost: BTP slice
   detail pages won't show description (acceptable; the candidate feed
   was the driver).

3. **Auto-accept as `category='nvl'`, `status='active'`** — user's
   direction "duyet vao catalog". Default `accept_candidate` status
   is `under_review`; user wanted live so substitute pipeline can use
   them. Materials carry name from sample_text (SAP Object description),
   uom from candidate.uom (richness enrichment). production_source
   left null since no BCCT signal.

4. **Two passes (narrow then broad), not one.** Pass 1 was a
   focused validation against the specific artifact the user
   investigated. Pass 2 broadened to all full_flat leaves. Splitting
   gave a confidence checkpoint before bulk-accepting 11× as many
   rows. Both committed; second pass also added the `--all-full-flat`
   mode for future reuse.

5. **4 workers over reload** for dev server. Uvicorn's `--workers N`
   excludes `--reload`. User explicitly chose workers; auto-reload is
   ergonomic but workers match prod systemd shape and serve concurrent
   sister-app pagination requests without queueing. Documented the
   trade-off in AGENTS.md + memory so future sessions don't re-add
   --reload by reflex.

## What Didn't Work

1. **Initial worker count check via `ps -ef | grep uvicorn`** showed
   only 3 processes (zsh + uv + python master) immediately after
   startup. Worker spawn was still in flight. Confirmed via uvicorn
   log instead: "Started server process [pid]" appears 4 times,
   "Application startup complete" appears 4 times. Lesson: trust the
   uvicorn log over `ps` snapshots when verifying multi-worker.

2. **`Edit` tool refused to write through `CLAUDE.md`** because it's
   a symlink to `AGENTS.md`. Edited `AGENTS.md` directly; CLAUDE.md
   updates by transitivity. Confirmed via the system-reminder showing
   updated CLAUDE.md contents.

3. **`accept_candidate` default status is `under_review`**, not
   `active`. Had to explicitly pass `status='active'` to bypass the
   review queue. Worth flagging in case future bulk-accept consumers
   miss this — `accept_candidate(category='nvl', status='active')` is
   the production-ready form.

## Open Items

- **Run `refresh_substitutes.py` for johnson-vn** — embeddings exist
  for 9451 NVL now; substitute pairs against the ANN index would
  surface a richer candidate set than the trigram + same-HS sweep
  from earlier. Not auto-run this session; ~30-60s, $0 cost (uses
  pre-computed vectors).
- **BTP slice descriptions** — still NULL for the 3,337 BTP slice
  artifacts. If a UI surface ever displays description directly from
  a BTP slice's bom_edges, that path will see blank. Workaround: query
  through `lineage_root_id` to find the parent TP and pull description
  from there. Or do a secondary backfill pass matching by
  `(parent_code, child_code, qty)` if the use case emerges.
- **`accept_candidate` returns `None`** — no error on partial failure
  apart from raised exception. Script wraps in try/except and counts
  failures, but no detailed audit trail beyond `bom_audit_events`. For
  future bulk operations on larger clients, consider a per-row report
  written to a CSV.
- **Memory `project_reingest_pending.md` still lists Growatt** —
  Johnson is done end-to-end now (BCCT + BOM + catalog + embeddings).
  Growatt re-ingest mirrors the pattern; memory accurate.
