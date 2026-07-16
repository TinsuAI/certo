# Session 2026-07-17 (PM2) — /clients 500 fix + growatt-vn allocation regex calibration

Two local bugfixes found from user reports, both shipped and deployed. `origin/main` = prod
`barry-co` = nightly `demo-co` = **`d769012`** (CI/CD `29529764304` green; `/version` verified
both hosts). A prod/nightly config change (seed run) is prepped but NOT run.

## What Was Done

### 1. `/clients` + `/` → 500 "Internal Server Error" — fixed (`8e10948`, runtime)
- **Symptom:** every portfolio page load returned a plain-text 500 (and a downstream 502).
- **Root cause:** `pages.clients()` iterates every Data Hub client and mirrors each into the
  local `clients` table via `upsert_client` (`app_state_store.py`). The local DH (`:8754`) has
  ~60 leftover test clients (`nxt-api-*`, `nxt-yo-*`, `sa-test-*`, `nxt_tier_test`…) with an
  explicit `tax_code: null`. `upsert_client` bound the five NOT NULL text cols with
  `payload.get(col, "")`, which returns `None` when the key is present-but-null → the first such
  client raised `NotNullViolation` and 500'd the whole list. Only `johnson-vn` / `growatt-vn`
  carry real tax codes locally.
- **Fix:** `payload.get(col) or ""` for name/code/status/tax_code/contact (`app_state_store.py:73-77`).
  One client with a missing field no longer takes down the whole portfolio. Local-dev-only symptom
  today (prod clients have real tax codes), but the fix hardens prod too.

### 2. growatt-vn "Chạy tồn tất cả → mọi sheet 'Đã nạp BOM', toàn 0" (case `co-case-3c13e6b34eb3`)
- **Root cause:** the LOCAL dev DB's growatt-vn allocation strategy was still `same_as_customs_code`
  — the 2026-07-17 #14 `description_regex` seed hit prod+nightly in-container only, never the local
  DB. BOM uses dotted internal codes (`001.*`, `012.*`); under `same_as_customs_code` the lot
  `allocation_code` = short customs code (`IC`, `DAUNOI`, `DAYTINHIEU`…) so only **25/850** BOM codes
  matched → every material a shortage + missing-price → `calculated_sheet_status` hard-blocks to
  `bom_loaded` (`co_case.py:2104-2112`), i.e. "Đã nạp BOM" + 0 everywhere.
- **Action:** ran `scripts/seed_growatt_vn_allocation.py` LOCALLY (→ `description_regex` + forced full
  re-derivation, 38,287 rows). BOM match 25→848/850; 3/6 sheets calculated.

### 3. Residual `012.0001400` = CODE-EXTRACTION error, NOT out of stock — fixed (`b98156a`, config)
- User asked: truly out of stock or extraction error? **Extraction error.** 20 lots hold tens of
  thousands of units (case demand = 116).
- **Mechanism:** lot descriptions carry TWO parens — a mfr part number + the internal code:
  `...20ohm/TH/5mm/M(SCK10202MSY). Hàng mới 100%(012.0001400)`. The broad regex matched BOTH →
  `resolve_allocation_code` (`client_config_store.py:145`) treats 2+ distinct matches as ambiguous
  → `review_code("multiple_regex_matches")` → `allocation_code = ""`. Blank code → BOM line matches
  no lot → false shortage.
- **Fix (per-client config, not shared code):** calibrated growatt-vn's `description_regex` to
  `\(\s*([A-Z0-9]+\.[A-Z0-9]+)\s*\)` — a single alphanumeric·dot·alphanumeric token filling the whole
  parenthesis. Keeps every real code shape (`012.0001400`, `B700.0141600`, `PE07.0073300`,
  `001.SK0002900`), rejects part numbers/specs (`SCK10202MSY`, `150W`, `380-415`, `1.25-16MM2`).
  Measured on growatt-vn: **848→849 matches, 38→0 ambiguity-blanked lots, no regression**.
- Generalized the seed script: it now normalizes strategy/regex/fallback to the calibrated target,
  stays idempotent, and is **stdin-safe** (guards `__file__`) so it runs both as a file (local) and
  piped in-container (prod) — `scripts/` is NOT copied into the Docker image.
