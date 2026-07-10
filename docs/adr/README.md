# Architecture Decision Records

One file per decision, immutable once merged. Superseding a decision means writing a new
ADR that says so — never editing the old one.

## Numbering and naming

`NNNN-kebab-case-title.md`, zero-padded to four digits, allocated in merge order.

## Status values

`Proposed` · `Accepted` · `Superseded by ADR-NNNN` · `Rejected`

## Relationship to `.ai/DECISIONS.md`

`.ai/DECISIONS.md` is this project's original decision log — 12 dated entries in one file,
running from 2026-04-30. It stays as the historical record; **do not migrate it**, and do
not edit its entries.

From 2026-07-10, **new decisions are written here**, one per file, because:

- The Matt Pocock engineering skills (`/domain-modeling`, `/grill-with-docs`,
  `/improve-codebase-architecture`) read `docs/adr/` by convention.
- A stable filename can be linked from a brief, a migration comment, or a sister repo.
- Immutability per file is enforced by structure rather than discipline.

Cross-repo architecture decisions (the 3-app split) remain canonical in
`~/workspace/client/BCQT-System/.ai/DECISIONS.md`. When an ADR here touches that, link it.

## Relationship to `.ai/GLOSSARY.md`

Matt's skills expect a root `CONTEXT.md` as the ubiquitous-language glossary. This repo
keeps that content in `.ai/GLOSSARY.md`. See `docs/agents/domain.md` for the pointer the
skills should follow.
