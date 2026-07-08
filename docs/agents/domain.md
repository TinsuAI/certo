# Domain Docs

How the engineering skills should consume this repo's domain documentation. **This repo keeps its
domain docs under `.ai/`, not in `CONTEXT.md` / `docs/adr/`.**

## Before exploring, read these

- **`.ai/GLOSSARY.md`** — the project's glossary / ubiquitous language (CO domain: trừ-lùi,
  bảng kê, BOM, tồn kho CO, dossier, C/O form, TKX/TKN, …). This is the `CONTEXT.md` equivalent.
- **`.ai/DECISIONS.md`** — architectural decisions and rationale. This is the `docs/adr/`
  equivalent.
- Also useful for context: `.ai/STATUS.md` (current state) and recent `.ai/sessions/*` (handoff
  history).

Any skill in this repo that instructs you to "read `CONTEXT.md`" should read `.ai/GLOSSARY.md`
instead; anything that reads "`docs/adr/`" should read `.ai/DECISIONS.md`.

If a term or decision isn't captured yet, **proceed silently**. `/domain-modeling` (reached via
`/grill-with-docs` and `/improve-codebase-architecture`) appends to `.ai/GLOSSARY.md` /
`.ai/DECISIONS.md` lazily, only when a term or decision actually gets resolved. Do **not** create a
separate `CONTEXT.md` or `docs/adr/` — this project deliberately uses `.ai/`.

Layout: **single-context** (one app, not a monorepo).

## Use the glossary's vocabulary

When your output names a domain concept (an issue title, a refactor proposal, a hypothesis, a test
name), use the term as defined in `.ai/GLOSSARY.md`. Don't drift to synonyms the glossary avoids.
If the concept you need isn't in the glossary yet, that's a signal — either you're inventing
language the project doesn't use (reconsider), or there's a real gap (note it for
`/domain-modeling`).

## Flag decision conflicts

If your output contradicts an entry in `.ai/DECISIONS.md`, surface it explicitly rather than
silently overriding:

> _Contradicts DECISIONS.md "event-sourced X" — but worth reopening because…_
