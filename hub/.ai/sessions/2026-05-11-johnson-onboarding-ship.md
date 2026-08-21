# Session 2026-05-11 — Johnson onboarding ship + BTP dedup fix + UI ingest hooks

## What Was Done

End-to-end ship of the Johnson onboarding scope (originally 6 items in
the kick-off brief), plus a follow-up bug hunt that found + fixed BTP
artifact bloat and a broken hook resolution path for raw-edge parsers.

### Phase 0 — Johnson real BCCT ingest

- `scripts/ingest_johnson_real.py` — wraps existing `_insert_bcct` with
  null-`registration_date` filter (gen-col `year` is NOT NULL).
- Wiped Johnson seed data (cascade DELETE from `hub.clients`), recreated
  via `setup_clients_for_reingest.py`.
- Ingested NK 60,173 + XK 5,673 = 65,846 rows in 37s.

### Feature 6 — TKX/TKN file management (mig 059)

- `customs_declaration_files` table; per-declaration XLS/PDF metadata
  + FileBackend storage. Linked to BCCT via `(client_id, declaration_no,
  direction)` without hard FK (legacy archive imports tolerated).
- Filename parser `<prefix>_<digits>.<ext>` + XLS content cross-validate
  via "most-frequent + longest" 10-14-digit number rule (12-digit
  declaration_no beats 10-digit tax code).
- xlrd for .xls; openpyxl fallback for .xlsx; filename-only for .pdf.
- Web pages: index + detail + upload + bulk import script (TKN/TKX
  folders → 3,221 files via sha256 dedup).
- JSON API for sister-app C/O.
- "Tờ khai" tab added to client nav.

### Feature 3 — BCCT-derived catalog analysis

- `bootstrap_catalog_from_bcct.py` patched (mig 042 schema rename:
  `customs_code` → `material_code`; `internal_code` dropped). Ran for
  Johnson: 9,310 materials inserted (8,660 nvl + 650 tp).
- `app/stores/catalog_bcct_analysis.py` — per-material BCCT aggregation:
  row count, declarations, direction breakdown, "đại diện" picker
  (most-frequent attribute tuple, recency tie-break, NK preferred),
  per-field drift detection.
- Severity tiers: unit=critical, hs_code=warn, goods_name+origin=info.
- Common-prefix/suffix diff highlight: when ≥2 distinct values share long
  affixes, render with shared parts grayed and divergent middle bolded
  (catches near-identical descriptions that look identical when
  truncated). User caught this — original truncate(40) was too lossy.
- Catalog detail panel "Phân tích từ BCCT" with drift table + value-chips.

### Feature 4 — NVL substitute hybrid (mig 060 + 061)

- `material_substitutes` directed-edge table with 7 sources:
  client_confirmed, same_customs_diff_internal, same_hs, prefix_rule,
  trigram, embedding, manual_user.
- Per-client toggles in `clients.substitute_rules` JSONB. Johnson defaults
  `p2=false` (identity-mode makes it noise).
- `pg_trgm` GIN index on `material_code`; `pgvector` HNSW index on
  `description_embedding`.
- Same-HS caps at HS group ≤30 to avoid noise blow-up (Johnson HS
  73269099 has 4,020 mats = 16M pairs without cap).
- Combined-score formula picks max across sources. client_confirmed=1.0
  fixed; embedding=0.30+0.70×cosine; trigram=0.20+0.50×trgm.
- Catalog detail panel "Vật tư thay thế" with reason badges, score,
  reject/manual-add, rejected-list collapsible.
- JSON API for sister-app C/O substitute lookup.
- Refresh `refresh_candidates` produced for Johnson:
  same_hs=4,990, trigram=103,215, embedding=118,314.

### F4f — Embedding pipeline (mig 061 + pgvector install)

