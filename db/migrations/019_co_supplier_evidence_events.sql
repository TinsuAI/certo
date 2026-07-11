-- Supplier origin-evidence flags (VN-origin ticket #11, ADR 2026-07-11).
--
-- One APPEND-ONLY event per flip of a supplier's evidence flag: the table is
-- itself the audit log a customs verification years later reconstructs the
-- agency's knowledge from. Current state = the latest event per
-- (client_id, supplier_key). No update/delete path exists by design.
--
-- supplier_key is the whitespace-only normalization of the BCCT
-- consignee_name (app/supplier_identity.py) — the SAME function on the
-- curation write path and the Tính read path, or flags silently stop
-- matching rows. No branch/parent auto-merge: the same real supplier under
-- two spellings is two rows, flagged explicitly.
--
-- doc_no/doc_date are deliberately absent (deferred by user directive;
-- additive migration later). Until then bảng kê column (12) composes
-- "Phụ lục X/<NCC>" from evidence_kind + supplier name and (13) stays blank
-- with a non-blocking warning at Tính.

create table if not exists co_supplier_evidence_events (
  event_id text primary key,
  client_id text not null,
  supplier_key text not null,
  supplier_name text not null default '',
  action text not null check (action in ('on', 'off')),
  evidence_kind text not null check (evidence_kind in ('phu_luc_x', 'co_import')),
  actor_id text not null default '',
  actor_email text not null default '',
  note text not null default '',
  created_at timestamptz not null default now()
);

create index if not exists co_supplier_evidence_events_client_key_idx
  on co_supplier_evidence_events (client_id, supplier_key, created_at desc);
