# Session 2026-06-04 — Declaration download.zip "manifest-only" defect

## What Was Done

CO reported the Bearer route `GET /v1/hub/clients/{cid}/declarations/download.zip`
returned a 200 ZIP containing only `DANH_SACH_TO_KHAI.txt` — the named .xls files
absent — for johnson-vn (e.g. import `107271918940`, export `308189816340`). The
report's stated root cause: "the Bearer handler shares the manifest builder but not the
file-streaming loop; reuse the cookie route's assembly."

**Investigation overturned that root cause.** Both routes already call the same
`_build_declarations_zip` (introduced `21f3620`, 2026-05-15), which DOES stream blobs
(`backend.get(f.backend_key)` → `zf.writestr`). Confirmed in the running prod container.
13/13 existing Bearer provider tests passed, including the one asserting embedded files.

The real cause, found by probing prod: **johnson-vn was metadata-only.** All 3221
`hub.customs_declaration_files` rows had a `backend_key` + sha256 but no blob on disk —
`backend.get` raised FileNotFoundError, which the builder swallowed via
`except FileNotFoundError: continue`, yielding a manifest-only ZIP that still named the
file and reported "Thiếu file: 0". growatt-vn was fine (4038/4038 blobs present). The
cookie route would return the IDENTICAL manifest-only ZIP — the symptom was never
Bearer-specific; the report's "cookie includes the .xls" premise was false for johnson.

Two work items (with user approval at each gate):

**(A) Data remediation** — `scripts/backfill_declaration_blobs.py` (new): matches source
files to rows by **content sha256** (provably-correct bytes), dry-run by default,
idempotent, non-destructive (only `put`s currently-unresolvable keys).
- Source: repo `data/source_inventory/johnson-vn/2026-05-07-updated/Johnson/TKN|TKX/`
  (2351 + 870 files = exactly the import/export row counts).
- Prod `:8754`: tar'd source (454M) → streamed to box via `ssh.exe 'cat >'` → extracted →
  `docker cp` into container → ran `--apply`. Dry-run: 3221 matched / 0 unmatched / 0
  present. Apply: **done=3221 failed=0**.
- Nightly `:8764`: its DB is a prod snapshot, so backend_keys are identical. Instead of
  re-shipping source, stream-copied the blob dir container→container:
  `docker cp data-hub-app-1:.../johnson-vn - | docker cp - nightly-dh-app-1:.../`. 3221 files.
- Verified both envs: resolve_ok=3221, missing=0, **sha_mismatch=0**; download.zip for the
  two reported declarations now embeds the .xls (import 1.18MB, export 138KB) + manifest.

**(B) Code hardening** — `db7ae88` fix(declarations): a registered-but-missing blob is no
longer silently dropped. `_build_declarations_zip` resolves blobs in the staging pass and
collects unresolved file ids; `_build_manifest_text` adds a `File thiếu nội dung trên máy
chủ: N` count line + per-file `[THIẾU NỘI DUNG]` annotation; the archive gains a
`FILE_THIEU_NOI_DUNG.txt` marker. Healthy + zero-match outputs unchanged. Shared builder ⇒
cookie and Bearer stay byte-identical. New `tests/test_declarations_zip_missing_blob.py`
(3 tests incl. a Bearer==cookie golden). Full suite: 1306 passed, 15 skipped.

Deploy: CI run `26932326139` green; (B) live on prod + nightly. Blobs persist in volume
`data-hub_appfiles` (survive recreate). Transient source/script files cleaned off the box.

Also verified (user asked): nightly CO (`nightly-co-app-1`) calls **nightly** DH, not prod
— its `DATA_HUB_API_BASE_URL`/`JWKS_URL` use alias `dh-app:8754` → 172.29.0.5 =
`nightly-dh-app-1` on `nightly_default`; nightly CO isn't attached to `tinsu-shared`
(prod's net) at all, and its service token `iss=demo-datahub.tinsu.ai` wouldn't validate
against prod (`ttdatahub.tinsu.ai`) anyway.

## Decisions Made

- **Don't implement the report's suggested fix** — it was a no-op (the streaming loop
  exists). Surfaced the contradiction and the true root cause before touching code.
- **sha256 content-match for the backfill**, not filename — guarantees the restored bytes
  are exactly the registered ones regardless of naming.
- **Stream-copy prod→nightly blobs** rather than re-shipping 1.6G source, because nightly's
  backend_keys are identical to prod (DB snapshot). Verified by sha after.
- **Ship (B) even though (A) resolves the symptom** — the silent swallow is a genuine latent
  defect; honest reporting beats invisible data loss.

## What Didn't Work

- `python /tmp/script.py` in the container failed `ModuleNotFoundError: app` — Python puts
  the script's dir (`/tmp`) on sys.path, not cwd. Fix: `docker exec -e PYTHONPATH=/app`.
- `get_client` is in `app.routes.clients`, not `app.stores.clients` (first probe import
  error).
- Host can't read the docker volume dir as `tinsu` (root-owned) — verify blob counts via
  `docker exec ... find` inside the container, not host `find`.

## Open Items

- **Why did johnson land metadata-only?** Some ingest path created `customs_declaration_files`
  rows + parsed BCCT lines but never `backend.put` the .xls. Find and fix it so future
  ingests don't repeat the gap. growatt-vn was unaffected — compare the two ingest paths.
- **Nightly durability:** if the nightly cron re-snapshot wipes the files volume (vs DB
  only), the copied blobs would be lost — keys still match so a re-copy fixes it, and (B)
  shows the marker meanwhile. Prod is unaffected (blobs are original there now).
- CO to re-run its container-side probe (`download_declarations_zip` + `zipfile.namelist`)
  to confirm end-to-end. No CO change required.
