# The Engineering Flow

The skills in `~/.claude/skills/` form one main flow, two on-ramps that merge onto it, and
a few things that sit off to the side. This file explains the whole shape and records how
it maps onto **this repo** after the 2026-07-10 configuration.

Source of truth for the flow itself is `~/.claude/skills/ask-matt/SKILL.md`. Source of
truth for the repo's config is `docs/agents/{issue-tracker,triage-labels,domain}.md`.

---

## 1. The main flow: idea → ship

```
                    /grill-with-docs          sharpen the idea by interview
                            │                 (stateful: writes CONTEXT.md + ADRs)
                            ▼
        ┌───────  can every question be settled in conversation?  ───────┐
        │ no                                                         yes │
        ▼                                                                │
   /handoff out                                                          │
   /prototype       throwaway code answers one design question           │
   /handoff back                                                         │
        └────────────────────────────┬───────────────────────────────────┘
                                     ▼
                     is this a multi-session build?
                    ┌────────────────┴────────────────┐
                yes │                                 │ no
                    ▼                                 │
               /to-spec        thread → spec          │
                    ▼                                 │
              /to-tickets      spec → tickets,        │
                    │          each declaring its     │
                    │          blocking edges         │
                    ▼                                 ▼
              /implement  (once per ticket, fresh context each time)
                    │
                    ├── drives /tdd internally, one red-green slice at a time
                    └── closes with /code-review, then commit
```

**Why grill first.** An idea you cannot state precisely cannot be specced. The interview is
where imprecision surfaces. `/grill-with-docs` is the stateful variant — it leaves a paper
trail in `CONTEXT.md` and ADRs. `/grill-me` is the same interview with no repo to write to.
Both run the same `/grilling` primitive.

**Why the prototype detour.** Some questions have no verbal answer: does this state model
feel right, what should this screen look like, is this query fast enough. Write throwaway
code, keep the answer, delete the code.

**Why tickets carry blocking edges.** On a real tracker the edges become native blocking
links, so any ticket whose blockers are closed can be picked up by whoever is free. A
ticket is a thin slice through the system, not a layer of it.

**Why context is cleared between tickets.** Steps 1–3 belong in one unbroken context window
so that grilling, spec, and tickets build on the same thinking — do not `/compact`, do not
`/clear` until `/to-tickets` is done. Then each `/implement` starts fresh from its ticket.
The limit is the **smart zone**, roughly 120k tokens, within which the model still reasons
sharply. If a session approaches it before `/to-tickets`, `/handoff` rather than push on
degraded.

**Shortcuts.** Reach for `/tdd` alone to build one concrete behaviour test-first without a
spec. Reach for `/code-review` alone to review a branch against a fixed point.

---

## 2. The two on-ramps

A starting situation that generates work, then merges onto the main flow.

### Bugs and requests piling up → `/triage`

Turns issues **you did not create** into issues an agent can act on. See §6 — it is the
skill most often misused, because it looks like a general issue-grooming tool and is not.

### Something is broken → `/diagnosing-bugs`

For the hard ones: the bug that resists a first glance, the intermittent flake, the
regression that crept in between two known-good states. It refuses to theorise until it has
a **tight feedback loop** — one command that already goes red on *this* bug — and then fixes
with a regression test.

When its post-mortem concludes that there was no good seam to lock the bug down, it hands
off to `/improve-codebase-architecture`.

### A large, foggy effort → `/wayfinder`

When the way from here to the destination is not visible yet. It charts a map of
investigation tickets on the tracker and resolves them one at a time, producing
**decisions, not deliverables**, until the way is clear. Then it merges onto the main flow
at `/to-spec` — or straight to `/implement` if the effort turned out small.

`/grill-with-docs` is for an idea you can hold in one session. `/wayfinder` is for the idea
you cannot.

---

## 3. Codebase health

`/improve-codebase-architecture` — the survey. Run it when there is slack. It finds
**deepening opportunities**: places where a lot of behaviour could hide behind a smaller
interface. Picking one *generates an idea*, which re-enters the main flow at
`/grill-with-docs`.

`/codebase-design` — the bench you design the chosen one on. Survey finds the candidate;
design shapes it.

---

## 4. Vocabulary underneath

Two references that run beneath everything else. Each is the single source of truth for its
vocabulary. Reach for them when the **words**, not the process, are the problem.

