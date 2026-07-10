# Session 2026-07-11 (PM) — VN-origin spec + tickets; GitHub Issues becomes tracker of record

Docs/process only — no app code changed. Turned the closed VN-origin design
(12 ADRs, sessions 2026-07-10/11) into a spec and 8 published tickets.

## What was done

1. **Spec** (`/to-spec`): `.ai/features/2026-07-11-vn-origin-materials/spec.md` —
   synthesizes the 12 ADRs; 32 user stories; implementation + testing decisions; out of
   scope pinned (phase-2 in-bloc, doc_no/doc_date, status-enum refactor, per-row col-9
   edits). **Test seams user-approved:** Tính recompute seam (primary), route seam
   (guards + curation + config), pure-fn seam (`origin_country` module, `column9_text`);
   export==web parity as assertion, not seam.
2. **Tickets** (`/to-tickets`): 8 tracer-bullet slices, user approved. Only deviation
   from the grill's 7-ticket order: column-9 split into materialization (#9) + flip
   lifecycle (#10) to keep each in one context window.
3. **GitHub = tracker of record** (user decision after asking "why not GitHub?"):
   published as `TinsuAI/co` **#6–#13**, label `ready-for-agent`, created the five
   triage labels on the repo, bodies reference the spec path, blockers as real `#N`.
   Local `issues/01…08.md` files kept as archive copies, each linking its issue.
4. **Convention docs updated:** `docs/agents/issue-tracker.md` rewritten (issues →
   GitHub via gh, in dependency order; specs/BACKLOG/api-requests stay `.ai/`),
   `docs/agents/triage-labels.md` (roles = GitHub labels; GitHub wins over local
   `Status:` lines), `AGENTS.md` two summary blocks.

## Decisions made

- **Tracker of record = GitHub Issues** (option chosen over mirror-only and local-only).
  Recorded in `docs/agents/issue-tracker.md` + `AGENTS.md`, not as an ADR (process, not
  architecture). The old doc's "gh is not installed" was stale — gh 2.87.3 present,
  Issues enabled on TinsuAI/co.
- Ticket granularity/edges: #6,#7,#8,#13 frontier; #9←(#6,#7); #10←#9; #11←#6;
  #12←(#7,#9,#11). #8 (shortage guard) ships independently — legal urgency.

## Git

- `c55e433` docs(spec): VN-origin spec + 8-ticket breakdown (GitHub #6-#13)
- `f9d79f2` docs(agents): GitHub Issues becomes the tracker of record
- Plus this handoff commit. **All docs-only, on local `main`, NOT pushed**
  (origin/main = `312e58d`; push only reruns Deploy demo).

## What didn't work / notes

- The interactive `ls` alias on this box ignores a path argument (returned repo root
  for `ls .ai/sessions/`); use `command ls` in scripts.
- GitHub issue bodies: blocking edges are plain "Blocked by #N" text (no native
  dependency API used); keep publishing in dependency order so numbers exist.

## Open items (next session)

- **Build the frontier one ticket per fresh context** with `/implement`; fetch via
  `gh issue view <n>`. Start #6 (plumb) or #8 (shortage — urgent). Design is closed;
  do not re-grill.
- Push the 3 docs commits when the user wants them on origin.
- Standing non-ticket action items (unchanged): audit already-locked SHORTAGE sheets
  in prod; resolve the `missing_price` one-belt hole.
- At build time (ticket #11): confirm exact `consignee_name` spellings for Mingjie
  VN / Minghui VN; never flag `MINGJIE INDUSTRIAL (HK) LIMITED`.
