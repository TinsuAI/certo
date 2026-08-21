# Domain Docs

Where this repo keeps the domain documentation the engineering skills expect, and what to
read before exploring the codebase.

## Before exploring, read these

- **`.ai/GLOSSARY.md`** — this repo's ubiquitous-language glossary. It plays the role the
  skills call `CONTEXT.md`. There is no root `CONTEXT.md` and none should be created.
- **`docs/adr/`** — architecture decision records, one file per decision, immutable.
- **`.ai/DECISIONS.md`** — the original single-file decision log (12 entries, from
  2026-04-30). Historical record. New decisions go to `docs/adr/` instead.

For cross-repo architecture (the Data Hub / BCQT / CO three-app split), the canonical
source is `~/workspace/client/BCQT-System/.ai/DECISIONS.md`, entry
*"2026-04-30 PM — Data Hub 3-app architecture"*.

## Also load at session start

Project convention, not a skill requirement, but the skills benefit from it:

- `.ai/STATUS.md` — current progress, blockers, next step
- the last 2-3 files in `.ai/sessions/` — full handoff context
- `.ai/features/<slug>/brief.md` — per-feature specs. Grep here **before** auditing a
  topic; a recent brief may already cover it.

## Writing new decisions

`docs/adr/README.md` has the numbering, status vocabulary, and the relationship to
`.ai/DECISIONS.md`. Offer an ADR only when the decision is hard to reverse, surprising
without context, and the result of a real trade-off.
