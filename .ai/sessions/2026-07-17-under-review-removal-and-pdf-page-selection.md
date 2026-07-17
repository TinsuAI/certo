# 2026-07-17 — `under_review` removal (#49) + declarations PDF page selection (#50)

Second session of 2026-07-17. The first was the codebase audit —
`.ai/sessions/2026-07-17-codebase-audit-and-bom-batch-fix.md`. Read that one
for the audit findings backlog; this log does not repeat them.

**Entry point:** user raised three items via `/ask-matt`. Two shipped, one
deferred.

> ⚠️ **`main` is 10 commits ahead of `origin/main` and NOT pushed.** Pushing
> auto-deploys PROD *and* applies migration 094 at boot. See "Open items".

---

## What shipped

Both merged to **local** `main`, not pushed. Final gate: **1670 passed, 16
skipped, 0 failed** on the merged tree, run serially.

| Commit | What |
|---|---|
| `2ad2292` | Merge #49 — `under_review` removed |
| `6e02593` | Merge #50 — page-selective declarations PDF |
| `88c94d2` | AGENTS.md stale baseline + shared-DB hazard |

### #49 — `materials.status='under_review'` removed entirely

Approving one candidate landed `under_review`; the bulk button beside it
hardcoded `active`. Two buttons, one page, two outcomes. And BCCT ingest —
which nobody reviews — auto-inserted `active`, so **the unreviewed path
produced the more trusted state**. ADR-0001 had already rejected this model in
so many words; the value survived as a leftover of the `catalog_derive` wizard
abandoned in the 2026-05-09 pivot.

Migration **094** drops it from the CHECK → `active | deprecated | tombstoned |
inactive`, flipping the 1 surviving row first. Also deleted: `promote_material`
+ its button, the `?status=under_review` chip, the badges, and the resolver's
`resolution_status='resolved_pending_review'`.

`promoted_to_declared_at` / `promoted_by` **retained** (3 dev-era rows carry
values; `bom_audit_events` has no record of those promotions) but no longer
read or rendered.

### #50 — declarations PDF prints only the pages a CO dossier cites

A real Growatt import declaration is **52-54 pages for 50 goods lines** —
roughly one line per page, VNACCS caps 50 lines/TK. A dossier cites a few, so
~90% of printed pages were irrelevant.

New `POST /v1/hub/clients/{cid}/declarations/download.pdf`, body
`{direction, declarations:[{declaration_no, lines?}], sort?, quality?,
max_part_bytes?, filename?}`. The GET is untouched and byte-identical.

Measured: a 5-declaration dossier citing 2 lines each went **262 pages / 978KB
→ 22 pages / 326KB**. That also finally fixes the Ecosys ~2MB limit, which
`quality=compact` never could — merged size is page-count driven.

---

## Decisions made

**1. Page selection keys on the form's own `<NN>` line marker.** The rendered
ECUS page text prints `<01>` on line 1's page, `<02>` on line 2's (`<IMP>` /
`<EXP>` is the watermark; the marker regex is numeric-only, `<(\d{1,3})>`).
Validated on 6 real declarations / 300 lines: `bcct_rows.line_no` set == marker
set **exactly**, 1 line per page, zero missing/extra.

**Rule (derived, never hardcoded):** a page with **no** marker is a non-goods
page → always keep. A page with a marker is kept only if its line was
requested. This matters — the header is *not* a fixed count: four declarations
have non-goods pages `[1,2]`, two have `[1,2,3,54]` (3-page header + trailer).
"Print page 1" or "pages 1-2" would silently drop a header page.

**2. REJECTED — matching NVL codes in page text.** Tested and discarded.
`customs_code` is an HQ bucket code: `IC` matched **24 of 52 pages**, `DOV` 14,
`TEM` 6, and `IC` false-positives into the header as a substring. NB codes do
work (150/150 found, zero substring collisions) but can be empty (CO
`requires_review` lots) or degenerate to the HQ code for clients configured
`same_as_customs_code`. Line numbers need none of that. *(Also: `customs_code`
is `'.'` on E13 fixed-asset declarations — a placeholder that matches every
page trivially. Cost one wasted probe.)*

