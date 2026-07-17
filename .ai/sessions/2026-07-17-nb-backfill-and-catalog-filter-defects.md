# Session 2026-07-17 — NB two-source backfill (#53) + catalog filter defects (#54)

Third session of 2026-07-17. Earlier: the codebase audit + BOM `:batch` fix, the
`under_review` removal + PDF page selection, and the #52 BCCT derive-gap fix
(which shipped commits `02377c6`/`2992623` but **left no session log**).

## Context / why this session happened

Opened with `/ask-matt "tiếp tục việc C từ session trước"`. "Việc C" was not
recoverable from disk — the #52 session wrote no summary — and the repo has two
readings of "C" (the audit's C1..C8 findings, and the BACKLOG's C.x theme). Asked;
the answer was **"cái vụ redesign ấy... mới làm được cái backfill gì thôi mà"** —
i.e. the deferred candidates bulk-approve UI redesign (STATUS Next Steps item 4;
its "#2" is a session-log item number, **not** an issue — repo has no issue #2).

## What Was Done

### 1. Grilling the redesign premise (`/grill-with-docs`)

Looked at the page before redesigning, per STATUS's own instruction. Facts that
reframed it:

- **The asymmetry.** `derive_from_bcct` (`app/stores/provenance.py:93`) reads only
  `bcct_rows.customs_code` — the HQ side — and auto-inserts `status='active'`
  materials at ingest with `category='nvl'` hardcoded. #52 made *every* entry point
  do it. An NB code extracted from the parens of the **same `goods_name`, same
  declaration line** never derives; it queues.
- **The queue was 2,704 shown** (2,683 nb / 17 hq / 4 unified) + 207 machinery.
  The unfiltered bulk button would have taken 2,670 of 2,704.
- **Zero rejections ever**, both clients, whole history. The bulk button had been
  in prod since 2026-07-11 and **no human had ever pressed it**. The one human
  `catalog_candidate_decision` (2026-07-17 03:03) was a #49 test.
- **johnson-vn's queue is 0** — unified client, no parser rules, `bcct_nb_codes`
  empty. The problem is Growatt-shaped and 99% NB.

Advisor (on **fable**) ranked `(a) standing derive rule > (d) press+measure > (b)
filter vocabulary > (c) selection model`, and established that ADR-0001's "a human
presses the button. No standing rules that run at ingest" was written against the
`catalog_derive` **wizard** (dropped in mig 047) — line 56-57 says so itself:
*"rejected per-page regex authoring, **not automation**"*.

User chose **(d)**. Measuring inflow then proved impossible:

- All 39,203 growatt `bcct_rows` were indexed on **one day**, 2026-05-27
  (`distinct_days = 1`). Last BOM artifact 2026-05-29, last BQD 2026-05-05,
  newest declaration dated 2026-05-20.
- `docs/release-engineering.md:116` — **Tier P not stood up**, no paying customer,
  so no operator generates inflow.

**Inflow is zero, not unmeasured.** Both (a) and (d) were bets on a flow that does
not exist. What survived was the backfill on its own merits.

### 2. #53 — NB two-source backfill (SHIPPED local + prod)

`scripts/backfill_nb_two_source.py`, modelled on `backfill_bcct_derive_gap.py`.
Predicate: `>=2 of bcct/bom/bqd` + not machinery + `_derive_bulk_attrs` can infer a
category. Dry-run default, `--commit` to apply, actor `ops:backfill-nb-two-source-53`.

**Two sources, not one, is the whole argument.** The paren extract is the only
*guessed* stream; BOM/BQD rows are exact strings from client-authored files. A bad
parser rule yields **bcct-only** strings → stays queued. `bcct_nb_codes` is
delete-and-rebuild per client (ADR-0001), so one bad rule edit re-mints the entire
extraction — the second source is what keeps that out of a no-delete table CO reads
live. The 73 bom-only rows stay queued too (`provenance.py:150-153`).

Through `bulk_accept_codes`, **not** `derive_from_bcct`: the latter's hardcoded
`'nvl'` would mislabel the 23 `tp` rows, which CO would pull into its
origin-material set (its only filter is `category != "tp"`).

| | local | prod |
|---|---|---|
| accepted / skipped | **2,593 / 0** | **2,594 / 0** |
| materials | 850 → **3,443** | 849 → **3,443** |
| pending (shown + machinery) | 2,911 → **318** (111 + 207) | 2,912 → **318** (111 + 207) |
| BOM codes with no catalog row | 2,109 → **74** of 2,236 | — |

Both instances converged to identical numbers. The 1-row delta was `PV01.0105200`,
a dev-only artifact from the #49 UI test; **prod categorised it `tp` automatically,
matching the human's choice** — a live validation of the derive rule's category
logic on the only human decision the system has ever recorded.

Prod run: `scp` + `docker cp` into `data-hub-app-1`, dry-run then `--commit`
(#52's pattern). `/healthz` 200, version unchanged `0.21.0`/`4b958ef` — data only.

### 3. #54 — catalog filter defects (COMMITTED, not deployed)

**The user rejected the "no redesign needed" conclusion** — "*nghĩa là ko sửa gì
feature và UI hả? Tao thấy nó vẫn xấu xí, ko make sense về UX logic mà?*" — and was
right. The data analysis answered whether the *queue's contents* were a real review
surface (they weren't); it said nothing about whether the *page works*.

Reading the template found defects, verified live:

- **Every facet chip's count was computed in one filter state while its link
  navigated to another.** `?q=001.0033` shows **2 rows** under chips reading
  `NB (93)`, `BOM (73)`, `BCCT (4)`, `BQD (34)`. Counts came from `base` (machinery
  filter only); hrefs preserved `q`.
- **Navigation silently dropped filters.** Six params across three forms rehydrating
  each other by hand-written hidden inputs, each re-declaring only some of the rest.
  Live: tick «Chỉ lá BOM đã làm phẳng» (2,106) → click NB to narrow → `leaf=1`
  discarded → **2,683, wider**. A control meaning *narrow* returned a wider set, and
  «Tất cả» reported the filtered count so there was no denominator to catch it by.

Fix: `_filter_params` + `_filter_url_builder` own filter→URL; every chip, clear link
and form rebuilds from the full state with named facets overridden. Forms emit hidden
inputs by iterating `filter_params` rather than hand-listing. `_facet_rows` counts
each facet with its own filter dropped and the rest applied — the state that click
lands on.

**The invariant: a chip's number is the number of rows you get by clicking it.**
`tests/test_catalog_candidates_filter_state.py` (6 tests) over HTTP;
`.ai/features/2026-07-17-catalog-filter-state/ui_smoke.py` in a real browser.

### 4. `/code-review` (two axes) + advisor + fix bundle (`fa78a22`)

**Standards:** 0 hard violations, 8 judgement calls. **Spec:** 3 findings, 0 creep;
confirmed #53's predicate faithful and the standing rule not snuck in.

Applied (advisor-ranked): CHANGELOG corroboration claim, dev-login docs,
`_facet_count`→`_facet_rows`, double `_filter_params`, `ui_smoke.py` cleanups.
Left with reasons: private `_derive_bulk_attrs` import, divergent `PREDICATE` keys,
duplicated `main()`, six-param data clump.

## Decisions Made

- **The standing derive rule is DEFERRED, not rejected.** Revisit trigger is an
  **event, not a date**: the next real BCCT/BOM/BQD ingest, or a second dual-code
  client onboarding. The residue this backfill leaves *is* the standing rule's
  residue, so any new two-source NB code that appears is by construction one the
  rule would have derived — inflow becomes measurable then. Would need an ADR-0001
  amendment.
- **«Tất cả» drops only the kind facet.** #54's "should read 2,704" is **withdrawn**
  (amended on the issue + `brief.md`). Reading 2,704 requires clearing every facet,
  which re-runs Defect 2's own mechanism from a different chip. **Accepted cost:**
  with a rule-bar filter on, the unfiltered total appears nowhere; #54's "operator
  has no denominator" rationale is unmet. Advisor's verdict: that rationale was
  invented while writing the issue — there is no operator. Fix when one exists: a
  passive total in the header/rule bar, keeping the chip as-is.
- **Backfill judged as a backfill**, completing #52's NB side — not as stage one of
  an experiment.
- Work on a branch; `main` push auto-deploys prod.

## What Didn't Work

- **I turned a UX complaint into a data question and answered the data question.**
  The user caught it. Two separate things; clearing a backlog doesn't fix a surface.
- **A test that passed by coincidence.** Jinja escapes `&`→`&amp;` in hrefs (correct
  HTML). `TestClient.get(href)` parses `?q=X&amp;kind=nb` as a param named
  `amp;kind`, silently dropping everything after the first — so the kind facet was
  never applied and the assertion passed only because counts coincided. `_chips()`
  now `html.unescape`s. **Worth remembering: HTML-level assertions are not
  browser-level assertions.**
- **The advisor's mount-point inference was wrong.** It proposed `post_ingest_hooks`;
  that is BOM-**adapter**-scoped (`app/parsers/bom_adapters/__init__.py:321`), fired
  per artifact for one adapter — not a general ingest hook. A cross-stream rule needs
  an idempotent reconciler over all three ingest paths.
- My own first read of the 1-row prod/local delta blamed `047.0007100`; its
  `created_at` was my own backfill's timestamp. The real cause was `PV01.0105200`.
- `pkill` + `setsid` restart of uvicorn kept dying; `nohup setsid … & disown` worked.

## Open Items

1. **Nothing is deployed.** Branch `fix/nb-two-source-backfill`, 3 commits, **not
   merged**. `main` is **17 commits ahead of `origin/main`**, carrying migs 094+095.
   Prod's data already has #53's rows (script-applied) but not #54's code.
2. **Prod `schema_migrations` reads 093 while its data reflects 095.** `'..'` was
   hand-applied to `customs_code_placeholders` without recording the migration. 095
   is guarded idempotent (`and not ('..' = any(...))`), so the next deploy is safe —
   **by luck, not design**. 094 is also pending there.
3. **`docs/release-engineering.md:116` vs memory `project_prod_auth_enforcement`.**
   The doc calls `ttdatahub.tinsu.ai` **Tier D (Demo)** with
   `DATA_HUB_API_AUTH_DISABLED=1` and says Tier P is not stood up; the memory says
   never set that in prod and that `/v1/hub` is strict there. **One is wrong.** We
   wrote to that instance today. Unresolved — needs a human call.
4. **Shared dev DB has drifted from prod three ways**, all found today:
   `PV01.0105200` (a #49 UI test's material), `TEST_TP_DRIFT` (a fixture code inside
   real client `growatt-vn`), and the admin password. The conftest sweep only catches
   suffixed **clients**, not artifacts inside real ones. Local numbers ≠ prod numbers.
5. **~20 committed scripts hardcode `admin123`.** Correct today (it is
   `main.py:112`'s default and `.env` is never loaded), but they 401 against any DB
   seeded from a shell that *does* export `DATA_HUB_SEED_PASSWORD`. CO's server does
   exactly that (`set -a; . ./.env; set +a`).
6. **#54's scoped-out UI items**, recorded in `brief.md`, not filed: row «Duyệt» is a
   `<details><summary class="btn-primary">` fake button opening a 5-field form in a
   table cell; "Duyệt" names two different operations side by side; "Đề xuất" carries
   four unrelated meanings in one cell.
7. **Review items left by design** (advisor-reasoned): private `_derive_bulk_attrs`
   import, divergent `PREDICATE` keys, duplicated `main()`, six-param data clump.
8. **Issues #49/#50/#52/#53/#54 are all still OPEN** — their commits are unpushed, so
   nothing auto-closed.
9. **Untouched from earlier sessions:** #51 (Danh Mục `STATUS_MAP` CheckViolation),
   #26/S1 (`/v1/hub` fails open on fresh/restored DB — still the #1 ranked risk),
   audit findings C3 / S2 / S3 / C8 unfiled, #46 index (must run CONCURRENTLY
   out-of-band), the comprehension thread (4 of ~5 seams remain).
10. **`.ai/sessions/2026-07-17-codebase-audit-and-bom-batch-fix.md` is still
    untracked**, and the #52 derive-gap session has no log at all.

## Notes for Next AI Session

- **Run pytest serially** (`-p no:randomly`, one session). Shared dev DB: concurrent
  runs invent failures; a migration on one branch reds every other branch. Only the
  merged tree is a trustworthy gate. Baseline now **1680 passed, 16 skipped**.
- **Dev login is `admin@data-hub.local / admin123`** — docs said `local_test_password`
  until today and were wrong since 2026-05-05. `.env` is **not** auto-loaded (no
  dotenv import in `app/`).
- **Advisor must run on model `fable`** (memory `feedback_advisor_runs_fable`).
- Prod psql: `ssh tinsu@100.84.189.87` then
  `docker exec data-hub-db-1 psql -U hub -d data_hub`. Use Windows
  `/mnt/c/Windows/System32/OpenSSH/ssh.exe` — WSL ssh is broken, and the host does
  **not** resolve as `tinsu` (use the IP).
- **Do not re-derive the inflow analysis.** It is zero and the evidence is in §1.
- Undo handle for both backfills: the `catalog_bulk_accept` audit events'
  `details->'codes'` (393 and 2,593/2,594 entries). Undo = bulk `tombstoned`, never
  DELETE.
