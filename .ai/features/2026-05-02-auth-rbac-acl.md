# Feature: Auth RBAC + per-client ACL (Phase 1 — local, pre-SSO)

**Date:** 2026-05-02
**Status:** Draft → ready to implement
**Scope:** Data Hub only. Cross-app SSO (BCQT/CO consumers) deferred to M9 SSO design pass.

## Goal

Replace single-role flat auth with a 4-role hierarchy + per-client ACL so the agency can manage who-does-what before the product touches real customer data.

## Roles (locked)

| Role     | Scope                                                    | Can do                                                                                  |
|----------|----------------------------------------------------------|------------------------------------------------------------------------------------------|
| `dev`    | Tinsu AI vendor — **single user** in deployment          | Everything `admin` can + edit `deployment_config` + edit per-client `code_resolution_mode` post-creation. Bootstrap account. |
| `admin`  | Agency owner — multiple allowed                          | Create/lock users, assign roles (manager/staff), assign managers→client groups, assign staff→client+scope, edit non-technical client config (status/notes/tax_code/bom_proposal_qty_tolerance_pct), full read+edit on every client. |
| `manager`| Scoped to a subset of clients                            | Within their group: assign staff→client+scope, edit non-technical client config, full read+edit. Outside group: nothing visible. |
| `staff`  | Scoped per-client with `read` or `edit`                  | `read`: view assigned client tabs. `edit`: read + upload Excel + row edits + tombstone. Cannot edit client config.        |

**Key invariants:**
- Exactly one `dev` user. Enforced via partial unique index `where role='dev'`.
- Manager group membership is the access boundary — manager cannot list/see clients outside their group.
- Staff scope is per-client. Staff with no `user_client_access` rows sees nothing.

## Schema (migration `008_auth_rbac.sql`)

```sql
-- Tighten role enum.
alter table hub.users drop constraint if exists users_role_check;
alter table hub.users add constraint users_role_check
  check (role in ('dev', 'admin', 'manager', 'staff'));

-- Exactly one dev.
create unique index if not exists uq_users_single_dev
  on hub.users ((1)) where role = 'dev';

-- Manager → client group membership.
create table if not exists hub.user_managed_clients (
  user_id text not null references hub.users(user_id) on delete cascade,
  client_id text not null references hub.clients(client_id) on delete cascade,
  granted_by text not null references hub.users(user_id),
  granted_at timestamptz not null default now(),
  primary key (user_id, client_id)
);
create index if not exists idx_managed_clients_client on hub.user_managed_clients(client_id);

-- Staff → client + scope (read|edit).
create table if not exists hub.user_client_access (
  user_id text not null references hub.users(user_id) on delete cascade,
  client_id text not null references hub.clients(client_id) on delete cascade,
  scope text not null check (scope in ('read', 'edit')),
  granted_by text not null references hub.users(user_id),
  granted_at timestamptz not null default now(),
  primary key (user_id, client_id)
);
create index if not exists idx_client_access_client on hub.user_client_access(client_id);

-- Migrate seed admin → dev (single existing user).
update hub.users set role = 'dev' where email = 'admin@data-hub.local';
```

**Rejected alternatives:**
- Multi-scope per-client (`scopes text[]`) — over-engineering for MVP. Two scopes are enough; refactor when a 3rd appears.
- Letting manager group be derived from "manager-created staff assignments" — implicit boundaries are fragile. Explicit `user_managed_clients` is clearer and queryable.

## Authorization helpers (`app/auth/permissions.py`)

```python
def can_view_client(user, client_id) -> bool: ...
def can_edit_client(user, client_id) -> bool: ...      # row edits, uploads, tombstones
def can_edit_client_config(user, client_id) -> bool:   # tax_code/notes/tolerance/status — non-technical
def can_edit_client_technical(user, client_id) -> bool: # code_resolution_mode — dev only
def can_edit_deployment_config(user) -> bool:           # dev only
def can_manage_users(user) -> bool:                     # admin + dev
def can_manage_managers(user) -> bool:                  # admin + dev (assign manager→clients)
def can_assign_staff_to_client(user, client_id) -> bool: # admin/dev anywhere; manager within group
def visible_clients(user) -> list[str]:                 # client_ids user can see (used for client list filter)
```

