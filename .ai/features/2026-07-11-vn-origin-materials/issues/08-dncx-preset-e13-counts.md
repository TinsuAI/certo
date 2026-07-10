# 08 — `dncx` preset +E13, per-type counts, exclusion warning

Status: ready-for-agent — tracked on GitHub: [TinsuAI/co#13](https://github.com/TinsuAI/co/issues/13) (tracker of record)

## Parent

`.ai/features/2026-07-11-vn-origin-materials/spec.md` (build-order ticket 7).

## What to build

Onboarding a DNCX client via the config preset stops silently dropping their on-spot
domestic purchases: the `dncx` eligible-declaration-types preset becomes
`["E11","E13","E15"]` (E13 is 83% of Growatt's on-spot volume). No live client config
is edited — `[]` (no filter) is correct for the current clients. The client-config
form shows per-declaration-type BCCT row counts next to the eligible-types field, and
saving a list that would exclude a type present in the client's data raises a
non-blocking warning.

## Acceptance criteria

- [ ] `dncx` preset = `["E11","E13","E15"]`; stray non-material E13 lots stay
      harmless (lots participate only when their code matches a BOM line).
- [ ] No live client config is modified; empty list still means no filter.
- [ ] Client-config form shows per-declaration-type BCCT row counts for the client.
- [ ] Save-time warning (non-blocking) when the configured list excludes a type
      present in the client's BCCT data.
- [ ] The per-supplier/per-type BCCT aggregation sweep is shared with the ticket 06
      curation screen (whichever lands first builds it; the other reuses it).

## Blocked by

None — can start immediately. Coordinate the shared BCCT aggregation helper with
ticket 06 if both are in flight.
