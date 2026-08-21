# 2026-07-11 — Catalog plan verification, design review, issue amendments

## What was done

Session goal drifted deliberately: started as "start dev server", became "re-establish
trust in the catalog tickets (#30–#35) before building anything". No product code changed.

1. **Dev server** up on :8754 (`--workers 4`, background task).
2. **#31 claims verified against code + DB**: all 13,631 `hub.materials` rows are
   `status='active'`; list route (`app/routes/api.py:465`) filters status only when the
   caller passes `?status=`; get-by-code (`:506`) has no status filter at all. Premise held.
3. **#30 claims verified**: exactly two `.` junk materials (growatt-vn, johnson-vn, both
   `bcct_observed`); `derive_from_bcct` (`app/stores/provenance.py`) has no placeholder
   exclusion while 3,509 Growatt + 13 Johnson BCCT rows carry `customs_code='.'`; the
   `'.'` check is scattered over `_is_missing_hq` (`app/parsers/catalog_candidates.py:27`),
   `app/stores/catalog_candidates.py:611`, `app/routes/catalog_candidates.py:321`;
   `hub.clients` has no placeholder column. Premise held. One cosmetic error: issue cites
   `provenance.py:33`, function def is at `:79`.
4. **Status semantics established** (answering "won't the filter hide unapproved NVL from
   CO?"): `status` is NOT the approval gate. BCCT-observed NVL are auto-inserted `active`
   at ingest by `derive_from_bcct`; approval is tracked on `source` (promote flips
   `bcct_observed→client_declared`, `catalog.py:1050`) plus the candidates queue.
   Enum: active / under_review / deprecated / tombstoned / inactive — non-active values
   set only manually (`catalog.py:1014`, `:1317`). Zero non-active rows today.
5. **Critic sub-agent review of #31** (Opus): verdict "needs amendment". Key: `active`-only
   default overloads status with approval semantics it doesn't carry; predicate should be
   `not in ('tombstoned','inactive')`; second leak surface found
   (`bcct_material_identity.py:120-133` serves dead rows to CO's BCCT identity payload);
   byte-identical oracle is non-discriminating; positive tests + API doc duty missing.
6. **Full catalog design review** (fork, Fable 5) — report committed at
   `.ai/features/2026-07-10-catalog-candidates-merge/design-review-2026-07-11.md`.
   Verdict: **keep the six-phase plan, amend #31 and #34, don't restructure.** Extra
   findings: trust ordering inverted (auto-ingest → `active`, human accept →
   `under_review`); #31's `active`-only would hide staff-accepted materials from CO
   between phases 1 and 4; #34 as written destroys the 1,207 accept decisions'
   `(decided_by, decided_at, decision_reason)`; brief and STATUS disagreed on phase order.
7. **All recommended actions executed:**
   - **#37 filed** (`ready-for-human`): BCCT-identity surface — open contract decision
     (hide dead rows vs deliberately keep them for historical resolution).
   - **#31 rewritten**: alive-only predicate, `?status=` param on get-by-code, positive
     test set, `API_CONTRACT.md`/`API_CHANGELOG.md` duty, #37 scope split, oracle demoted,
     pagination property recorded.
   - **#34 amended**: before dropping `catalog_candidates`, copy decided rows' decision
     tuples into `hub.bom_audit_events` (new `event_type`); drop migration must enumerate
     unreplayable columns.
   - **Brief reconciled**: order settled **1 → 0 → 2 → 3 → 4 → 5** (real edges: 3←0,
     4←3, 5←3+4); phase-1 row updated.
8. **Committed + pushed** `b6ece39` (brief + design review; also carried the previously
   unpushed `bb26b70` STATUS correction). Deploy run 29114048212 was in progress at
   session end — docs-only, no code change, version stays 0.20.0.

## Decisions made

- **#31 predicate: `status not in ('tombstoned','inactive')`**, list and get-by-code
  symmetric, 404 on dead code (CO degrades gracefully — verified all paths map 404→`{}`).
- **Phase order: 1 → 0 → 2 → 3 → 4 → 5** (brief's "don't do 1 before 0" had no mechanism).
- **Six-phase plan stands** — no restructure.
- **#34 must preserve decision audit** via `bom_audit_events`, not a new audit table.
- **BCCT-identity surface is a deliberate open decision (#37)**, not a bug to auto-fix.

## What didn't work / traps

- `gh` label on issue creation: only `ready-for-human`/`ready-for-agent` used; fine.
- zsh ate a bare `===` in a compound echo — quote such separators.
- Critic and fork agree independently on the predicate — useful pattern: verify claims
  first in-session, then hand the verified fact sheet to reviewers so they judge, not
  re-derive.

## Open items

1. **`/implement` #31 (amended)** — fresh session, **branch first** (push to `main`
   deploys prod), commit `Closes #31`.
2. Then #30 → #32 → #33 → #34 → #35 per settled order.
3. **#37 decision** is user's: dead rows in BCCT identity payload — hide or keep.
4. Carried over from previous sessions: CO refresh-token integration unbuilt; prod
   Postgres collation mismatch; `v0.19.0` tag absent; `docs/agency-staff-guide` branch
   unmerged; CO's PR #11 question (raster scans in dossiers).

## Postscript — deploy network incident (same session, after the handoff commit)

Both docs-only pushes (`b6ece39`, then `152b432`) hit a box-level outbound network
outage on `tinsu` (~18:18–18:49 UTC = 01:18–01:49 +07):

- Run `29114048212` (`b6ece39`): Test job hung 17+ min on "Install LibreOffice"
  (24s on the last green run) — apt couldn't reach mirrors. Cancelled as superseded
  by the next run.
- Run `29114412818` (`152b432`): Test + Docker build green; "Deploy to tinsu" died
  at "Compose up" with **empty step logs** — the self-hosted runner lost GitHub
  mid-job. The container was untouched; the old build kept serving at the origin.
- Externally `ttdatahub.tinsu.ai` returned CF `530` / error `1033`.
  `journalctl -u cloudflared` on the box: repeated "failed to dial a quic
  connection … timeout: no recent network activity"; the tunnel re-registered on
  its own at 18:49:41Z (hkg01).
- Fix: `gh run rerun 29114412818 --failed` after the network recovered → deploy
  green. Prod verified: `/version` → `0.20.0` @ `152b432`, `/healthz` → `200`,
  anon `/v1/hub/dncxs` → `401`.

Lesson: one network blip produced three unrelated-looking symptoms (hung apt step,
dead deploy job with no logs, CF 1033). Before assuming a deploy broke prod: ssh
the box, curl the origin `/healthz` locally, check `docker ps` for the app
container, then `journalctl -u cloudflared`. Note `gh run view --log-failed`
returns nothing for a job whose runner died — the JSON `.jobs[].steps[]`
conclusions still show where it stopped.