Refactor `app/auth.py` → `app/auth/__init__.py` re-exports + `app/auth/permissions.py` for the new module. No router signature changes.

## UI surface (additive)

New pages, all inside `/admin/*` namespace except staff-assignment which is a tab on the client workspace:

1. **`/admin/users`** (admin/dev) — list, create user, set role, deactivate. Form fields: email, display_name, role (dropdown).
2. **`/admin/managers/{user_id}/clients`** (admin/dev) — assign clients to a manager (multi-select).
3. **`/clients/{client_id}/staff`** (manager-of-this-client / admin / dev) — new tab in client workspace. List staff with access; add/remove; toggle scope `read↔edit`.

Login/session flow unchanged. Top-nav adds "Quản trị" link for admin/dev. Settings page (`/clients/{id}/config`) gates `code_resolution_mode` field on `can_edit_client_technical(user, client_id)`.

**Out of scope this phase:**
- Audit log of permission changes (table exists implicitly via `granted_by`/`granted_at` columns; no audit-view UI yet).
- Bulk operations (assign one staff to N clients in one form).
- Soft-delete vs hard-delete users — keep current `status` column toggle.

## Test plan

**Unit (pytest):**
1. `test_role_check_constraint` — insert with role='foo' rejected.
2. `test_single_dev_invariant` — second dev insert violates partial unique index.
3. `test_can_view_client_dev` — dev sees all.
4. `test_can_view_client_admin` — admin sees all.
5. `test_can_view_client_manager_in_group` — manager sees clients in `user_managed_clients`.
6. `test_can_view_client_manager_out_of_group` — manager does NOT see other clients.
7. `test_can_view_client_staff_with_access` — staff with row in `user_client_access` sees that client.
8. `test_can_edit_client_staff_read_scope` — staff with scope='read' returns False.
9. `test_can_edit_client_staff_edit_scope` — staff with scope='edit' returns True.
10. `test_visible_clients_filters_correctly` — for each role, returns expected set.
11. `test_can_edit_deployment_config` — only dev returns True.
12. `test_seed_admin_migrated_to_dev` — after migration, seed `admin@data-hub.local` has role='dev'.

**Manual end-to-end (Playwright optional):**
- Login as dev → see /admin/users, can create admin Bob, manager Carol, staff Dave.
- Admin Bob → assigns Carol as manager of Growatt VN; assigns Dave to Johnson VN with edit.
- Manager Carol → only sees Growatt VN in client list. Adds staff Eve to Growatt VN with read scope.
- Staff Dave → sees only Johnson VN. Can upload Excel. Cannot see Growatt.
- Staff Eve (read on Growatt) → sees Growatt tabs but upload buttons disabled / 403 on POST.

## Done criteria

- [ ] Migration 008 applies cleanly on fresh DB + on existing DB with seed admin.
- [ ] Seed admin auto-migrated to `role='dev'`.
- [ ] All 12 unit tests pass; total pytest count = 28 + 12 = 40+.
- [ ] /admin/users + /admin/managers/{id}/clients + /clients/{id}/staff render and function for the role each is gated to.
- [ ] Existing routes wired through new permission helpers; staff-with-read on a client cannot POST.
- [ ] No regressions in existing 28 tests, 27 screenshots still pass.
- [ ] Existing seed data (Growatt + Johnson) still loads without auth errors.
- [ ] STATUS.md updated; session summary written.

## Phase 2 (deferred — not this work)

- JWT issuer + JWKS for cross-app SSO (BCQT/CO consume tokens).
- Cookie-domain federation across 3 apps on shared deployment.
- Audit log UI for permission changes.
- Service account tokens for CO → Data Hub BOM proposal API (currently any-bearer-token).
- Password reset flow + invite email + 2FA.
- Soft-delete + tombstone of user accounts with reassignment rules.

## Open follow-ups recorded for next session

- When BCQT/CO audits land (post M9 discovery), revisit JWT shape for shared SSO.
- Decide if manager can promote staff to manager (currently no — only admin/dev can).
- Decide if "edit" scope grants approve_proposal action when manual mode lands in phase 2.
