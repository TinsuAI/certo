# Data Hub Agent Knowledge

This folder is the only document source searched by the Chat Agent `search_knowledge_base` tool.

The folder is intentionally curated for user-facing support. Do not put internal AI handoff notes, private strategy notes, credentials, deployment targets, or `.ai/*` session content here.

## Product

Data Hub is the master records application for agency source records:
- DNCX/client directory.
- BCCT customs declaration rows.
- Material and product catalog records.
- BOM versions and BOM change proposals.
- BQD/code mappings.

BCQT-System and CO-System consume Data Hub through HTTP APIs. They must not write directly to the `hub` Postgres schema.

## Source Records

Source records are the shared HQ-data tier owned by Data Hub. Examples:
- BCCT rows uploaded from customs declaration spreadsheets.
- Danh Mục material/product rows.
- BOM versions.
- Code mappings.

CO owns certificate workflow state. BCQT owns settlement workflow state. Shared source records stay in Data Hub.

## API Contract

The current consumer API contract is documented at `docs/API_CONTRACT.md`.

Key rules:
- Read routes require bearer auth.
- BOM proposal submission requires a valid Data Hub JWT.
- CO BOM proposals for `modified_for_case` must include `parent_version_id`.
- `co-config` declaration-type filters are currently marked `unconfigured`.
- `source-summary.co_stock_row_count` is raw import row count, not usable CO stock.

## Auth

Data Hub issues JWTs through `/v1/auth/token` and browser SSO through `/v1/auth/authorize` plus `/v1/auth/exchange`.

Consumers should verify JWT signatures locally using `/v1/auth/jwks`.

## Roles

Roles are:
- `dev`: vendor technical role.
- `admin`: agency-wide admin.
- `manager`: scoped manager for assigned clients.
- `staff`: per-client staff user with read or edit access.

Client ACL is always enforced by Data Hub on `/v1/hub/*` requests.