**3. CO sends the line map; DH does not derive it.** Forced by architecture —
hub has **no cases table**; `case_id` is an opaque key in
`bom_artifacts.context` jsonb present only on `intent='modified_for_case'`
rows, so DH cannot resolve a dossier's NVL set. CO already has the data:
`case_tkx_tkn_summary` (`barry-CO-main/app/web/co_case_context.py:481-497`)
assembles `tkn[decl].lines[*].line_no` + `.material_code` per declaration, and
`_fetch` (`co_case.py:1500-1506`) throws it away keeping only `declaration_no`.
**One-callsite change on CO's side. Not yet done — CO is untouched.**

**4. POST, not GET** (advisor on `fable` concurred, with the decisive fact).
A line map is inherently per-declaration → cannot be a flat repeated param; at
the 500-declaration cap a URL encoding runs ~12KB, over nginx's default 8KB
`large_client_header_buffers` — and it only *appears* to work today because
CO→DH rides the internal Docker bridge past nginx. A contract whose max request
size depends on the proxy path is broken. **Nothing caches these responses
anyway**: `app/main.py:141-159` forces `Cache-Control: no-store, private` on
every `/v1/hub` path and attachment (added after the 2026-06-06 unauthenticated
leak), and nginx has no `proxy_cache`. Precedent: `POST
/v1/hub/products/bom/artifacts:batch` documents itself "Read-only, idempotent".

