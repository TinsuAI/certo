# Project Status

**Date:** 2026-05-08 — material_identity rename + drop internal_code + configurable parser rules + drop material_identity (mig 038)

## Current State

End-to-end bundle shipped: `bcct_rows.product_identity` renamed to
`material_identity` then **dropped entirely** (mig 038). Both
`internal_code` and `material_identity` are now fully runtime-derived
from `(row_data, materials_catalog, hub.client_parser_rules)`. No
persisted derivations. Staff edit per-client regex rules via web UI
under `/clients/<id>/parser-rules`. Hardcoded Growatt regex
(`goods_name.py`) and `bcct_adapters/` registry deleted.

- **Repo HEAD**: `f75d681` on `main` — **NOT YET PUSHED**. 18 commits
  ahead of origin/main (8 from prior session 2026-05-07 + 10 from this
  session).
- **Tests**: 624 pass / 15 skip / 1 pre-existing fail
  (`test_co_columns` real-data, untouched).
- **Local DB v3 state**: schema at mig 038 applied; rules seeded for
  `growatt-vn` (5 internal_code rules + 1 material_identity_candidates
  rule). Identity-mode clients (DKE, Johnson, Do Thanh, demo) need no
  rules.
- **Demo URL**: https://ttdatahub.tinsu.ai (CI/CD picks up after push).

### Bundle commits (this session)

| Commit | Description |
|---|---|
| `046601e` | Phase 1 — engine core + ReDoS-safe pattern compiler (9 TDD tests) |
| `92581fe` | Phase 2 — mig 035 + material_identity rename + drop internal_code |
| `119927b` | Phase 3 — wire compute_internal_code helper + mig 036 seed Growatt |
| `5e5cb66` | /rev fix #1+#2 — bcct.html template + resolver display_code semantic |
| `f6ece41` | /rev fix #4 — replace bcct_adapters/ with rule engine (mig 037) |
| `ab09d83` | /rev fix #3 — CRUD endpoints + UI page + test panel single-mode |
| `ae77a74` | Deferred polish — history endpoint + PATCH UI + recent/coverage modes + sister-app docs |
| `f5eec19` | docs: STATUS.md + session summary |
| `f75d681` | Mig 038 — drop material_identity column entirely; fully runtime-derived |

### Sister-app notes posted

- `~/workspace/client/data-hub/.ai/sister-app-notes/2026-05-08-material-identity-rename-and-internal-code-drop.md`
  — for CO + BCQT. Hard-cut API breaking changes, 6-site CO consumer
  audit, before/after diffs, CI gate.
- Predecessor brief `2026-05-07-bcct-product-identity/brief.md` has an
  Amendment 2026-05-08 section appended with R4 correction.

### Behavior changes that consumers will notice

1. API param renames (hard cut, no alias): `include_product_identity`
   → `include_material_identity`. Old name returns 400.
2. Response field `internal_code` removed at every level. Read
   `material_identity.declared_internal_code` for the legacy view OR
   `material_identity.display_code` for the canonical resolved form.
3. `display_code` semantic: was `row.internal_code or customs_code`;
   now `resolved_code` (when resolved) or `customs_code` (fallback).
   For Growatt exports: was `BIENTAN.17`, now `PV01.0117500`.
4. `parser_adapter` field is now constant `"client_parser_rules"`
   (was `"growatt_bcct"` / `"identity"`). `parser_version` is `"v1"`.
5. `evidence.matched_text` now includes parens (full match span); was
   bare capture group.
6. 666 Growatt export rows + 14 import bug-shape rows now resolve
   correctly. They previously fell through F1-anchor or F1-disjunction
   bugs in the deleted hardcoded regex.
7. **(mig 038)** material_identity is no longer persisted — every read
   resolves at runtime. Rule edits propagate to next read; no backfill.
   Trade-off: bulk export (~23k rows) takes ~25-50s vs near-instant
   for cached read. Per-page reads (50 rows) ~50-100ms — negligible.
   parser_version stability across rule edits is intentionally not
   guaranteed.

## Next Steps

Priority order:

1. **Push branch to origin** — 16 commits ahead, demo CI/CD waiting.
   Run `git push origin main` when ready.
