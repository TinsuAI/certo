# Project Status

**Date:** 2026-05-08 — full BCCT identity + parser-rules + payload-promotion bundle

## Current State

End-to-end bundle of 7 migrations shipped this session, plus
multiple architectural pivots driven by user feedback during the
session:

1. mig 035 — material_identity rename + drop internal_code column.
2. mig 036 — seed Growatt parser rules (internal_code).
3. mig 037 — seed Growatt material_identity_candidates rule.
4. mig 038 — drop material_identity column too (runtime-derived).
5. mig 039 — promote payload Tier 1: rename `currency`→`currency_nt`
   + add 4 typed columns (`total_value_nt`, `unit_price_nt`,
   `total_tax`, `unloading_location`). Fixes currency-tag bug.
6. mig 040 — promote payload Tier 2: 4 more typed columns
   (`contract_no`, `contract_date`, `internal_mgmt_no`, `package_marks`).
7. mig 041 — prune 38 typed-already keys from payload jsonb.

Plus mid-session resolver tweaks:
- Stage swap (Stage 2 paren-extract before Stage 1 customs_code).
- display_code semantic = resolved_code (not internal_code).
- Per-row inspect view at `/clients/<id>/bcct/history/<txn>/<line>`
  showing all 40 typed columns + computed material_identity jsonb.

Architectural principle: **pure-derivation values are not cached**.
internal_code (regex over goods_name) and material_identity (5-stage
resolver) both runtime-only. Custom parser rules live in
`hub.client_parser_rules`, edited by staff via web UI at
`/clients/<id>/parser-rules` (dev role).

- **Repo HEAD**: `a971919` on `main` — **PUSHED** + deployed to
  demo. 26 commits this session (origin already up-to-date).
- **Tests**: 626 pass / 15 skip / **0 fail**. The pre-existing
  `test_co_columns` failure addressed by mig 041 cleanup.
- **Demo server (tinsu)**: HEAD = `a971919`, healthz=200,
  schema_migrations 035-041 all applied, 6 parser_rules seeded for
  growatt-vn. CI workflow technically marked "failed" but only the
  best-effort LLM smoke step (401 from upstream service); deploy +
  test + API smoke all green.
- **Local DB v3 state**: schema at mig 041 applied; rules seeded for
  `growatt-vn` (5 internal_code + 1 material_identity_candidates).
  All payload promotions backfilled (75,304 rows). Identity-mode
  clients (DKE, Johnson, Do Thanh, demo) need no rules.
- **`hub.bcct_rows`**: 40 typed columns (was 32). Payload jsonb
  contains 13 keys (sparse tax-detail + Ghi chú + STT audit).
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
| `e6acfa0` | docs: STATUS + sister-app note + brief amendment for mig 038 |
| `a41f84e` | Resolver Stage 2 (paren-extract) wins over Stage 1 + UI marker for computed columns |
| `6a31fc9` | Per-row inspect view (Trạng thái hiện tại) + UI markers for computed fields |
| `932ea10` | Mig 039 — promote payload Tier 1 + currency-tag bug fix |
| `db0f1ef` | Mig 040 — promote payload Tier 2 (contract + internal_mgmt + package_marks) |
| `37b8046` | Mig 041 — prune typed-already keys from payload jsonb |
| `d491145` | docs: handoff — sister-app note + STATUS + session summary |
| `a971919` | fix(ci): mig 036/037 idempotent + safe on fresh DB |

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
8. **(resolver swap, post-mig 038)** Stage 2 (paren-extract) now
   evaluates BEFORE Stage 1 (customs_code in materials). For
   Growatt-style exports where customs_code='BIENTAN.20' AND
   goods_name contains '(PV02.0228801)', resolved_code now
   = `PV02.0228801` (was: `BIENTAN.20`). Identity-mode clients
   unaffected (no rules → fall through to Stage 1).
9. **(mig 039)** `currency` field renamed → `currency_nt` (FX-domain
   semantic). 4 new typed columns: `total_value_nt`, `unit_price_nt`,
   `total_tax`, `unloading_location`. Fixes currency-tag mismatch
   for ~70k rows where USD-tagged values were actually VND-magnitude.
   FX-domain (transaction currency) and VND-domain (taxable) now
   represented separately.
10. **(mig 040)** 4 more typed columns added: `contract_no`,
    `contract_date`, `internal_mgmt_no`, `package_marks`.
11. **(mig 041)** payload jsonb pruned: 38 typed-already keys
    removed. Payload now contains only Tier 3 (sparse tax detail,
    free-text, audit fields). Consumers using
    `payload->>'Tên doanh nghiệp'` etc. must switch to typed
    columns (`exporter_name`, etc.).
12. **(UI)** BCCT row history page now shows full "Trạng thái hiện
    tại" section with all 40 typed columns + computed
    material_identity expandable. Computed fields marked with `ƒ`.

## Next Steps

Priority order:

1. **CO consumer migration** — sister-app note
   `.ai/sister-app-notes/2026-05-08-material-identity-rename-and-internal-code-drop.md`
   has full migration steps including all migs 035-041 changes.
   CO updates needed:
   - 6 read sites in `data_hub_client.py:415,426,438,538`,
     `bom_service.py:266`, `main.py:1794` — swap `internal_code`
     reads to `material_identity.declared_internal_code` /
     `display_code`.
   - SQL refs to `currency` column → `currency_nt`.
   - SQL refs to `payload->>'X'` for promoted keys (Tên doanh
     nghiệp etc.) → swap to typed columns (`exporter_name` etc.).
   - Param renames `include_product_identity` → `include_material_identity`.
2. **BCQT consumer prep** — no current consumer; sister-app note is
   forward-looking. Same field-rename story when BCQT adopts.
3. **Wipe + ingest fresh — Growatt and Johnson** (memory
   `project_reingest_pending.md`). Triple-unblocked now: rule
   engine works, FX/VND domains split, payload pruned. Re-ingest
   produces clean rows from scratch — no backfill needed.
4. **BACKLOG cleanup** — 3 scripts SQL-degraded after payload prune
   need Python-side rewrites. See `.ai/BACKLOG.md` "Scripts that
   lost SQL `material_identity` access" entry:
   - `scripts/settlement_resolver.py::_load_bcct_universe`
   - `scripts/detect_dual_source_btps.py`
   - `app/agent/tools.py::_query_bcct`
5. **Demo data parity** — after step 3 (wipe + ingest), mirror to
   tinsu via pg_dump → scp.exe → restore. Dev DB and demo are
   currently both at mig 041 schema, but data still has 2026-Q1
   pre-mig data with old derivations cached.
6. **Optional polish (not blocking)**:
   - Add Playwright E2E for parser-rules UI (memory
     `feedback_feature_folder_with_screenshots.md`).
   - Per-key cache invalidation in `client_parser_rules` engine
     (current impl drops wholesale; benign at current scale).
   - preview_token belt-and-suspenders on rule writes.
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