**5. Fallback = print ALL pages** (user's call). An entry with no `lines` →
every page. Never silently drop evidence. Makes POST a strict superset of GET.

**6. Whole pages only, never edit a page.** Stripping rows from the `.xls`
pre-render would renumber lines and break the `X/N` marker — the output would
stop being a faithful copy of the filed declaration and be disqualified as
customs evidence.

**7. #49 scope = FULL removal** (user's call over minimal/middle).

**8. API_CHANGELOG entry filed `Cosmetic`, not `Breaking`.** The heading
decides whether CO/BCQT operators get a notification. Grep proved **zero**
`under_review` / `resolved_pending_review` consumers in either repo, so by the
changelog's own definition ("sister apps must update code") it is not Breaking,
and a Breaking heading would fire a notification demanding nothing. Judgement
call — revisit if that definition is ever loosened.

**9. Historical changelog entries get NEW entries, not edits.** The 2026-07-11
/ `0.21.0` entries recorded `under_review` as live. That was **true on that
date**. `API_CONTRACT.md` is different — it states the *current* contract, so it
was edited in place.

---

## What didn't work

**The parallel-agent test results were both wrong, in opposite directions.**
Two agents ran concurrently against the **shared** dev DB
(`postgresql:///data_hub`). #49 reported `1620 passed, 0 failed`; #50 reported
`12 failed + 5 errors, identical to clean main`. Both were partly right and
both drew a wrong conclusion — one called the failures flaky, the other called
`main` red.

Two *distinct* causes, which look identical:
1. **Migration skew** (deterministic): mig 094 on #49's branch reded every
   other branch including `main`, because their tests still post
   `status="under_review"`. Survives a serial re-run. Resolves on merge.
2. **Concurrent-run interference** (phantom): two pytest sessions at once
   invent failures that pass in isolation.

I initially misdiagnosed (1) as (2) and told the user "main is not red" — wrong.
**A git worktree isolates files, not the database.** Saved as memory
`feedback_test_db_shared_across_branches`; also documented in AGENTS.md.

**Two claims in my own agent brief were fabricated, and the agents caught both:**
- "Find the existing byte-identity test and make it gate your change" — **there
  was no such test.** The promise at `API_CONTRACT.md:974,994` was documented
  but never tested. The agent wrote one.
- "A kept page still reads `4/54`" — invented. The form's marker actually reads
  `3/52` on PDF page 4 of `108234677720`; its internal numbering matches neither
  the PDF index nor the render length. The invariant (content untouched) holds;
  the number did not. Agent corrected the wording rather than propagate it.

**Issue #49's scope item 6 was wrong.** I claimed `catalog.py:598-600` was the
`under_review` chip handler. It is the **generic** `status` filter serving the
Active and Deprecated chips too — deleting it as specified would have broken
both. The agent caught it and removed only the chip.

**#49's scope missed a write path.** `POST /clients/{cid}/catalog/{code}/edit`
also wrote `under_review` and would have thrown a **500 CheckViolation on a real
user action** once mig 094 landed. Now rejects with 400. It was in-scope under
#49's own "no code path can write it" criterion.

---

## Review

`/code-review` run on #49 (`main` fixed point, spec #49). Two axes, unmerged.
**Spec: 0 missing / 0 wrong**, both Done-when criteria independently verified.
**Standards: 8 findings.** User certified 1, 2, 3, 5, 6, 8 → fixed in `fb0c014`;
4 (UI proof) skipped as removal-only; 7 pre-existing.

#50's implementing agent ran `/code-review` on itself and its Spec axis caught a
real self-introduced regression: a hoisted shared validator changed the GET's
error `detail` precedence when two params are bad at once — which **CO branches
on**. Fixed in `31d11cb`.

Notable fixes from the bundle: the `EDITABLE_STATUSES` dedup covers only the
three *editable* sites — the mig-094 CHECK stays separate **on purpose**, since
it admits `inactive`, which is storable but must not become hand-settable.

---

## Open items

1. **PUSH DECISION — `main` is 10 commits ahead, unpushed.** Pushing
   auto-deploys PROD and applies **migration 094** at boot. Migration is
   idempotent-safe (flips rows before the constraint) and verified clean on a
   fresh DB. Consider `/security-review`: #50 adds a new `/v1/hub` surface.
2. **Version still `0.21.0`.** Now two more `[Unreleased]` entries (#49 Sửa,
   #50 API) on top of #47's. Decide the release cut — this is a bigger bump
   than the `v0.21.1` the last session contemplated.
3. **CO has not adopted #50.** The POST exists and is unused; CO still calls the
   GET and gets all pages. The change is one callsite —
   `barry-CO-main/app/routers/co_case.py:1500-1512` stops discarding
   `lines[*].line_no`. Sister-app note **not** written for #50 (only for #49).
4. **#2 — candidates bulk-approve UI redesign. DEFERRED, and its premise
   changed.** #49 removed half the incoherence (the two buttons now agree).
   **Re-look at the page before redesigning.** The likely remaining complaint is
   the model, not the styling: "the filter IS the rule" means no checkboxes, no
   per-row selection — you cannot approve 5 and skip the 6th. The server
   deliberately does not trust a client-sent code list (`_filter_pending`,
   `stores/catalog_discovery.py:60`, is shared by the GET render and the POST).
   Needs `/grill-with-docs` in a **fresh** window — user-typed only.
5. **#51 filed** — Danh Mục upload with a status column raises CheckViolation.
   `STATUS_MAP` (`app/parsers/materials.py:94-103`) emits `pending` /
   `discontinued`, illegal since **mig 042** dropped them without updating the
   parser — 52 migrations of latent breakage. Also `inactive` → `discontinued`
   looks like a plain inversion bug. Open question in the issue: which legal
   status each label should map to.
6. **Prior session's backlog is untouched** — the unfiled audit findings (C3,
   S2, S3, C8) and the ranked work (#26/S1 fail-open, #46 index) are still open.
   See that session log.

## Notes for next session

- **CO's `data_hub_client.py:1118`** now holds a dead reference:
  `resolution_status not in ("resolved", "resolved_pending_review")`. Harmless —
  the removed element just stops matching. Drop it next time CO is touched.
- **Run the suite serially** (`-p no:randomly`, one session). Never trust a
  single-branch red while another branch holds an unmerged migration; the gate
  is the **merged** tree.
- `AGENTS.md`'s pytest baseline is now dated (`~1670 passed, 16 skipped
  (2026-07-17)`) and documents the shared-DB hazard. It had read "219 passed"
  — off ~7x — and cost two agents a run each.
- Advisor must run on model `fable` (memory `feedback_advisor_runs_fable`).
- Prototype scratch deleted; its answer lives in #50 + this log.
