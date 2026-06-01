# Data Hub API Request: BCCT pull `since` filter + tombstones

## Use Case
CO is moving `refresh_co_stock_for_client()` from a destructive
DELETE+INSERT of `co.co_stock_rows` to a diff-based incremental refresh
(`.ai/features/2026-05-28-co-stock-refresh-audit/brief.md` for the rationale).

Even with the local diff logic in place, CO still has to pull the full
BCCT corpus on every refresh because today's adapter is
`GET /v1/hub/bcct?client_id=X` (full set, paginated). On the largest
client (Johnson: ~65k BCCT rows) that pull alone is ~8-10s before any
DB write. Operators currently refresh several times a day during
declaration intake.

What CO needs is a "give me everything that changed since timestamp T"
delta, so a no-op refresh costs ~milliseconds and an after-Data-Hub-import
refresh costs proportional to actual upstream changes.

## Existing Endpoint Gap
- `GET /v1/hub/bcct?client_id=X` returns every published BCCT row for
  the client. No timestamp filter; no deletion semantics.
- `GET /v1/hub/clients/{cid}/bcct/by-codes` filters by item code, not by
  recency, and doesn't expose deletes either.
- No tombstone / deletion notification surface anywhere — when an
  operator corrects/deletes a BCCT row on Data Hub, CO has no way to
  learn it short of full re-pull.

## Proposed Contract
Method and path:
`GET /v1/hub/bcct`

Query parameters (existing + new):
- `client_id`: required (existing).
- `since`: optional ISO-8601 timestamp (UTC). When provided, return only
  BCCT rows whose `indexed_at` (server-side ingestion/update timestamp)
  is strictly greater than `since`. Default behavior unchanged when
  omitted.
- `include_tombstones`: optional boolean, default `false`. When `true`,
  the response includes a `tombstones` array listing transaction_keys
  whose BCCT row was removed since `since`. Only meaningful with `since`.
- `cursor`, `limit`: existing pagination.

Request body:
None.

Response body (compatible with existing shape when `since` is omitted):
```json
{
  "items": [
    {
      "transaction_key": "tk_abc123",
      "client_id": "growatt-vn",
      "direction": "import",
      "declaration_no": "308449399330",
      "registration_date": "2026-04-21",
      "indexed_at": "2026-04-21T10:32:00Z",
      "...": "all existing BCCT row fields"
    }
  ],
  "tombstones": [
    {
      "transaction_key": "tk_xyz789",
      "removed_at": "2026-04-21T09:15:00Z",
      "reason": "operator_delete"
    }
  ],
  "next_cursor": null,
  "server_time": "2026-04-21T10:35:12Z"
}
```

Notes on the shape:
- `tombstones` is omitted when `include_tombstones=false` (back-compat).
- `server_time` is always returned. CO stores it as the "high-water mark"
  for the next call's `since` value — guarantees no gap even if multiple
  rows share an `indexed_at` clock tick.
- Existing callers that ignore unknown response keys (CO already does
  via `_get_all`) continue to work without changes.

Error cases:
- `400 invalid_since` when `since` is not parseable ISO-8601.
- `400 invalid_include_tombstones` when value is not `true`/`false`.
- `401 bearer token required`.
- `403 forbidden` when the token cannot view `client_id`.
- Existing pagination / auth errors unchanged.

## Auth
Required scope:
`hub:read` (same as current `/v1/hub/bcct`).

Client scoping rule:
Service-token `client_ids` whitelist must include `client_id`. User JWT
must carry a claim allowing this client.

Token type:
User JWT or service token (matches current `/v1/hub/bcct`).

## Data Semantics
Source of truth:
`hub.bcct_published_rows` for items; a new
`hub.bcct_published_rows_tombstones` (or equivalent) for tombstones.
Both are emitted by the Data Hub BCCT publish pipeline — `items` on
insert/update, `tombstones` on delete.

Precision requirements:
`since` and `indexed_at` are UTC ISO-8601 with **at least** millisecond
precision. CO uses `server_time` from the previous response as the next
`since`, so server-internal clock skew is handled centrally.

Pagination:
Same `cursor` / `limit` semantics as current endpoint. When combined
with `since`, pagination is over the filtered set. `tombstones` is
returned in full on the first page (its size is bounded by deletions,
which are rare); subsequent pages have `tombstones = []`.

Idempotency:
Read-only, naturally idempotent. Same `(client_id, since)` returns the
same superset across calls (modulo new arrivals since the previous
query — by design).

Versioning or pinning:
Adding `since` + `tombstones` is backward-compatible. CO will gate the
delta path on response carrying `server_time` — if the field is absent,
fall back to full-rebuild. Data Hub may choose to bump the BCCT API
minor version for tracking purposes; not required for CO consumption.

## Tests Required In Data Hub
Provider tests:
- `since` omitted → response shape matches current contract; no
  `tombstones` field.
- `since=<past ts>` → returns rows whose `indexed_at > since`, excludes
  older rows.
- `since=<future ts>` → returns `items: []`, `tombstones: []`,
  `server_time` populated.
- `include_tombstones=true` + `since=<ts>` → `tombstones` contains
  transaction_keys deleted since `since`.
- `include_tombstones=true` without `since` → 400 (deletes since when?
  caller must scope by time).
