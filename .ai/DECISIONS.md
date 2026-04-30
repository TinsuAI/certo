# Architecture Decisions

<!-- Format:
## [Date] Decision Title
**Context:** Why this decision was needed
**Decision:** What was decided
**Alternatives:** What else was considered
**Consequences:** What this means going forward
-->

## Canonical decision pointer

Until Data Hub has its own discovery sprint output, the architectural decisions for this product live in the sister repo:

**`~/workspace/client/BCQT-System/.ai/DECISIONS.md` → "2026-04-30 PM — Data Hub 3-app architecture"**

That entry covers:
- Three Tinsu AI products (Data Hub + BCQT + CO).
- 3-app architecture, hybrid Postgres + per-project SQLite, strict app-data ownership.
- SSO via internal auth center in Data Hub.
- Code seed from CO (`barry-co-main`).
- BCQT reframed as Data Hub consumer.
- Three deployment shapes per agency.
- M9 umbrella milestone covering 3-app extraction + hybrid engine migration + deployment + SSO.
- Naming caveat: "Data Hub" is provisional.

## 2026-04-30 Project scaffold

**Context:** New product spun out from architectural decision in sister repo BCQT-System, made same day. Need a home for code + AI context before M9 discovery sprint.

**Decision:** Initial scaffold via `git init` + `ai-init --type app` + custom AGENTS.md preserving cross-repo context.

**Alternatives:** Could have folded into BCQT-System or barry-co-main as a sub-package, but the architecture decision (3 separate apps, strict ownership) requires distinct repo.

**Consequences:**
- Sister repo references will appear in commits + AGENTS.md + STATUS.md until Data Hub develops its own decision base.
- Tech stack picks deferred to M9 discovery sprint (audit CO first, match its stack).

---

## Decisions to add post-discovery

(Placeholder — entries to be written during/after M9 discovery sprint)

- Schema canonical choice per entity (BCQT current vs CO seed) — picked entity-by-entity.
- ORM/DAL choice (SQLAlchemy / psycopg raw / etc.).
- Migration tool choice (Alembic / raw SQL).
- Service-to-service auth model (token type, scope design).
- File storage abstraction implementation (`FileBackend` interface).
- SSO session/cookie strategy across 3 apps.
