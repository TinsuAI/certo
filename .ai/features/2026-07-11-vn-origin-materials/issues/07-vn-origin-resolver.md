# 07 — Per-row VN-origin resolver (the feature)

Status: ready-for-agent — tracked on GitHub: [TinsuAI/co#12](https://github.com/TinsuAI/co/issues/12) (tracker of record)

## Parent

`.ai/features/2026-07-11-vn-origin-materials/spec.md` (build-order ticket 6).

## What to build

At Tính, each material row resolves origin: originating iff the lot's
`origin_country` normalizes to VN **AND** the supplier carries a current evidence
flag. Conservative default `non_origin`; the resolver returns an originating
**amount**, not a boolean; resolution is never persisted onto the material outside
the sheet snapshot — re-Tính re-resolves from current flags.

Qualifying value moves to column (7) (trị giá có xuất xứ FTA) and RVC/LVC rise. A
line whose lots resolve to different origins splits into one row per origin via the
ticket 02 machinery, each part keeping merged-declaration behaviour. Qualifying rows
compose column (12) from the evidence kind + supplier name ("Phụ lục X/<NCC>");
column (13) renders blank with a non-blocking warning until document dates exist.
Locked sheets are self-contained: later flips never change them (damage/benefit
surfacing is ticket 06's job).

End-to-end demo: on growatt-vn, flag the two NCC, Tính a sheet consuming their
materials, and see (7)/(9)/(12) correct on the web grid and every export, with RVC
higher than before. A client with zero flags (Johnson) is bit-for-bit unchanged.

## Acceptance criteria

- [ ] Row originating iff `origin_country`→VN AND supplier flagged; resolver returns
      an originating amount per row.
- [ ] AND rule negative cases: flagged supplier + non-VN lot stays non-originating;
      VN lot + unflagged supplier stays non-originating (both tested — 24 of 64
      VN-capable suppliers sell mixed-origin goods).
- [ ] Mixed-origin line splits per resolved origin; parts sum exactly to the line's
      quantity and money; (7)/(8) and LVC reflect exactly the VN portion.
- [ ] Qualifying rows: value in (7), column (12) = composed evidence label, column
      (13) blank + non-blocking warning.
- [ ] Zero-flag client (Johnson): sheet context, exports, and totals byte-identical
      before/after the feature (regression pin).
- [ ] Re-Tính after a flag flip re-resolves; locked sheets keep their snapshot
      unchanged.
- [ ] End-to-end on growatt-vn data: flag Mingjie VN + Minghui VN → Tính → verified
      on web grid and all three exports; RVC increases.

## Blocked by

- 02 — Override identity re-key + render-split fan-out machinery
- 04 — Column (9)/(12)/(13) materialization: modes, normalization, unknown label
- 06 — Supplier evidence store + curation screen + flip flow