2. **CO consumer migration** — open Claude Code in
   `~/workspace/client/barry-CO-main`, point at the new sister-app
   note `.ai/sister-app-notes/2026-05-08-material-identity-rename-and-internal-code-drop.md`.
   CO updates 6 sites in `data_hub_client.py:415,426,438,538`,
   `bom_service.py:266`, `main.py:1794`. CI gate: don't deploy Data
   Hub mig 035-037 until CO consumer PR merges.
3. **BCQT consumer prep** — no current consumer; sister-app note is
   forward-looking. When BCQT adopts, same field-rename story.
4. **Wipe + ingest fresh — Growatt and Johnson** *(still pending)*.
   Memory `project_reingest_pending.md`. Now that the configurable
   rules infra works, wipe-and-reingest will produce
   correctly-resolved `internal_code` + `material_identity` from the
   first ingest (no backfill needed).
5. **Demo data parity** — after step 4, mirror to tinsu via
   pg_dump → scp.exe → restore.
6. **Optional polish (not blocking)**:
   - Add Playwright E2E for parser-rules UI (memory
     `feedback_feature_folder_with_screenshots.md` — UI features get
     committed screenshots).
   - Add `feedback_token` mechanism on rule create/update endpoints
     (brief R2 belt-and-suspenders — defer until first real misconfig).
   - Per-key cache invalidation instead of wholesale clear (current
     impl drops all cached rules on any edit; benign at current scale).
7. **BACKLOG cleanup** — review `.ai/BACKLOG.md` "Modular BOM ingest
   adapters" item 5 (now in-flight per this brief) — the BCCT-side
   work is done; BOM-side items 1-4 remain.

## Blockers

None hard. Soft (carry-over from prior session):
- 14 orphan BTPs Growatt (data quality — staff classify when TP context arrives).
- T1-T2/2026 BCCT for Growatt missing (agency hasn't supplied file).

## Notes for Next AI Session

**Read first** (in order): this STATUS, then session log
`.ai/sessions/2026-05-08-material-identity-and-parser-rules.md` (next),
then the brief at `.ai/features/2026-05-08-configurable-bcct-parsing/brief.md`.
The predecessor brief at `2026-05-07-bcct-product-identity/brief.md`
ends with an Amendment 2026-05-08 section explaining the supersession.

**Key memory** (load before reasoning about parser rules / resolver):
- `project_bom_immutable_principle.md` — never DELETE aggregate data;
  parser rules use soft-disable.
- `feedback_bom_vocab.md` — chronological brief amendments, never
  retro-edit.
- `project_bom_code_multirole.md` — multi-role canonical (PV01.0104300).
- `feedback_review_depth.md` — cap review at 2 passes.
- `feedback_drive_ops_dont_handoff.md` — execute via ssh.exe/scp.exe.

**Architecture / contracts that are LOCKED, don't relitigate**:
- 3-app split (Data Hub + BCQT + CO).
- `hub.client_parser_rules` is the single source of truth for
  client-specific regex. No more hardcoded adapters.
- ReDoS protection: `google-re2` library; backreferences rejected
  at save time.
- `material_identity.display_code = resolved_code` when resolved,
  `customs_code` otherwise.
- Identity-mode clients (DKE, Johnson, Do Thanh, demo) short-circuit:
  `internal_code = customs_code`. No rules needed for them.
- Auth: parser-rules edits gated by `can_edit_client_technical`
  (dev role only — admin not enough).

**Environment quirks**:
- Native Postgres on `/var/run/postgresql` socket, owner `vp`.
- WSL2: Windows OpenSSH (`/mnt/c/Windows/System32/OpenSSH/{ssh,scp}.exe`).
- Port 8754 pinned for dev. Server may be running from this session —
  check `ss -ltn | grep 8754`. Login: `admin@data-hub.local` / `admin123`.
- New dep: `google-re2==1.1.20251105` (pyproject.toml + uv.lock).

**Critical user feedback this session** (also in memory):
- "Pre-production, break để làm cho hợp logic" — chose hard-cut API
  break over grace-period aliases. CO consumer coordinated, not
  deferred.
- "Per-client regex phải config được trên web UI" — drove the
  configurable rules architecture vs another hardcoded patch.
- "Bundle option α (full)" — committed to one big PR vs splitting
  into mini-features.

**Sister-app coordination state**:
- CO `barry-CO-main`: 6-site audit done, sister-app note written,
  awaiting next CO session.
- BCQT `BCQT-System`: forward-looking note only; no consumer yet.
