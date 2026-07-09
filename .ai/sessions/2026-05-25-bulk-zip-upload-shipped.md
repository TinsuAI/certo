# Session — Bulk ZIP upload for per-decl XLS/PDF shipped

**Date:** 2026-05-25 → 2026-05-27 (continuous session across date boundary).
**Branch:** `main`.
**Commits:** `f6f948f`, `db0a86f`, `a331c74` — all pushed to `origin/main`
and deployed to demo box via push-triggered CI runner.

## What Was Done

### 1. Feature: bulk-upload ZIP for per-declaration XLS/PDF files

Shipped a 2-step preview/confirm flow at
`/clients/{id}/declarations/upload-zip`. The single-upload form gained
a second tab "Tải hàng loạt (ZIP)"; on submit the server extracts
supported members into `/tmp/data-hub-staging/zip-<uuid>/`, parses each
via the existing `app.parsers.declaration_files` parser, dedup-checks
against `customs_declaration_files.sha256`, and renders a preview with
4 KPI cards (OK / Duplicate / Mismatch / Parse error) + a detail table
limited to non-OK rows. On confirm, ingest is skip-on-error and
counts redirect to the declarations index as a toast.

Architecture:

- `app/uploads/declaration_zip.py` — pure pipeline. `validate_zip` →
  `extract_to_staging` → `parse_staged_files` → `annotate_dedup_status`
  → `commit_staged_files`. Side modules: `cancel_staging`,
  `reap_expired_staging`, `get_staging_path`.
- `app/routes/declarations.py` — 3 new routes: preview, commit, cancel.
  Reaping happens at the start of every preview (no cron).
- `app/templates/clients/declaration_upload.html` — extended with
  tabs + inline JS toggler. Hash routing via `#bulk` / `#single`.
- `app/templates/clients/declaration_zip_preview.html` — new template.
- `app/parsers/declaration_files.py` — added
  `DeclarationFileMismatchError(DeclarationFileError)` so the bulk
  preview can distinguish mismatch from parse_error without
  substring-matching the exception message.

Caps (D6 in brief): ZIP ≤ 256 MB · extracted ≤ 2 GB · member ≤ 10 MB
· ≤ 5000 members. Caps enforced pre-extraction with `zi.file_size`
sum and per-member size + traversal checks. Python's `ZipExtFile`
enforces declared `file_size` during decompression, so the
sum-of-headers check is reliable against bombs.

Path traversal hardening on both sides:

- Member name — regex split on `[\\/]`, reject `..` component or
  absolute prefix; basename via `Path(zi.filename).name` strips dir
  components before write; uses `zf.open(zi)` + `dest.open("wb")` not
  `ZipFile.extract()` so symlink unix-extra-attrs are NOT honored.
- Staging ID — strict regex `^zip-<uuid8-4-4-4-12>$`; `get_staging_path`
  returns None for any mismatch. `cancel_staging` only acts on validated
  paths.

### 2. Two follow-up improvements (single commit `db0a86f`)

- `#bulk` hash preserved on every redirect that ends at the upload
  page (cancel, expired-staging error, invalid-ZIP rejection) so the
  operator lands back on the bulk tab.
- `.ai/features/2026-05-25-bulk-declaration-zip-upload/ui_smoke_real_corpus.py`
  walks 10 screenshots against 50 real Johnson TKN XLS + 2 injected
  non-OK files. All 4 status buckets exercised; dedup-at-scale
  (50/50 duplicate on re-upload) proved on real corpus.

### 3. Bell-hide (commit `a331c74`)

Notification bell `{% include "notifications/_bell.html" %}` commented
out in `base.html:39` per ad-hoc request. Backend (store + routes +
12 tests) intact. Re-enable = uncomment 1 line.

### 4. Testing + deploy

- 1175 passed, 15 skipped (was 1143 + 15 baseline → +32 new tests).
- Local smoke: 4 synthesized + 10 real-corpus screenshots committed.
- Demo deploy: CI auto-triggered on push. `Deploy to tinsu` step ✓ for
  both code commits (the "Smoke LLM /models (best effort)" step
  returned 401 against `codex-lb-demo.sgnai.dev/v1/models` — unrelated
  pre-existing CI redness, not a deploy failure).
- Demo verification: `https://ttdatahub.tinsu.ai/healthz → {"status":"ok"}`;
  `POST /clients/x/declarations/upload-zip → 422` (route exists,
  missing form field) confirms new code reached production container.