- **`/domain-modeling`** — the language of the *domain*. Challenge a fuzzy term, resolve a
  word doing three jobs, record a hard-to-reverse decision as an ADR.
- **`/codebase-design`** — the deep-module vocabulary: module, interface, depth, seam,
  adapter, leverage, locality. The shape of a module, not the shape of the domain.

---

## 5. Crossing sessions

**`/handoff` forks. `/compact` continues.**

`/handoff` compacts the conversation into a markdown file. You do not continue in place —
you open a new session and reference that file. Use it when you want a fresh window but
need the current conversation preserved.

`/compact` (built-in) stays in the same conversation and lets earlier turns be summarised.
Use it at intentional breaks between phases. Never mid-phase.

---

## 6. `/triage` in detail

It converts an inbound issue into one an agent can execute. That is its whole job.

**Only for issues you did not create.** Tickets cut by `/to-tickets` are already agent-ready.
Triaging them re-litigates settled work.

### Labels

Every triaged issue carries exactly one **category** and one **state**. Conflicting state
labels stop the skill, which asks before doing anything else.

| Category | | State | |
|---|---|---|---|
| `bug` | something is broken | `needs-triage` | maintainer must evaluate |
| `enhancement` | new feature or improvement | `needs-info` | waiting on the reporter |
| | | `ready-for-agent` | fully specified, agent can run unattended |
| | | `ready-for-human` | needs judgement, external access, or manual testing |
| | | `wontfix` | will not be actioned |

Unlabeled → `needs-triage` → one of the other four. `needs-info` returns to `needs-triage`
once the reporter replies.

### The five steps

1. **Gather context, and run two checks most people skip.**
   - *Redundancy* — is this already implemented? Search by **domain concept, not by the
     reporter's wording**. If found, it is a `wontfix` of the "already built" kind: point at
     where it lives, and do **not** write to `.out-of-scope/`.
   - *Prior rejection* — read `.out-of-scope/*.md` and surface anything that resembles this
     request.
2. **Recommend, then stop.** Category, state, reasoning, and a summary of the relevant
   codebase. Wait for the maintainer.
3. **Verify the claim before designing anything.** Reproduce the bug from the reporter's
   steps. Report one of: confirmed (with the code path), not reproducible, or insufficient
   detail — the last is a strong `needs-info` signal. A confirmed verification makes a much
   stronger brief.
4. **Grill if needed.** Runs `/grilling` and `/domain-modeling` together, sharpening domain
   terms and landing ADRs inline.
5. **Apply the outcome** — agent brief, human brief, triage notes, or close.

### The agent brief is a contract

The comment posted when an issue moves to `ready-for-agent` is the authoritative spec. The
issue body and discussion are context; the brief is the contract.

- **Durable over precise.** The issue may sit for weeks while the codebase moves. Describe
  interfaces, types, and behavioural contracts. **No file paths. No line numbers.** No
  assumption that today's structure survives.
- **Behavioural, not procedural.** *"`SkillConfig` accepts an optional `schedule` field of
  type `CronExpression`"* — not *"open `src/types/skill.ts` and edit line 42"*.
- **Complete acceptance criteria.** Each independently verifiable. The agent must know when
  it is done.

### Two details that are easy to miss

Every comment triage posts to the tracker must begin with:

```
> *This was generated by AI during triage.*
```

`.out-of-scope/` is institutional memory for **rejected** enhancements — why, so the
reasoning survives the closed issue and a repeat request meets the old decision instead of
a fresh argument. It is not for things that were already built.

---

## 7. `/code-review` — two axes, and what it will not find

Adopted as this repo's closing review on 2026-07-10, replacing `/rev`.

Both axes run as **parallel sub-agents with isolated contexts**, so neither masks the other,
and their findings are **never merged or reranked**. A change can pass one and fail the
other: correct code that builds the wrong thing passes Standards and fails Spec; the right
feature written against the grain of the repo does the reverse.

- **Standards** — documented repo standards, plus a fixed baseline of 12 Fowler code smells
  (mysterious name, duplicated code, feature envy, data clumps, primitive obsession,
  repeated switches, shotgun surgery, divergent change, speculative generality, message
  chains, middle man, refused bequest). A documented repo standard always overrides the
  baseline. Smells are labelled judgement calls, never hard violations. Anything tooling
  already enforces is skipped.
- **Spec** — requirements the spec asked for but the diff misses, behaviour nobody asked for
  (scope creep), and requirements implemented wrongly.

