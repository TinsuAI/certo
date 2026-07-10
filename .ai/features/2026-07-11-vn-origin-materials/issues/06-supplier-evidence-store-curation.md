# 06 — Supplier evidence store + curation screen + flip flow

Status: ready-for-agent — tracked on GitHub: [TinsuAI/co#11](https://github.com/TinsuAI/co/issues/11) (tracker of record)

## Parent

`.ai/features/2026-07-11-vn-origin-materials/spec.md` (build-order ticket 5).

## What to build

Staff curate, per client, which suppliers (NCC) have provided origin evidence. A new
append-only Postgres table via the standard migration chain:
`co_supplier_evidence_events(client_id, supplier_key, supplier_name, action on|off,
evidence_kind phu_luc_x|co_import, actor_id, actor_email, note, created_at)`.
Current state = latest event per `(client_id, supplier_key)`; the table is itself the
flip log (no update/delete path). Follow the existing CO events-store precedent for
DB/file-mode behaviour. `doc_no`/`doc_date` are deliberately absent (deferred by user
directive; additive migration later).

A new per-client curation screen lists every BCCT supplier — derived live, with row
counts, origin mix, and current flag — and lets any authenticated operator flip the
flag with an evidence kind. ON→OFF requires an explicit confirm rendering the
computed damage list (locked sheets whose snapshots counted this supplier's rows as
originating: case, sheet, originating amount — computed from the `supplier_key`
materialized by ticket 01, no new persistence). OFF→ON shows an info note ("N locked
sheets could benefit — mở chốt + Tính lại"). Actor comes from the DH JWT.

Day-one use: staff flag Growatt's two NCC (Mingjie VN, Minghui VN) through this
screen — no seed script. Confirm exact `consignee_name` spellings against BCCT while
building (query recorded in the knowledge addendum). `MINGJIE INDUSTRIAL (HK)
LIMITED` is a different legal entity and must stay unflagged — no name auto-merge.

## Acceptance criteria

- [ ] Migration creates the append-only events table; current-state read = latest
      event per `(client_id, supplier_key)`; no update/delete path exists.
- [ ] Curation screen lists BCCT suppliers live with row counts, per-origin mix, and
      current flag; flip control records `evidence_kind` (`phu_luc_x` | `co_import`).
- [ ] ON→OFF flip requires a confirm showing the damage list (case, sheet,
      originating amount) computed from locked snapshots; cancelling writes nothing.
- [ ] OFF→ON flip shows the could-benefit info note.
- [ ] Every flip event stores actor id/email from the DH JWT plus direction,
      evidence kind, and timestamp.
- [ ] The shared whitespace-only normalization function (from ticket 01) is used on
      both the write key and any read; two suppliers with similar names stay
      distinct entries (HK-namesake test).
- [ ] Flipping a flag alone never modifies any sheet, locked or not (resolution
      happens only at Tính — ticket 07).
- [ ] `doc_no`/`doc_date` fields absent by design.

## Blocked by

- 01 — Plumb lot origin fields into sheet materials at Tính