- `pgvector` 0.6.0 installed via sudo apt + `CREATE EXTENSION` as
  postgres superuser (vp role isn't superuser).
- `app/embedding.py`: 2-tier config (global `app_settings` keys
  `embedding.*` + per-client `clients.embedding_config` JSONB). Multi-field
  text template `{name}. HS={hs_code}. UoM={unit}. Origin={country_origin}.`.
  OpenRouterClient (urllib, no extra dep). text+model sha256 hash for
  dirty detection.
- `scripts/embed_materials.py` — walks dirty rows, batches via OpenRouter
  (`text-embedding-3-small`, dim=1536), writes vector + tracking columns.
  Dry-run default; `--force` clears hash + re-embeds all.
- **Auto-enable rule:** flips `clients.substitute_rules.p5_embedding=true`
  on first successful embed. UX: if user populated vectors, they
  obviously want them used.
- Substitute refresh extended with embedding source via lateral cosine
  ANN search (HNSW `<=>` operator), top-10 per material.
- Admin/settings/embedding UI — config form + Test connection + (later
  removed) per-client re-embed table moved to per-client catalog page.
- Johnson live run: 11,920 embedded in 350s (77 items/s, ~$0.018 cost).

### Background job framework (mig 062)

- `hub.background_jobs` table tracks long-running ops kicked off from
  the web UI. Wrapper `scripts/_job_runner.py` updates pending → running
  → done|error and captures stdout to log.
- Per-client AI panel on `/clients/{cid}/catalog` (top of page) with
  stats (Đã phân tích / Cần phân tích lại / Số gợi ý / Lần phân tích
  gần nhất) + 3 buttons: Cập nhật phân tích AI / Làm lại từ đầu /
  Tìm lại gợi ý vật tư.
- Job detail page `/jobs/{id}` with meta-refresh while not terminal.
  Job list `/clients/{cid}/jobs`.
- ETA estimates scale by count (calibrated to 33 items/s embed,
  75 items/s substitute refresh from Johnson runs).

### Phase 4 — Johnson BOM ingest + 4-shape (existing CLI script)

- 106 SAP-exploded BOM XLSX ingested via `ingest_technical_raw_batch.py`
  (no code changes needed, just a CLI run).
- 27,848 raw edges across 106 TP raw_graphs.
- `scripts/fixup_johnson_btp_sx_after_bom.py` — post-BOM catalog fixup:
  insert 2,615 missing intermediate parent codes as `btp_sx`
  (source='bom_observed'), reclassify 416 nvl→btp_sx (codes used as
  parents in BOM = sub-assemblies). Memory `project_reingest_pending`
  noted Johnson "BTP_SX không có NP, không XK" — BOM ingest reveals them.

### BTP dedup bug + UI hook resolution fix (post-ship)

User noticed 8,837 BTP raw_graph artifacts felt like too many, asked 4
sharp questions. Investigation found 2 separate bugs:

**Bug 1: BTP artifact bloat (8,837 → 3,337, 2.6× reduction).**

`scripts/derive_btp_shallows._subtree_edges()` was preserving
TP-context fields on BTP slice edges:
- `level` = depth in original TP tree
- `node_path` = path from TP root
- `source_row_no`, `sheet_name` = TP XLSX metadata

These all got hashed by `normalized_edges_hash`, so identical BTP slices
under different parent TPs produced different hashes → no dedup.

ALSO: `create_raw_artifact` dedup keys on `parent_artifact_id`. The script
was passing `parent_artifact_id=artifact_id` (the source TP), which
fragmented the dedup lookup per-TP.

Fix:
1. `_subtree_edges` nulls out the context fields (relative depth +
   path-from-BTP can be re-derived on display from parent_code →
   child_code chain).
2. `parent_artifact_id=None` on derived BTP slices. Source TP recorded
   in `context.first_seen_via` (informal trace) + computable on demand
   from `bom_edges`.

Backfill: hard-DELETE the 8,837 bloat artifacts (override
`project_bom_immutable_principle` per user; data was draft + derived +
noise from a script bug). Re-ran derive → 3,337 deduped artifacts.

**Bug 2: UI ingest hooks didn't fire for raw-edge parsers.**

`parse_raw_edges_with_fallback` (in `app/parsers/bom_edges.py`) returns
its own adapter-name strings (`sap_indented_raw`,
`growatt_factory_technical`) which were NEVER registered in the main
`bom_adapters._REGISTRY`. Two parallel adapter naming systems.

When upload-confirm called `run_post_ingest_hooks(adapter_name=
"sap_indented_raw", ...)`, `resolve()` returned None → entire hook
chain silently no-op'd. UI uploads with `profile=technical_raw`
produced only the TP raw_graph — no BTP slicing, no shape materialization.

Fix: `_LEGACY_ALIASES` entries pointing at closest registered adapters:
- `sap_indented_raw` → `sap_indented_walk`
- `growatt_factory_technical` → `multi_sheet_per_root`

Both target adapters declare `[derive_btp_shallows, materialize_shapes]`
so the same post-ingest behaviour applies regardless of which path
the upload took.

Verified end-to-end via Playwright smoke: deleted MFW0513-39 from DB,
uploaded XLSX via UI, confirmed → 3 artifacts created (raw_graph +
shallow + full_flat, all published; 23 BTPs deduped against existing).

### UX cleanup post-bug-fix

- Added `materialize_shapes` hook (registered for all flat adapters too,
  not just SAP). Now any UI BOM upload gives staff full 3-shape coverage
  immediately on confirm (no manual CLI run needed).
- Per-client AI panel ETA estimates scale by `materials_dirty` /
  `materials_total` count (was hardcoded "5 phút cho 12K").
- Settings page cleaned: per-client re-embed table removed (moved to
  catalog page). Settings page now only has global config form.

## Decisions Made

1. **Catalog source-of-truth: BCCT-derived default + XLSX override.**
   When a row exists from XLSX (`source='client_declared'`), it shadows
   the BCCT-derived view entry. Most clients won't have XLSX — they get
   pure BCCT-inferred catalog.

2. **TKX/TKN file linkage via `(client_id, declaration_no, direction)`,
   no hard FK to `bcct_rows`.** Allows uploading legacy archives even
   for declarations not yet ingested. UI shows "Thiếu TK" / "Có TK"
   badge per BCCT row.

3. **Substitute scoring: max across sources, not weighted average.**
   Sources are independent signals — taking max preserves each source's
   strongest claim. UI displays all sources that flagged the pair.

4. **Embedding text composition: multi-field, not just `name`.**
   `{name}. HS={hs_code}. UoM={unit}. Origin={country_origin}.` —
   includes categorical signals (HS/UoM/origin) that disambiguate
   identically-named goods. material_code excluded — handled by trigram
   layer separately.

5. **Auto-flip p5_embedding on first successful embed.** UX
   discoverability — user shouldn't need to know about a hidden DB
   flag. Implemented in `embed_materials.py` end-of-run.

6. **Hard-DELETE the 8,837 BTP bloat (not tombstone).** Override
   `project_bom_immutable_principle` per user direction. Acceptable
   because data was: derived (not asserted), draft (never published),
   noise from a script bug (no semantic value).

7. **VNACCS 50-line cap is real, not export truncation.** Distribution
   cliff at exactly 50 lines/declaration is normal Vietnamese customs
   system behaviour. Don't email agency. Memory
   `feedback_cliff_not_truncation` saved as recurring lesson.

8. **`parent_artifact_id=None` on derived BTP slices.** Otherwise dedup
   query fragments per-parent-TP. Source TP traceability via
   `context.first_seen_via` jsonb field; "which TPs reference this BTP"
   computable on demand from `bom_edges`.

9. **Background jobs over async/streaming.** Long-running ops (5-min
   embed) need async, but FastAPI BackgroundTasks tied to request
   lifecycle. Detached subprocess + DB-row status tracking + meta-refresh
   poll on web page is operationally simpler than SSE/websocket.

## What Didn't Work

- **Initial truncation hypothesis for Johnson NK 50-line cap.** Saw
  distribution cliff (776 declarations exactly at 50, zero above), claimed
  it was BCCT export truncation. User asked me to investigate myself —
  cross-checking against per-TK XLS files in `TKN/` folder showed every
  per-TK file ALSO capped at 50 goods → VNACCS system limit, not
  truncation. Wasted ~30 minutes on email-drafting + agency follow-up
  cycle. Lesson saved as memory `feedback_cliff_not_truncation`.

- **First UI upload smoke** (post-mig + hook wire) showed the hook chain
  no-op'd. Symptom: 1 new artifact, 0 BTPs, 0 shapes. Diagnosed as
  adapter-name mismatch between `parse_raw_edges_with_fallback` and the
  main `bom_adapters` registry. Required adding `_LEGACY_ALIASES` entries.

- **First attempt to fix BTP bloat** by re-rooting only edge fields kept
  the bloat. `create_raw_artifact` dedup was ALSO keying on
  `parent_artifact_id`, so even with identical edges, different parent
  TPs produced separate artifacts. Required setting `parent_artifact_id=None`
  on derived slices.

- **Pure-name embedding text** (just `{name}` template) — discussed
  briefly but not used. User's data has too many identically-named goods
  with different HS/origin to disambiguate by name alone. Settled on
  multi-field default.

- **Direct row count `count_distinct_unit_etc` for drift detection** —
  worked but produced bad UX when 2 long descriptions shared a 91-char
  prefix and differed at the end (truncate(40) made them look identical).
  User flagged it; switched to common-affix detection + bold-the-diff
  rendering.

## Open Items

- **Johnson agency hasn't supplied 4 NK + 1 XK TK files.** UI shows
  badge "Thiếu TK" — acceptable per user.
- **A.4.2 backlog: substitute XLSX bulk upload (P1 client_confirmed).**
  Manual-add UI covers single-pair use. ~0.5 day.
- **A.4.3 backlog: smarter `goods_name` similarity** (insignificant-diff
  folding via pg_trgm + embedding). Now unblocked since both are live.
- **CO sister-app integration** for the substitute API. Need
  `.ai/sister-app-notes/` doc.
- **Nightly cron for embed + refresh.** Currently only manual trigger.
- **Push 5 commits to `origin`.** Working tree clean.
- **Memory `feedback_verify_status_vs_code`** says STATUS lags HEAD; today's
  STATUS reflects HEAD as of these 5 commits.