- Pagination across `since` + `cursor` returns disjoint pages, total
  matches an unpaginated query.

Negative tests:
- Invalid `since` string → 400 `invalid_since`.
- `since` with timezone-naive ISO → 400 (require explicit UTC).
- Token without scope → 403.
- Wrong client_id → 403 (don't leak existence).

Edge cases:
- BCCT row inserted then deleted within the `since` window → appears in
  `tombstones`, not in `items`.
- BCCT row updated multiple times within window → appears once in
  `items` with the latest payload.
- Two refreshes from CO with the same `since` (clock skew safety) →
  both return the same superset; idempotency holds.
- Client has zero BCCT rows ever → `items: []`, `tombstones: []`,
  `server_time` still populated.

## CO Consumer Plan
Adapter method to add in `app/data_hub_client.py`:
```python
def list_bcct(self, client_id: str, *, since: str = "", include_tombstones: bool = False, **query) -> dict:
    """Returns the raw envelope {items, tombstones, server_time, next_cursor}.

    Current `list_bcct` returns `list[dict]` (items only). Promote to
    envelope-returning when Data Hub deploys `since`. Existing callers
    that want just items can do `.get("items", [])`.
    """
    return self._get_all_envelope(
        "/v1/hub/bcct",
        {"client_id": client_id, "since": since, "include_tombstones": "true" if include_tombstones else "", **query},
    )
```

Behavior gate: at startup or first call, CO probes one `/v1/hub/bcct`
response. If it lacks `server_time`, mark `delta_refresh_supported = False`
in a process-local cache and never call with `since` (avoids 400s).

Call sites that will consume the adapter:
- `app/main.py:5473` (`refresh_co_stock_endpoint`) — where the delta
  refresh logic lives.
- `app/portfolio.py:source_workspace` — non-incremental call, switches
  to envelope shape but ignores `tombstones`.
- `app/data_hub_client.py:DataHubBackedPortfolioService.source_workspace`
  — same.

Consumer tests:
- Adapter constructs query with/without `since`; envelope passthrough.
- Refresh logic: config_hash branch — when config_hash differs from
  stored hash, full-pull regardless of `since` support.
- Refresh logic: delta path emits `snapshot_row_added/_removed/_updated`
  events; full path emits a single `snapshot_refresh` event.
- Refresh logic: tombstone with active claim → operator-visible
  warning, source_row NOT removed from snapshot, claim untouched.
- Fallback path when Data Hub returns no `server_time`.

## Prerequisite Confirmation: `transaction_key` stability

CO's diff design hinges on `BCCT_row.transaction_key` being **deterministic
across re-imports** of the same row. Concretely: if a user re-uploads the
same BCCT spreadsheet (or Data Hub re-ingests the same row from any
upstream system), the resulting `transaction_key` MUST be identical to
the previous import's value.

Why this matters:
- CO derives `source_row = "import-row-" + sha1(transaction_key)[:16]`.
- `co.co_stock_rows.source_row` is the PK on the cached snapshot.
- `co.co_stock_claims` references `source_row` (claim ID is derived from
  it). Stable lots = stable claims across refreshes.

If `transaction_key` were random per import (UUID, monotonic counter,
ingestion timestamp, etc.), a re-import would look like "all old rows
deleted + all new rows added" to CO — refresh becomes a flood of
delete-and-recreate events, claims get orphaned, audit log becomes noise.

Verification we need from Data Hub:
1. Document how `transaction_key` is constructed. Likely candidates:
   - Hash of `(client_id, declaration_no, line_no, customs_code,
     sequence_within_line)` — deterministic, ideal.
   - Hash of the full row payload — deterministic but breaks if payload
     is edited.
   - UUID at row creation, persisted across re-imports — deterministic
     once row exists, but only if Data Hub deduplicates on re-import.
   - Random per import — would break this design.
2. Confirm the dedup behavior on re-import: when the same
   `(declaration_no, line_no, customs_code)` appears in a re-uploaded
   file, does Data Hub reuse the existing `transaction_key` or generate
   a new one?
3. If transaction_key is NOT stable, please surface the lot-key tuple
   `(declaration_no, line_no, customs_code)` as a separate stable field
   on the BCCT row payload. CO will diff by lot key instead, and stop
   relying on transaction_key for identity.

Empirical check from CO side (current growatt-vn data, 38,287 stock
rows):
- `transaction_key` → `source_row`: 1:1 (deterministic by sha
  construction — confirmed).
- `(declaration_no, line_no, customs_code)` → `transaction_key`: 1:1
  (no duplicates observed).

This is consistent with `transaction_key` being deterministic in the
current snapshot, but doesn't prove behavior across a re-import. Please
confirm the construction so we can lock the diff design.

## Approval
Data Hub contract owner:
TBD — request needs your sign-off before CO lands `delta_refresh_supported`
detection. The CO-side diff logic (option B) ships independently and
benefits even without this filter (audit events + claim safety on
full-pull). `since` is the speed win on top.

Two decisions needed:
1. `since` + `tombstones` filter on `/v1/hub/bcct` — speed optimization,
   gated behind `server_time` presence in response.
2. `transaction_key` stability statement (above) — correctness
   prerequisite for the diff design. Required even without `since`.

Approval date:

Data Hub commit:
