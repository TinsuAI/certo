# Triage labels

This repo uses a local-markdown issue tracker, so triage roles are recorded as a `Status:` line
inside each issue/feature file (e.g. `Status: ready-for-agent`), not as remote labels. The five
canonical roles use their default names:

- `needs-triage` — needs evaluation / scoping
- `needs-info` — waiting on the reporter (usually the user) for more detail
- `ready-for-agent` — fully specified, AFK-ready: an agent can pick it up with no extra human context
- `ready-for-human` — needs human implementation or a human decision
- `wontfix` — will not be actioned

A freshly captured item with no `Status:` line is treated as `needs-triage`.
