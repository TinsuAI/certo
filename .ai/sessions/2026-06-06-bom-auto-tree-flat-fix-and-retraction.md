# Session 2026-06-06 — BOM auto-tree-flat fix + honest signals + self-service retraction

Triggered by a user report: a technical BOM uploaded on prod (`MPL0100-39.XLSX`,
johnson-vn) was stored but never converted to a flat BOM. Diagnosed → fixed →
hardened UX → added self-service cleanup → remediated prod data → verified live.

All four code commits shipped to prod (`ttdatahub.tinsu.ai`, Docker):
`90ba345` → `0bd85d2` → `1105993` → `7886efa` (+ `be0da06` STATUS doc).

## What Was Done

### 1. Root cause (evidenced on prod, not guessed)
`profile=auto` (default "Tự động phát hiện") ran `parse_with_fallback` (flat
rows) for **every** adapter and stored the result via `create_artifact` →
`source_bom_kind=manual_flat`, `flatten_status=not_applicable`. Single-rooted
explosion trees (`sap_indented_walk`, `multi_sheet_per_root`,
`emits_intermediate_btp_versions=False`) therefore landed FLAT: no `raw_graph`,
no edges, so the `materialize_shapes` post-ingest hook (acts only on **published
`technical_raw`** artifacts) no-op'd → no shallow/full_flat — yet
`parse_status='done'`. Prod evidence: `MPL0100-39` had `context.profile=
sap_indented_walk`, 8-level `_node_path`, 244 rows, 0 `bom_edges`. Census showed
the bug signature `manual_flat | sap_indented_walk | 2` (vs 3031 healthy
`technical_raw` Johnson BOMs).

### 2. Logic fix (`90ba345`)
`app/routes/bom.py` auto branch: when the detected adapter is a tree adapter
(`emits_intermediate_btp_versions=False`) **and** a raw-edge parser matches,
set `profile='technical_raw'` and fall through to the raw-edges path
(`parse_raw_edges_with_fallback` → `create_raw_artifact` → materialize). Falls
back to flat path if no raw-edge parser matches (no regression). Regression test
in `tests/test_bom_flexible_flow.py::test_auto_profile_tree_adapter_lands_as_raw_graph`.

### 3. UX hardening (`0bd85d2`)
- **Preview destination banner** (`bom_preview.html`): states whether confirming
  will auto-derive flat shapes (technical_raw) or store as-provided flat; red
  warning when a multi-level `_node_path` file is about to land flat.
- **Honest post-ingest toast** (`bom.html`): confirm redirect carries
  `kind` + `flat`; list toast distinguishes technical-OK / technical-no-flat
  WARNING / flat-stored — instead of a flat "done". The warning is the exact
  signal the original bug swallowed.

### 4. Self-service retraction (`7886efa`)
Closes the gap that forced dev SQL to clean bad data:
- `tombstone_bom_version()` in `app/stores/bom.py` + route
  `POST /clients/{id}/bom/artifact/{aid}/tombstone` + danger-zone form on the
  artifact detail. Reason required; writes `version.tombstoned` audit;
  **cascades to derived shapes** (resolves the version root — a shape's
  raw_graph parent, else the artifact — and tombstones root + children). Soft
  only (never DELETE). Confirm dialog warns sister apps consume the version.
- `POST /clients/{id}/uploads/{uid}/delete` + "Xoá" button in the uploads list,
  restricted to `error`/`rejected` rows (a `done` row backs an artifact via
  `source_upload_id`); also unlinks the blob best-effort.
- Tests: `tests/test_bom_artifact_tombstone.py` (5 cases).

### 5. Prod data remediation
Tombstoned the 2 stuck artifacts (`MPL0100-39`, `MFW0537-39`), re-ingested via
the fixed flow (in-container TestClient reading the existing blobs).
`MPL0100-39` now has raw + shallow + full_flat (published). `MFW0537-39` already
had good shapes from 2026-05-13/05-25 — the 2026-06-04 re-upload was a
byte-identical stray `manual_flat`; the re-ingest duplicates were tombstoned.

### 6. Live prod verification (httpx → 127.0.0.1:8754 inside the container)
- Tombstone: empty reason → 400; tombstone raw → 303 `?tombstoned=2`, cascade
  (active→0), 2 audit rows, reason stored; real `MPL0100-39` untouched. ALL PASS.
- Upload delete: error → 303 + DB row **and** blob gone; rejected → gone;
  done → 400 (row+blob kept); unknown → 404. ALL PASS.
Throwaway clients + scoped sessions, cleaned up each time.

### Screenshots
`.ai/features/2026-06-05-bom-auto-tree-flat-fix/screenshots/` (9, via
`scripts/screenshot_bom_flow_signals.py`): upload form, technical/flat/multi-level
previews, 3 toast variants, artifact danger zone, uploads delete.

## Decisions Made

- **Tree vs flat = adapter nature, not user's profile pick.** Routing keys on
  `emits_intermediate_btp_versions`, not on whether the user happened to pick
  `technical_raw`. Tree adapters already had a raw-edge parser counterpart
  (`parse_raw_edges_with_fallback`); the bug was auto never using it.
- **Cascade on the version root, not single artifact.** A wrong technical BOM is
  raw + shallow + full_flat; tombstoning one would orphan the rest. The action
  resolves the root and tombstones root + children so one click is complete —
  this absorbed the separate "thu hồi cả cụm" option I'd proposed.
- **Soft tombstone, not DELETE** — BOM immutable principle (`project_bom_immutable_principle`).
  Reused `bom_audit_events` (`version.tombstoned`) rather than a new table.
- **Upload delete refuses `done`** — those back artifacts via `source_upload_id`.
- **Verified against the live uvicorn**, not just in-process TestClient, because
  the ask was "works on prod".

## What Didn't Work / Gotchas

- **`create_raw_artifact` dedup keys on `actor`.** Re-ingesting `MFW0537-39`
  (which already had an `erp_pipeline` raw) as `agency_staff` produced a
  byte-identical-but-duplicate raw + shapes instead of deduping. Had to tombstone
  the dupes. If a future bulk re-ingest crosses actors, expect duplicates.
- **In-container `python /tmp/x.py` fails `import app`** — `sys.path[0]` is
  `/tmp`, not `/app`. Run with `-e PYTHONPATH=/app --workdir /app`.
- The multi-level-flat preview warning rarely fires now (auto reroutes tree
  files to raw); it's a defensive net for manually-chosen flat profiles. Its
  screenshot was produced via a synthetic pending insert.

## Open Items

- **Carried from prior session (still open):** LLM is on a TEMPORARY OpenRouter
  key (borrowed from `growatt-item-master/.env`); restore sgnai
  `codex-lb-demo.sgnai.dev` when its Cloudflare tunnel is back, or provision a
  dedicated key. Old config in `data/files/.prod_llm_settings_backup.tsv`.
- Possible follow-on: make `create_raw_artifact` dedup actor-agnostic (or warn on
  cross-actor identical-edge collisions) to prevent re-ingest duplicates.
- CO/BCQT consumers: a tombstoned version disappears from their read API
  (`tombstoned_at is null`). No consumer-facing notification exists — fine for
  "this was wrong" but worth noting if a consumed version is ever retracted.