**It does not hunt bugs.** Neither axis asks about logic errors, security holes, missing
error handling at I/O boundaries, or breaking changes to public interfaces. The retired
`/rev` did. For changes touching auth, migrations, or the `/v1/hub` surface, run the
harness's `/security-review` as a separate pass.

**It needs two inputs.** A fixed point for `git diff <point>...HEAD`, and a spec. The Spec
axis locates the spec from issue references in the commit messages, via
`docs/agents/issue-tracker.md` — which is why **every commit must reference its issue**
(`Closes #31`, `Refs #33`). Without that reference, the Spec axis has nothing to compare
against and skips.

---

## 8. How this repo is wired

| Concern | This repo |
|---|---|
| Issue tracker | GitHub Issues on `TinsuAI/data-hub`, via `gh`. Single ticket store. |
| PRs as a request surface | **No.** Triage does not read them. |
| Triage labels | The five canonical names, unrenamed. `wontfix` shipped with GitHub; the other four created 2026-07-10. |
| `CONTEXT.md` | Does not exist. `.ai/GLOSSARY.md` plays that role. Do not create a root `CONTEXT.md`. |
| ADRs | `docs/adr/`, one file per decision, immutable. `.ai/DECISIONS.md` is the frozen predecessor. |
| Spec store | `.ai/features/<slug>/brief.md`. `/to-spec` is largely redundant here. |
| Backlog | `.ai/BACKLOG.md` is **frozen**; its open items became issues #14–#35. |
| Closing review | `/code-review`. `/rev` retired. |
| Session handoff | `/handoff` if the user types it; otherwise the agent writes `.ai/sessions/YYYY-MM-DD-<topic>.md` and updates `.ai/STATUS.md` by hand. |

### Who can invoke what

The agent calls these itself:

`/tdd` · `/code-review` · `/codebase-design` · `/domain-modeling` · `/grilling` ·
`/prototype` · `/research` · `/diagnosing-bugs` · `/qa` · `/request-refactor-plan` ·
`/resolving-merge-conflicts` · plus the repo's own `/discover`, `/fix`, `/scaffold`

**The user must type these** — they set `disable-model-invocation: true`, and must appear at
the **start** of a message or the harness treats them as plain text:

`/ask-matt` · `/handoff` · `/implement` · `/to-spec` · `/to-tickets` · `/triage` ·
`/wayfinder` · `/grill-with-docs` · `/grill-me` · `/improve-codebase-architecture` ·
`/teach` · `/ubiquitous-language` · `/writing-great-skills` · `/setup-matt-pocock-skills`

### Deviations, and why

- **`/to-spec` is mostly redundant.** A feature brief already is the spec. Cut tickets from
  it directly.
- **`/implement` cannot be agent-invoked.** It only wraps `/tdd` + `/code-review`; run those
  two directly and the result is the same.
- **`/setup-matt-pocock-skills` was run by hand.** Do not run it again — it would add a
  duplicate `## Agent skills` block to `AGENTS.md`.
- **`/triage` has no input yet.** No external reporters. The 22 issues on the tracker were
  all cut from a backlog or a brief, so they are already agent-ready. Do not triage them.
  `needs-triage` and `needs-info` will stay unused until someone from outside files an issue.

---

## 9. A worked example — the 2026-07-10 catalog session

Useful because it did **not** follow the main flow, and the reason is instructive.

The session started with "review the catalog build flow". `/grilling` was invoked early and
abandoned after two questions: it was asking which design to pick while nobody yet knew the
subsystem had four write paths. **Grilling was called too early.** It interviews to choose
between options; there were no options yet, only fog.

What the session actually traced was closer to the `/wayfinder` on-ramp:

1. An ad-hoc survey of the subsystem — the job `/improve-codebase-architecture` does.
2. `/discover` (this repo's own) to produce `.ai/features/2026-07-10-catalog-candidates-merge/brief.md`
   — the job `/to-spec` does.
3. A `critic` sub-agent pass, which has no equivalent in this skill set, and which
   overturned two decisions in the brief.
4. A small prototype: build the link table in a temp table, run the collapse query, measure
   it. 0.162s. The job `/prototype` does.
5. Tickets cut by hand into issues #30–#35 with blocking edges — the job `/to-tickets` does.

The lesson is the one the router already states: for an effort where the way is not yet
visible, the entry point is `/wayfinder`, and it produces **decisions, not deliverables**
until the fog lifts. Only then does grilling have something to grill.
