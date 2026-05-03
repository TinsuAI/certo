# Feature: BOM proposal modes — manual + hybrid + configurable approver tier

**Date:** 2026-05-03 (PM)
**Status:** shipped (uncommitted)
**Trigger:** Phase-2 unblock from BACKLOG. MVP shipped auto-only; this
adds the deferred manual + hybrid review modes the proposal queue was
already scaffolded for.

## Scope

- **Modes** (`hub.clients.bom_proposal_mode`):
  - `auto` — auto-rule decides synchronously (existing behaviour).
  - `manual` — every proposal lands in `pending`; reviewer must act.
  - `hybrid` — auto-rule approves clean proposals; rule rejections fall
    through to `pending` with `failed_conditions` for override.
- **Approver tier** (`hub.clients.bom_approver_tier`, configurable
  per-client): `edit` (default) / `manager` / `admin`. Maps to existing
  permission helpers — no new RBAC roles.
- **Reviewer actions:** approve / reject / withdraw on pending
  proposals. Approve materialises a new BOM version inheriting the
  proposal's `actor` + `intent` + `parent_version_id`.
- **Service-token withdraw:** `/v1/hub/proposals/{id}/withdraw` lets
  CO rescind its own pending proposals via `bom:propose` scope.
- **UI:** `/clients/{cid}/edit` exposes both dropdowns;
  `/clients/{cid}/proposals` sorts pending first + new chip filters;
  `/clients/{cid}/proposals/{pid}` renders inline review form when
  status=pending and user has approver permission.

## Out of scope (explicit)

- "Approve with edits" (reviewer modifying rows before approval).
  Decision: reviewer asks submitter to resubmit. Resubmission of the
  same canonical key while pending returns the existing pending
  (idempotent); resubmission after `withdrawn` creates fresh.
- Notification preferences. Pending notifications fan out to every
  edit-scope user via existing `notify_many` helper. No per-user
  opt-out yet.
- Bulk approve. Reviewer acts one-by-one.

## Files changed

```
db/migrations/023_bom_proposal_modes.sql       new
app/stores/bom.py                              + 220 lines (mode dispatch + 3 actions)
app/auth/permissions.py                        + can_approve_proposal helper
app/auth/__init__.py                           + exports
app/routes/proposals.py                        rewrite (HTML actions)
app/routes/clients.py                          + tier field, validation
app/routes/api.py                              + /v1/hub/proposals/{id}/withdraw, dev kill-switch
app/main.py                                    + DATA_HUB_API_AUTH_DISABLED warning
app/seed.py                                    + bom_approver_tier
app/templates/clients/edit.html                + tier dropdown, mode labels
app/templates/clients/proposals.html           rewrite (sort pending first)
app/templates/clients/proposal_detail.html     + review callout
app/i18n.py                                    + 20 keys (vi/en)
tests/test_bom_proposal_modes.py               new (16 tests)
tests/test_read_api_auth.py                    + 2 tests for kill-switch
tests/test_provenance.py                       fix `auto_only` → `auto`
tests/test_client_config.py                    fix `auto_only` → `auto`
```

## Manual test plan

Done via `/tmp/dh_ui_smoke.py` (Playwright) + dev server on 8754. Steps:

1. Visit `/clients/growatt-vn/edit` → confirm 3-option mode dropdown +
   3-option approver-tier dropdown render. **Screenshot:**
   `screenshots/01_edit_form.png`
2. Switch mode to `manual` → save → reload edit page, confirm persisted.
3. Submit a proposal via `POST /v1/hub/products/INV-3000/bom/proposals`
   with auth disabled (`DATA_HUB_API_AUTH_DISABLED=1`) → expect
   `status=pending`.
4. Visit `/clients/growatt-vn/proposals` → pending row sorts first;
   new "chờ duyệt" chip with count. **Screenshot:**
   `screenshots/04_proposals_list_pending.png`
5. Open the pending proposal detail → review callout shows Approve
   button + Reject form + Withdraw button. **Screenshot:**
   `screenshots/05_proposal_pending_with_review.png`
6. Click Approve with note → redirects back to detail; status badge
   = "đã duyệt"; review callout gone; metadata populated;
   `materialized_version_id` set. **Screenshot:**
   `screenshots/06_proposal_approved.png`
7. Switch mode back to `auto` for clean state.

Re-run anytime with: `uv run python /tmp/dh_ui_smoke.py`.

## Done criteria

- [x] 16 new unit tests pass + 307 baseline still passes (325 total).
- [x] Migration 023 applied cleanly; check constraints active.
- [x] Approve / reject / withdraw store actions raise
  `ProposalNotPending` on already-decided proposals.
- [x] Idempotency excludes `withdrawn` so resubmit-after-withdraw
  creates new proposal.
- [x] Service-token withdraw endpoint requires `bom:propose` scope +
  client whitelist; returns 409 on already-decided.
- [x] UI smoke: 7-step Playwright walkthrough green.
- [x] Approver-tier permission gate honours `edit` / `manager` /
  `admin` choices on real users.
- [ ] Sister-app cutover (CO + BCQT) — not part of this feature; tracked in
  `.ai/sister-app-notes/`.

## Dev convenience: API auth kill-switch

`DATA_HUB_API_AUTH_DISABLED=1` env var → `/v1/hub/*` accepts requests
with no `Authorization` header. Suppressed automatically when
`api_auth_strict=true`. Loud warning at startup. Two regression tests
guard behaviour. Do not set in prod.
