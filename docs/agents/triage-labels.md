# Triage Labels

The skills speak in terms of five canonical triage roles. This file maps those roles to the
actual label strings used in this repo's tracker (`TinsuAI/data-hub` GitHub Issues).

| Canonical role    | Label in our tracker | Meaning                                  |
| ----------------- | -------------------- | ---------------------------------------- |
| `needs-triage`    | `needs-triage`       | Maintainer needs to evaluate this issue  |
| `needs-info`      | `needs-info`         | Waiting on reporter for more information |
| `ready-for-agent` | `ready-for-agent`    | Fully specified, ready for an AFK agent  |
| `ready-for-human` | `ready-for-human`    | Requires human implementation            |
| `wontfix`         | `wontfix`            | Will not be actioned                     |

No renaming — the default vocabulary is used verbatim.

`wontfix` ships with GitHub. The other four were created on 2026-07-10.

The nine stock GitHub labels (`bug`, `documentation`, `duplicate`, `enhancement`,
`good first issue`, `help wanted`, `invalid`, `question`, `wontfix`) remain available;
only `wontfix` carries triage meaning.

## Note on `/triage`

`/triage` is for issues **you did not create** — inbound bug reports and feature requests.
Tickets cut by `/to-tickets` from a brief are already agent-ready and must not be triaged.
This project currently has no inbound reporters, so `needs-triage` and `needs-info` will
stay unused until it does.
