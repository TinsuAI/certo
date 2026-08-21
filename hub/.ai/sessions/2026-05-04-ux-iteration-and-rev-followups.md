# Session: 2026-05-04 EOD — UX iteration + /rev follow-ups + manual-test fixtures

Continuation of `2026-05-04-bcct-overhaul-and-llm.md`. After the 4-stage
build (A+B / D / C1 / C2) shipped + post-/rev critical fixes landed, I
generated manual-test fixtures and the user drove every stage by hand
through the running web UI. Each test surfaced 1-3 small bugs or rough
UX edges. Total ~10 commits, all fixed, server live at end.

## What was done

### Manual-test fixture corpus (commit `18cc9ce`)

`data/manual_test/`:
- `01_stage_AB_full_co_bcct.xlsx` — 3 export rows with all 12 CO headers
  populated (verifies typed columns + year derivation).
- `02_stage_D_chinese_headers.xlsx` — 2 rows with Chinese headers (`报关单号
  / 项次 / 申报类型 / 登记日期 / 海关编码 / 货物名称 / 数量 / 单位 / 总价值 /
  货币`). Forces rigid parser to fail → triggers LLM fallback (or "LLM not
  configured" surface).
- `03a_stage_C1_baseline.xlsx` — 3 rows for fresh seed (MAN_C1_A/B/C).
- `03b_stage_C1_changed.xlsx` — same 2 TKs (1 DIFF, 1 NOOP) + 1 NEW;
  MAN_C1_C missing → ORPHAN candidate.
- `_cleanup.sql` — wipe MAN_* rows + history + pending + parser_mappings
  + the file_uploads audit rows.
- `README.md` — file-by-file walk: each file → URL → expected outcome
  (toast text, redirect target, DB state, audit log content).

### UX issues surfaced + fixed (commits `c77da85` → `aafa0d5`)

1. **Silent upload success** (commit `c77da85`).
   User uploaded `01_stage_AB`, hub redirected to `/bcct` with no toast.
   Fix: route returns
   `?ingested=N&new=X&updated=Y&deleted=Z&noop=N&skipped=N` query string;
   list view template reads `upload_summary` and renders green banner
   `✓ Đã ingest N dòng (X mới · Y cập nhật · Z đã xóa · ... )`.

2. **LLM error sanitization v2** (commit `c77da85`).
   `_request_llm_mapping` previously echoed raw SDK exception to the
   browser, including a confusing "Detail withheld to avoid leaking
   credentials" message. The real cause for the user was that they had
   pasted their email into the `Model` field — not a credentials issue.
   Split into 3 distinct paths:
   - LLM not configured → `File không khớp parser tự động: <rigid err>.
     Bật LLM Smart Parser ở /admin/settings/technical hoặc upload file
     đúng format BCCT.`
   - LLM configured but call failed → `Parser cứng từ chối + LLM gọi
     không thành công ({type_name}). Kiểm tra cấu hình tại
     /admin/settings/technical hoặc xem chi tiết tại
     /clients/{id}/uploads.` (Type name shown is safe; full error
     server-side via `parse_error` column.)
   - file_signature is None (workbook empty) → distinct message.

3. **Auto-fetch LLM model list** (commit `fd3d30e`).
   User shouldn't have to type model names. Added
   `app/llm.py:list_models(cfg)` calling `client.models.list()`. Settings
   route accepts `?fetch_models=1`; populates a `<select>` dropdown
   from the result; auto-saves first model when none was set. Save
   button now redirects with both `?saved=1&fetch_models=1` so the
   normal Save flow auto-populates the dropdown.

4. **"json" lowercase in prompt** (commit `6221706`).
   User's vLLM/LM-Studio endpoint returned 502 with: `Response input
   messages must contain the word 'json' in some form to use
   text.format of type json_object`. OpenAI's strict-output rule.
   Our system prompt only had `JSON` (uppercase) inside an escaped
   example. Fix: rewrote prompt with `json` lowercase 4 times in plain
   prose; user message prefixed with `json input follows. Reply with
   json only.`

5. **Sample column shows wrong data per row** (commit `6d6ef6b`).
   Inner `for row in samples` loop overrode `loop.index0`, so every
   header row read the same cells (`samples[0][0] · samples[1][1] · …`).
   Fix: capture outer loop's column index as `col_idx` before entering
   inner loop; use `row[col_idx]`.

6. **Logical-field input → dropdown** (commit `58a06f1`).
   Free-text was error-prone. Now `<select>` populated from
   `_TARGET_FIELDS_BY_MODULE['bcct']` (canonical 27 fields) + `(skip)`
   option. Custom LLM-proposed fields still round-trip via a separate
   `(custom)` option appended to the list.

7. **Reject path on parse-mapping** (commit `58a06f1`).
   Previously only Lưu (apply all) or Hủy (navigate away). Now 3
   explicit choices via `formaction=`:
   - Lưu — accept + cache + ingest (primary)
   - Reject — file isn't BCCT; new POST endpoint marks
     `parse_status='rejected'`, doesn't cache mapping (mapping was
     speculative; same shape on a future upload may be valid)
   - Quay lại sau — navigate; file stays in `proposed_mapping` for
     later review

8. **`/uploads` link to propose UI** (commit `cc7ac81`).
   "Quay lại sau" left users stranded — `/uploads` listed the
   `proposed_mapping` file but didn't link back to the propose page.
   Added `review mapping →` link beside the filename when
   `parse_status='proposed_mapping'` AND module is `bcct`. Distinct
   badges for the two new statuses (`proposed_mapping` = info-blue,
   `rejected` = warn-yellow).

9. **History link from BCCT row table** (commit `5c158f5`).
   User asked: "after running C1, how do I see what changed?" History
   page existed but only via direct URL. Added new `Lịch sử` column
   with `✏ N` badge linking to history page when N>0; `—` link
   (still clickable) otherwise. Backed by LEFT JOIN aggregate sub-query
   indexed via `idx_bcct_row_history_pk`.

10. **History page: user_id → email + display_name** (commit `aafa0d5`).
    `Ai` column showed raw `u_31151f0497094109` — opaque to humans. LEFT
    JOIN `hub.users`; render bold `display_name` + email; sentinel
    actors (`system`, `ops:script`) shown as warn badge with tooltip.

### /rev minor follow-ups (commit `2e8cd05`)

- `_lookup_cached_mapping` no longer increments `use_count` on read.
  New `_record_mapping_use(client_id, file_signature)` called only
  AFTER cached mapping has actually parsed successfully. Counter no
  longer overcounts when cached mapping fails and route falls back to
  rigid/LLM.
- `parse_mapping_confirm` now catches `FileNotFoundError` when reading
  `stored_path`; marks upload errored + raises 410 Gone with
  user-readable message instead of 500-ing.
- Migration numbering gap (010 → 012, no 011) intentionally NOT fixed.
  Renaming applied migrations would require updating
  `hub.schema_migrations` server-side; risky cross-environment. Left
  as cosmetic doc note in BACKLOG.

### Backlog file created (commit `89478f9`)

New `.ai/BACKLOG.md` separates "future ideas not yet planned" from
STATUS (current state) + DECISIONS (past choices). User-flagged 3
ideas added:
- Pre-commit upload preview at all stages
- Catalog multi-source provenance (DS NVL/SP ĐK HQ vs auto-derived from
  BCCT vs user-uploaded; surface "on declaration but not registered"
  diff as audit signal)
- BCCT tab staleness metadata (last upload + most recent declaration
  date as two signals)

Plus cross-cut /rev open items + epic open items rolled forward.

## Decisions made

- **Toast via query string, not session flash.** Simpler than introducing
  a flash mechanism; URL-shareable; toast content visible in audit logs.
- **Auto-default first model on `?fetch_models=1`** to make the "paste
  URL+key, click Save, done" flow work without further config — but only
  when `llm_model` is empty (don't override an explicit user choice).
- **Reject doesn't cache mapping.** The mapping was LLM-speculative; if
  the user marks the file as misrouted, the same shape on a *future*
  upload to the same client may be valid. Don't poison the cache.
- **History page: LEFT JOIN on hub.users, not client-side resolution.**
  Single SQL round trip; sentinels (`system`, `ops:script`) intentionally
  miss the join and fall through to a distinct render.
- **Migration renumber deferred.** Renaming would diverge `schema_migrations`
  rows across environments; not worth the risk for cosmetic numbering.

## What didn't work / Surprises

- **First Playwright screenshot attempt failed silently** (no output, no
  files written). Re-run with explicit `Path.mkdir(parents=True,
  exist_ok=True)` + size assertion fixed it. Always log file-size after
  screenshot capture.
- **Server restart took 4-6s** consistently because the migration runner
  walks all 13 SQL files at startup even when none are pending. Not a
  blocker but worth noting — `apply_migrations` could short-circuit when
  `schema_migrations` count == files count.
- **`set_config('app.user_id', %s, false)`** vs `SET app.user_id = $1`
  — the latter doesn't accept parameters (Postgres SET syntax doesn't
  parameterize). `set_config()` does. Found the hard way.
- **User pasted email into Model field** in /admin/settings/technical
  during their first test. The field had a placeholder but no
  validation. Fix landed via auto-fetch + dropdown which removes the
  text-entry trap entirely.

## How to resume

```bash
cd ~/workspace/client/data-hub
uv run uvicorn app.main:app --port 8754 --host 127.0.0.1 --reload
# Login admin@data-hub.local / admin123 (role=dev)

# Tests
uv run pytest -q                                          # 109 passed
DATA_HUB_REAL_DATA_DIR=/tmp/dh_real_data uv run pytest -q # 109+6 real-data passed

# Manual test fixtures + walkthrough
cat data/manual_test/README.md
psql -d data_hub -f data/manual_test/_cleanup.sql   # reset between runs

# Server lives at http://127.0.0.1:8754; admin password 'admin123'
# (NOT a production install; rotate before any real deploy)
```

## Open items (rolled forward to BACKLOG.md / STATUS.md)

- Pre-commit upload preview for catalog/bqd/bom (BCCT has it via
  parse-mapping; extend pattern).
- Catalog multi-source provenance.
- BCCT tab staleness metadata.
- Apply confirm-gate pattern to catalog/bqd/bom uploads.
- Manual mapping UI when LLM disabled.
- Migration numbering 010→012 cosmetic gap.
- CSRF protection (pre-existing).
- `set_config(...)` LOCAL when pooling lands.