- Applied locally → **5/6 sheets calculate, `missing_codes=[]`**. `PV06.0010800` computes to
  `lvc_status=fail` (a genuine RVC result, not a block); `PV01.0117900` is genuinely `missing_bom`.

### 4. Ship
- Full suite **910 pass / 14 skip** as a pre-push gate. Pushed `4e2eebd..d769012`. CI/CD green
  (build + tests + Deploy demo). `/version` = `d769012` on prod + nightly.

## Decisions Made

- **Null client fields → coalesce to "", don't filter the client.** One invalid client shouldn't 500
  the whole list, and in prod a real client with a temporarily-null field should still render.
- **Fix the growatt matching in the per-client `description_regex` config, NOT in the shared
  `resolve_allocation_code`.** The user explicitly flagged that hardcoding a "prefer the dotted match"
  tiebreak into the resolver would overfit the codebase to Growatt. The `description_regex` field is
  the #14-designed seam for exactly this client-specific knowledge; Johnson (`same_as_customs_code`)
  and other clients are untouched. The resolver's multi-match ambiguity guard stays intact as a
  general safety net (it just stops firing here because the regex no longer manufactures a false 2nd
  match).
- **`DEFAULT_DESCRIPTION_REGEX` left untouched.** Changing it would alter the demo `growatt` client
  and several test fixtures; the calibration is a growatt-vn config value only.
- **Did NOT clean the ~60 junk DH test clients.** They're DH-side data; the CLAUDE.md guardrail
  forbids modifying Data Hub from this repo. The code fix makes CO resilient regardless.
- **Prod seed prepped, not run.** Config/data change on prod deserves the user's go-ahead + a
  locked-case check, mirroring the 2026-07-17 vetting.

## What Didn't Work

- **Global regex tightening (dotted-only, e.g. `[A-Z0-9]{1,5}\.[0-9]{4,}`) regressed 848→838.**
  It required pure digits after the dot, dropping 11 real codes of the form `001.SK0002900` /
  `006.SK0004101` (letters after the dot). The correct invariant is alphanumeric·dot·alphanumeric,
  not digits-only — itself a lesson against assuming one code sub-format.
- **"Prefer the dotted match" tiebreak inside `resolve_allocation_code`** — worked numerically
  (848→849) but overfits Growatt's convention into the shared resolver. Rejected on the user's push-back.
- **Checking `goods_name` first was a false lead.** Locally `goods_name` is empty for all 38,287 rows;
  the internal code lives in `material_description` parens. (The 2026-07-17 prod notes say `goods_name`
  — local dev data differs.)

## Open Items

- **Run the calibrated seed on prod `co-app-1` + nightly `nightly-co-app-1`** (manual):
  `docker exec -i co-app-1 /app/.venv/bin/python - < scripts/seed_growatt_vn_allocation.py` (+ nightly).
  Prod growatt-vn still has the broad regex → same blanked lots expected. Vet first: confirm container
  names, check growatt-vn for locked cases (re-derivation changes stock `allocation_code`).
- **Optional:** calibrate `DEFAULT_DESCRIPTION_REGEX` (`client_config_store.py:40`) — the demo
  `growatt` client still uses the broad over-matching pattern.
- **`PV01.0117900`** on this case genuinely has no BOM (`missing_bom`) — separate from the extraction
  fix; not investigated.
- **Local DH clutter:** ~60 junk test clients (null tax_code) now render in the local portfolio with
  blank tax codes (no longer crash). Could be cleared DH-side if a tidy local list is wanted.

## Notes / Environment

- Local dev = auth-off + DB-mode (`:8001`, `npm run co:serve`). growatt-vn local stock: internal code
  in `material_description` parens (34,835/38,287 rows), `goods_name` empty. Distinct from prod.
- `scripts/` is NOT in the Docker image (`Dockerfile` copies app/db/docs/config/assets only) → prod
  runs one-off scripts via `docker exec -i … python - < script`. The seed script is now stdin-safe.
- Commit-message hazard hit again: backticks in `git commit -m` trigger zsh command substitution;
  used `git commit -F <file>` to fix.
