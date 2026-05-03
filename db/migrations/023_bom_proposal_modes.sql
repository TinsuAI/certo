-- Phase 2 unblock: enable manual + hybrid BOM proposal review modes.
--
-- Until now, hub.clients.bom_proposal_mode was free-form text defaulting
-- to 'auto'. Add a check constraint pinning the allowed set; introduce a
-- per-client `bom_approver_tier` so each agency can decide who is allowed
-- to approve / reject pending proposals.
--
-- Mode semantics (handled in app/stores/bom.py::submit_proposal):
--   auto    — auto-rule decides synchronously (existing behavior).
--   manual  — every proposal lands in 'pending'; reviewer must act.
--   hybrid  — auto-rule approves clean proposals; rule rejections fall
--             through to 'pending' (with failed_conditions) for override.
--
-- Approver tiers (handled in app/auth/permissions.py::can_approve_proposal):
--   edit    — anyone with edit access on the client (default).
--   manager — managers + admin/dev only.
--   admin   — admin / dev only.

alter table hub.clients
  add constraint chk_bom_proposal_mode
  check (bom_proposal_mode in ('auto', 'manual', 'hybrid'));

alter table hub.clients
  add column if not exists bom_approver_tier text not null default 'edit';

alter table hub.clients
  add constraint chk_bom_approver_tier
  check (bom_approver_tier in ('edit', 'manager', 'admin'));