### 5. Memory + convention updates

- Updated `feedback_feature_folder_with_screenshots.md` to record the
  sub-folder exception: `screenshots/<set-name>/*.png` is acceptable
  when a feature has 2+ distinct smoke runs (precedent: this feature's
  `screenshots/real-corpus/`).

## Decisions Made

- **Two-step preview/confirm with disk staging** (brief D1): chosen
  over single-step or DB-staged. Rationale: simpler state, no schema
  change, multi-worker safe on single host because `/tmp/...` is
  shared. TTL 1h, reaped at start of every new preview (no cron).
- **Direction explicit, not auto-detected** (D2): filename heuristics
  insufficient across clients. Operator picks once per ZIP.
- **`validate_content=True` by default** (D3): mismatch detection is
  the whole point; mirror single-upload semantics.
- **Preview UI: summary cards + non-OK detail only** (D4): 2000-row
  full tables make the page unusable. OK + Duplicate are gross counts.
- **Skip-on-error commit** (D5): mirror CLI script behavior. Mismatch
  and parse_error rows are skipped at commit time, never ingested.
- **Caps locked** (D6): 256 MB / 2 GB / 10 MB / 5000. ZIP > 256 MB →
  operator falls back to `scripts/import_declaration_archive.py`.
- **`DeclarationFileMismatchError` subclass** (from /rev pass 1): the
  initial implementation distinguished mismatch from parse_error by
  substring-matching `"mismatch"` in the exception message. Subclassed
  exception is robust against future message rewording.

## What Didn't Work

- **First `set_input_files` selector was unscoped** — used
  `'input[name="file"]'` which matched the SINGLE-FILE form first
  (both tabs share the field name). Form submitted with no file,
  server redirected back with error, screenshot captured the upload
  form instead of the preview. Fix: scope to `#panel-bulk input[name="file"]`.
- **First `wait_for_url` glob was too loose** — `"/declarations"`
  matched the source URL `"/declarations/upload"` so the wait returned
  immediately without waiting for navigation. Fix: use
  `"**/declarations/upload-zip"` and `"**/declarations?**bulk_inserted**"`.
- **`#bulk` hash dropped on cancel redirect** — first cut returned
  `/declarations/upload`, operator landed on single tab. Caught by
  real-corpus smoke. Fix bundled into `db0a86f`.
- **First commit's route test asserted `endswith("/upload")`** — broke
  after #bulk hash fix. Updated assertion to `endswith("/upload#bulk")`.

## Open Items

- **CI: Smoke LLM /models (best effort) step is chronically red** —
  401 against `codex-lb-demo.sgnai.dev/v1/models` because the workflow
  doesn't pass an auth token. Makes the deploy-to-tinsu job report
  failure even when actual deploy steps succeed. Worth a separate PR:
  either pass token, or replace `set -e` + `curl -fsS` with
  `curl -fsS … || true`, or remove the step.
- **Notification bell hidden** — `base.html:39` has `{% include %}`
  commented out. Re-enable by uncommenting when the notification
  feature is complete. Backend (12 tests passing) intact.
- **TTL 1h not yet validated against operator usage** — staging dirs
  reaped after 1 hour. May need to be longer if operators stage
  previews then leave for a meeting before confirming. Bump to 4h if
  feedback says so.
- **Body-size on reverse proxy** — server caps at 256 MB but if/when
  nginx is added in front of uvicorn it needs `client_max_body_size 256m`
  on the `/clients/*/upload-zip` location. Demo currently goes
  Cloudflare → docker → uvicorn (no nginx mid-stream); not blocking.
- **Real-corpus full-Johnson upload not tested** — only 50 of the 2351
  TKN files were exercised in smoke. The full corpus would exceed the
  256 MB ZIP cap; operator path for that is the CLI script.

## Notes for next session

- Dev server :8754 was running at last check (`nohup uv run uvicorn …
  --workers 4`). Check with `curl -sf http://127.0.0.1:8754/healthz`.
- Demo box is at `a331c74` (= origin/main HEAD). Verified by GET/POST
  smoke.
- Feature folder lives at `.ai/features/2026-05-25-bulk-declaration-zip-upload/`
  with `brief.md`, `ui_smoke.py`, `ui_smoke_real_corpus.py`, and
  `screenshots/` (4 flat + 10 in `real-corpus/`).
- Memory `feedback_feature_folder_with_screenshots.md` now documents
  the sub-folder exception for multi-smoke features.
