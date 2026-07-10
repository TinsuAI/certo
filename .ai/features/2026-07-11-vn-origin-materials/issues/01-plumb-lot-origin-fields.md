# 01 — Plumb lot origin fields into sheet materials at Tính

Status: ready-for-agent — tracked on GitHub: [TinsuAI/co#6](https://github.com/TinsuAI/co/issues/6) (tracker of record)

## Parent

`.ai/features/2026-07-11-vn-origin-materials/spec.md` (build-order ticket 1).

## What to build

After Tính, every material row backed by allocation lines carries the lot's country
of origin and supplier: `origin_country` and `consignee_name` copied from the lot's
BCCT data onto each allocation line and up to the sheet material, plus a materialized
`supplier_key` (whitespace-only normalization of `consignee_name` — this ticket
introduces the shared normalization function that ticket 06 reuses). The values are
persisted in the sheet snapshot, so locked sheets become self-contained for the later
damage-list computation.

Visible result: column (9) (nước xuất xứ) stops being blank on the web grid and all
three export formats — the renderers already read `origin_country`; today the value
never reaches them. Interim rendering is the raw BCCT string (VIETNAM, CHINA, …),
same as the agency's macro emits before hand-correction; Vietnamese display names and
modes arrive with ticket 04.

## Acceptance criteria

- [ ] Each allocation line carries `origin_country` and `consignee_name` from its lot.
- [ ] Each sheet material materializes `supplier_key` via a single shared, code-owned,
      whitespace-only normalization function (unit-tested; reused by ticket 06).
- [ ] Column (9) shows the raw lot country string on the web grid and all three
      exports for a freshly calculated sheet (was blank in prod).
- [ ] A line whose lots disagree on country surfaces all distinct countries (interim,
      until the ticket 02/04 split machinery renders them as separate rows) — never
      silently shows only one.
- [ ] The new fields land in the persisted sheet snapshot; previously persisted sheets
      keep loading with empty values until their next Tính (no backfill).
- [ ] Full file-mode suite green; no behaviour change beyond the new fields and the
      column (9) fill.

## Blocked by

None — can start immediately.
