# Session 2026-07-11/12 (overnight) — VN-origin feature: all 8 tickets implemented

Autonomous overnight run (user directive: "tự chạy lần lượt cho hết ticket").
All 8 GitHub tickets (TinsuAI/co #6–#13) implemented, tested, reviewed, committed
to local `main`, and closed on GitHub with result comments. **NOTHING pushed.**

## Commits (local `main`, on top of 4559c3d)

| Commit | Ticket | Content |
|---|---|---|
| 3fc3112 | #6 | Plumb `origin_country`/`consignee_name`/`supplier_key` into allocation lines + sheet materials at Tính; column (9) stops being blank; shared `app/supplier_identity.supplier_key` |
| 7cf73a6 | #8 | Shortage three-belt guard (`lvc_allocation_shortage`); fallback-price path removed; document-remedy copy; missing_price branches untouched |
| c9e678d | #7 | Override re-key → `material_sequence` (legacy migration idempotent via `override_key_scheme`), version-aware binding (`writable_overrides` closes the rebind hole), render-split fan-out `app/bang_ke_rows.py` wired into 3 renderers + web split rows |
| 8c8dd57 | #13 | dncx preset +E13; config form per-type BCCT counts + non-blocking exclusion warning; shared `app/bcct_aggregates.py` |
| ea710a6 | #9 | `app/origin_country.py` (raw→ISO→VN, unknown bucket, pure `column9_text`); materialization at all 4 Tính build exits; renderers/web = pure readers; config form mode+label+read-only mapping |
| 928bcf2 | #10 | Per-case mode override control + flip lifecycle (stale/chip/never-touch-locked); materializer SKIPS locked sheets (review catch); belts re-check the mode stamp |
| 546850e | #11 | Migration 019 `co_supplier_evidence_events` (append-only); store (loud 503 without DB); curation screen `/clients/{id}/suppliers`; ON→OFF damage-list confirm, OFF→ON benefit list |
| (pending) | #12 | Per-row VN resolver: line originating iff lot VN AND supplier flagged; originating AMOUNT; VNM shrinks exactly; (12) "Phụ lục X/<NCC>"; zero-flag byte-identical |

Suite progression: 757 → 879 passed (122 new tests), 13-14 skipped (DB-gated),
file-mode. Full suite ran green after every ticket.

## Review process

Per-ticket two-axis review (standards + spec sub-agents). Real catches folded in:
- #8: no-lot material tripped `lvc_missing_price` → the pre-action reason said
  "bổ sung đơn giá" instead of the document remedy → shortage reason now takes
  precedence; no-lot line classifies `partial_allocation`, not `missing_unit_value`.
- #7: version-gate write-bypass — writers merged into the kept map and restamped it
  with the current artifact id (silently rebinding version-A overrides to B) →
  `writable_overrides` starts empty on mismatch + drops undo stacks.
- #10: the Tính materializer re-stamped LOCKED sheets on any other sheet's Tính
  (whole-case persist) → silently rewrote as-filed column-9 text → locked skip.

## Decisions taken during build (within ADR bounds)

- `bang_ke` client settings live on the CO-side client overlay
  (`client["bang_ke_overrides"]`, precedent `co_stock_overrides`) — NOT in the
  DH-owned client_config — so they stay editable when DH source-mode makes the
  source config read-only. Read-time defaults instead of a config migration.
- Evidence store refuses loudly (503) without a DB instead of the events-store
  silent no-op: a silently dropped evidence flag would understate RVC forever.
- Fan-out identity fast-path only when the single group's key equals the
  material's own key — a fully-qualifying line renders as ONE part carrying
  origin status + evidence text.
- Material-level `supplier_key`/`consignee_name`/`origin_country` are
  ", "-joined distinct views; the per-line values are the true identities (the
  damage list and resolver read lines, never the joined strings).
- XML renderer's (12) stopped leaking `source_document_ref` (internal ref, not
  origin evidence) — behavior change for filed-XML re-exports, deliberate.

## What didn't work / gotchas

- Standalone (non-pytest) TestClient scripts against the repo run into the
  PERSISTED `data/local` growatt BCCT snapshot (June, has a `NK-DBG` lot for
  DEMO-NPL-001 with no origin/consignee). Stock candidates sort by declaration_no,
  so e2e test lots must sort BEFORE `NK-DBG` (used `NK-AAA-*`) or the stale lot
  absorbs the allocation.
- The origin page GET rebuilds products from the source context, so hand-seeded
  per-line fields never render — web-grid split e2e must go through a real
  upload→Tính (done in #9's country-mode split test).
- Review sub-agents sometimes stall >5 min; SendMessage "finalize now" unblocks.

## Deploy-day manual steps (NOT code)

1. growatt-vn: verify exact `consignee_name` spellings against live BCCT, then flag
   `CONG TY TNHH MINGJIE VIET NAM` + `CONG TY TNHH MINGHUI VIET NAM` via
   `/clients/growatt-vn/suppliers`. NEVER flag `MINGJIE INDUSTRIAL (HK) LIMITED`.
2. Johnson: zero flags (their all-VNM treatment is legally correct).
3. Migration 019 applies automatically (apply_migrations at boot); verified against
   local Postgres.
4. Watch: first Tính after deploy materializes column (9) on re-calculated sheets;
   locked pre-feature sheets stay blank until reopened (by design).

## Open items

- Push the 9 commits when the user wants them on origin (push triggers prod CD —
  user approval per guardrail).
- Standing non-ticket action items (unchanged): audit already-locked SHORTAGE
  sheets in prod (legal exposure — now that shortage BLOCKS, existing locked
  shortage sheets are the remaining stock); deliberate resolution of the
  `missing_price` one-belt hole.
- Known minor gaps (documented in review reports, accepted): CTC/tariff-shift
  preview still counts fully-qualifying materials' HS in the non-origin list
  (material-level status stays conservative); mixed-currency materials carry
  origin_amount but VNM stays unadjusted (such sheets are lock-blocked anyway);
  client-default mode flip confirm states consequences without exact counts.
- BACKLOG FX1 (Form X missing in co_forms.py) untouched; phase-2 in-bloc deferred.
