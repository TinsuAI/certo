# Session 2026-06-17 — Agency-staff user guide + prod data-parity audit (Growatt, Johnson)

Two unrelated threads: (1) authored a Vietnamese end-user guide for agency staff
and committed it on a docs branch + rendered a PDF; (2) audited whether prod data
for Growatt and Johnson matches prior ingest sessions, tracing one real divergence
to its source. No application code changed.

## What Was Done

### 1. Agency-staff user guide

- Wrote `docs/training/huong-dan-su-dung-nhan-vien-dai-ly.md` — a VN operational
  manual for agency staff (distinct from the existing
  `datahub-co-demo-training.md`, which is a presenter demo script). 15 sections in
  day-to-day order: intro/role → login & roles → per-client workspace → recommended
  ingest order → Catalog (incl. candidates, conflicts) → BQD → BCCT (preview diff)
  → Declarations (originals, ZIP, merged PDF) → Settlement (NXT, year-end stock) →
  BOM (flatten, needs-action/UoM, proposals) → Uploads & jobs → config (role-gated)
  → 5 core principles → troubleshooting table → practice exercises.
- Grounded in actual UI: read `app/templates/_client_nav.html`, `workspace.html`,
  `app/i18n.py` (exact VN nav labels), routes, and the 4 roles
  (`admin.role.*`: Dev/Admin/Manager/Staff). Prod URL `https://ttdatahub.tinsu.ai`.
- Committed as `d5ae3ab` on branch `docs/agency-staff-guide` (guide file only).
  **Not pushed.**
- Rendered PDF via `pandoc -f gfm -t html5 --pdf-engine=weasyprint` + a small
  DejaVu-Sans CSS → `/mnt/c/temp/toss/huong-dan-su-dung-datahub-nhan-vien-dai-ly.pdf`
  (9 pages, VN accents verified). Scratch only; not committed.

### 2. Prod data-parity audit

Queried prod (`ssh tinsu@100.84.189.87` → `docker compose exec -T db psql -U hub
-d data_hub`, SQL piped via stdin) and compared to session-recorded numbers / the
local-socket dev DB.

- **Growatt — exact match** to 2026-05-28 (BCCT) + 2026-05-29 (BOM wipe-reingest):
  `bcct_rows`=39,203, `customs_declaration_files`=4,038, `bom_artifacts`=823,
  `materials`=457, latest BCCT reg = 2026-05-20. Confirmed the 2026-06-14 645MB
  re-download added nothing.
- **Johnson — diverges (both explained):**
  - Prod BCCT *ahead*: 73,027 rows (2026 → 2026-06-02) vs dev 65,846 (→ 2026-05-06);
    2025 identical (37,661 rows / 1,812 decls), so no double-count. Traced the extra
    rows via `bcct_rows.upload_id → file_uploads`: two real UI uploads on 2026-06-08
    by `thanhtam@trongtin` — `BaoCaoHangChiTiet NK JS T5 new.xls` (6,439 rows) and
    `XK JS T5 new.xls` (1,477). `upload_id is null` count for the extra rows = 0
    (nothing script-injected). Conclusion: legit live agency usage; dev DB is stale.
  - Prod declarability *behind*: `materials.material_group` populated = 0/13,594 on
    prod vs 5,118 on dev. Mig 078–081 (schema) are applied on prod; the
    `backfill_johnson_material_group.py` data run is not.
- Updated two memory files with the verified findings.

## Decisions Made

- **Separate guide, not an edit of the demo doc.** The existing training md is a
  presenter script; agency staff need a task-ordered operational manual. Kept both.
- **Committed only the guide file**, on a branch, unpushed. Did not touch the
  pre-existing dirty tree (BACKLOG.md, uv.lock, untracked sessions/training/scripts)
  — confirmed not from this session.
- **Branched instead of committing to main**: push to main = prod CD redeploy, even
  for docs. Left the merge/PR decision to the user.
- **Treated prod as source of truth, dev DB as possibly stale** — verified by
  querying prod directly rather than trusting STATUS/memory, then traced the one
  surprising delta to a concrete upload before calling it benign.

## What Didn't Work

- Initial parity query assumed `exclusion_reason`/`excluded_at` live on
  `hub.materials` → "column does not exist" on both DBs. They're on
  `hub.bom_artifact_rows` (mig 078). Re-checked migrations + backfill script to
  confirm; not a divergence signal. `material_group` (on `materials`) is the right
  prod-backfill indicator.
- First guessed the Johnson prod-vs-dev BCCT gap might be a sync error / mystery
  rows; the `upload_id` join disproved that — it's real agency data.

## Open Items

- Disposition of `docs/agency-staff-guide` (merge / PR) and whether to also commit
  the untracked training assets the guide references (`input-scenarios/`,
  demo-training.md, slides, `*_final_list.png`, `generate_training_input_scenarios.py`).
- Declarability **prod** backfill still pending (was the only real Johnson gap):
  `backfill_johnson_material_group.py --exclusions-only --apply --client johnson-vn`
  against prod, then CO adoption, then flip the flag.
- Minor UX signal (not actioned): trongtin user hit repeated `mapping_pending`
  states on 2026-06-05 before a successful BCCT upload on 06-08.
