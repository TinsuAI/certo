# Triage labels

Since 2026-07-11 the tracker of record is GitHub Issues (`TinsuAI/co`), and the five
canonical triage roles exist there as real labels (default names):

- `needs-triage` — needs evaluation / scoping
- `needs-info` — waiting on the reporter (usually the user) for more detail
- `ready-for-agent` — fully specified, AFK-ready: an agent can pick it up with no extra human context
- `ready-for-human` — needs human implementation or a human decision
- `wontfix` — will not be actioned

A freshly captured item with no triage label is treated as `needs-triage`.

Local markdown files under `.ai/` (specs, archive copies of tickets) may carry the same
role as a `Status:` line near the top (e.g. `Status: ready-for-agent`); when a file has a
GitHub counterpart, the GitHub label wins.
