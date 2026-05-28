# BCCT incremental pull — `since` + tombstones available on `/v1/hub/bcct`

**To:** CO repo (`barry-CO-main`)
**From:** Data Hub
**Date:** 2026-05-28
**Request:** `barry-CO-main/.ai/api-requests/2026-05-28-bcct-incremental-since-filter.md`

## Status

Shipped. Endpoint live on demo (`http://100.84.189.87:8754`) and dev
(`http://127.0.0.1:8754`) after the next CI deploy. Provider tests +
API contract + API changelog all updated.

## What's available

`GET /v1/hub/bcct?client_id=<cid>&since=<ISO-8601 UTC>&include_tombstones=true`

- `since` (optional): ISO-8601 UTC timestamp. Returns only rows whose
  `indexed_at > since`. Timezone-naive strings rejected with 400
  `invalid_since`.
- `include_tombstones` (optional, requires `since`): `true` adds a
  `tombstones[]` array sourced from `hub.bcct_row_history` where
  `action='delete' AND changed_at > since`. Each entry has
  `{transaction_key, removed_at, reason}`. Returned in full on the
  first page only; subsequent pages have `tombstones=[]`.
- `server_time` always present in the response (ISO-8601 UTC). Use as
  the next call's `since`.
- Backward compatible: omitting `since` returns the existing shape +
  the new `server_time` field. Existing callers that ignore unknown
  keys continue to work without changes.

Full spec: `docs/API_CONTRACT.md` (search `GET /v1/hub/bcct`).
Changelog: `docs/API_CHANGELOG.md` entry dated 2026-05-28.

## `transaction_key` stability — confirmed

CO's diff design hinges on `transaction_key` being deterministic
across re-imports. Confirmed:

- Construction (`app/parsers/bcct.py:230`):
  - `f"{declaration_no}-{line_no}"` when declaration_no is present
    (the normal case for real customs data).
  - Fallback `f"{customs_code}-{token_hex(4)}"` when declaration_no is
    empty (edge case; should not happen for well-formed BCCT input).
- This means re-uploading the same BCCT spreadsheet yields the same
  `transaction_key` for each row, satisfying the
  `source_row = sha1(transaction_key)[:16]` mapping CO relies on.
- Caveat: if a user edits `declaration_no` or `line_no` on an
  ingested row (BCCT confirm-on-update flow exists), the
  `transaction_key` will change. CO's tombstone-aware diff handles
  this correctly — the old key appears in `tombstones`, the new key
  arrives in `items`.

If CO wants belt-and-suspenders, the `(declaration_no, line_no,
customs_code)` tuple is also stable and exposed on every row payload.
Falling back to that tuple as the identity key requires no Data Hub
change.

## Behavior gate (per the request)

CO's adapter detects support by checking `server_time` presence:

- Response has `server_time` → use `since` on subsequent calls.
- Response lacks `server_time` → fall back to full-pull.

`server_time` is now always present, so once the demo deploy lands
the detection will flip on automatically.

## Auth

Unchanged. Either user JWT or service token. Service tokens still
need `hub:read` scope and a matching `client_ids` whitelist for the
requested `client_id`.

## Empirical smoke (recommended on CO side)

Run a full-baseline pull + immediate `since=<that response's server_time>`
pull on Johnson (~65k rows). The delta call should return zero items
and complete in well under 100ms — that's the speed win from the
request.

## Error cases

- `400 invalid_since` — malformed timestamp or timezone-naive string.
- `400 invalid_include_tombstones` — value other than `true`/`false`.
- `400 include_tombstones_requires_since` — caller asked for
  tombstones without scoping the time window.
- Existing 401/403/404 unchanged.

## Open follow-ups

- If CO observes pagination edge cases under real load (Johnson 65k
  rows over a long `since` window), surface them and we'll add an
  EXPLAIN ANALYZE check + index review on `(client_id, indexed_at)`.
- Tombstone retention: `hub.bcct_row_history` has no TTL today. If
  CO's incremental refresh cadence means stale tombstones accumulate
  indefinitely, we can add a retention sweep later. Not blocking.
