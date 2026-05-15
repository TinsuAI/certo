# Notes for CO — declaration file status API + bulk ZIP download

**Provider:** Data Hub  ·  **Consumers:** CO  ·  **Date:** 2026-05-15

Posted in response to CO API request
`barry-CO-main/.ai/api-requests/2026-05-15-declaration-file-status.md`.

## What changed in Data Hub

Two routes shipped:

### 1. Bearer-aware summary (server-to-server)

```
GET /v1/hub/clients/{client_id}/declarations
```

Per-declaration summary with `file_count` from
`hub.customs_declaration_files`. BCCT row presence does NOT imply
declaration-file presence — this endpoint answers the file question.

Identity: `(client_id, declaration_no, direction)`. Same declaration
number in both directions ships as two distinct rows.

Query params:
- `direction` (optional, `import` / `export`).
- `declaration_nos` (optional, comma-separated, max 500). Exact-match
  on the canonical declaration_no string; preserves case + format.
  When provided, response is single-page with `next_cursor=null`.
- `has_files` (optional, `yes` / `no`).
- `cursor`, `limit` (default 200, max 500).

Response:

```json
{
  "items": [
    {
      "declaration_no": "308449399330",
      "direction": "export",
      "bcct_line_count": 2,
      "file_count": 1,
      "earliest_bcct_date": "2026-04-21"
    }
  ],
  "next_cursor": null
}
```

Auth: user JWT or service token with `hub:read` scope, `client_ids`
whitelist enforced.

Errors:
- `400 invalid_direction` / `400 invalid_has_files` / `400 too many
  declaration_nos`.
- `401 bearer token required` (strict mode).
- `403 forbidden` (scope or whitelist).
- `404 Client not found`.

### 2. Operator ZIP download (cookie-session, browser)

```
GET /clients/{client_id}/declarations/download.zip
    ?direction=<import|export>
    &declaration_nos=<comma-separated>
    &filename=<suggested-archive-name>
```

Operator clicks → archive contains every uploaded file plus a
`DANH_SACH_TO_KHAI.txt` manifest. Cookie-session auth so the operator's
Data Hub login is reused; CO surfaces the link in the TKX/TKN tab and
the browser carries the cookie.

Archive shape (frozen by contract):

- Files at archive root (no per-declaration subfolders). Operator drags
  them straight into a dossier folder.
- Duplicate `original_filename` values are dedupe-suffixed `_1`, `_2`,
  `_3` … so neither file overwrites the other.
- `DANH_SACH_TO_KHAI.txt` (plain text, UTF-8, Vietnamese) lists every
  requested declaration grouped by status ("Đã có file" /
  "Thiếu file") with per-file in-archive filenames.
- When zero files match: archive still ships with manifest plus
  `NO_FILES_FOUND.txt` marker — operator gets a well-formed download,
  not an HTTP error.

Behaviors:
- Unauthenticated callers → `303` to
  `/login?next=<original URL>` so the operator lands back on the
  download after sign-in.
- `direction` and `declaration_nos` are both required → `400` if
  missing or invalid.
- `filename` is optional. The server sanitizes it (strips path
  separators, control chars, `..` patterns; appends `.zip` if missing;
  caps length to 120 chars); falls back to `declarations.zip` if the
  cleaned form is empty.

## What CO needs to do

### `app/data_hub_client.py` adapter

Per the CO API request:

```python
def list_declarations(
    self, client_id: str, *,
    direction: str | None = None,
    declaration_nos: list[str] | None = None,
) -> list[dict]:
    params = {}
    if direction is not None:
        params["direction"] = direction
    if declaration_nos:
        params["declaration_nos"] = ",".join(declaration_nos)
    return self._get(
        f"/v1/hub/clients/{client_id}/declarations",
        params=params,
    )["items"]
```

`declaration_nos` is what you want when CO already knows the candidate
set per shipment (TKX export + TKN imports). The endpoint returns
single-page in that mode, so CO does not need to paginate. Cap your
request at 500 declarations per call — that matches Data Hub's
server-side cap.

### Call sites mentioned in the API request

- `DataHubPortfolioService.co_case_source_context()` →
  `source_context["declaration_file_counts"]`.
- `case_tkx_tkn_summary()` already accepts `declaration_file_counts`;
  pass it through so `in_data_hub` reflects file presence, not BCCT
  presence.
- `export_co_case_dossier_zip()` → use the same context for
  `tkx-tkn.json`.

### Filename pattern for the ZIP route

CO is expected to generate links like:

- Export bundle for the shipment:
  `TKX_<shipment_export_declaration_no>.zip`
- Import bundle for the shipment:
  `TKN_CO_<shipment_export_declaration_no>.ZIP`

Pass that string in the `filename=` query param; Data Hub uses it as
the Content-Disposition filename after sanitization.

## Auth setup

Same `hub:read` service token pattern as the existing Bearer
endpoints. If CO already uses `hub:read` for the substitute lookup
shipped 2026-05-13, no token change is needed — the same token works
on the new endpoint as long as the client is in its whitelist (or the
token has no whitelist).

## Provider-side tests

- `tests/test_declarations_api_v1_hub.py` — 17 tests covering the
  Bearer endpoint contract.
- `tests/test_declarations_download_zip.py` — 12 tests covering the
  ZIP route contract.

Both pass on `main` at the commit that ships these changes.

## What CO should NOT do

- Don't use `GET /api/v1/clients/{c}/declarations` (the existing
  cookie-only route). It still exists for the in-app declarations
  index page; it returns `401 login required` to Bearer callers.
- Don't try to derive file presence from `/v1/hub/bcct` — BCCT row
  count and uploaded-file count are independent signals.
- Don't pass huge declaration_nos lists. 500 is the hard cap; that
  should comfortably cover the largest TKN bundle a single C/O case
  references.

## Status / next steps

- Data Hub side shipped + tested + documented.
- Awaiting CO consumer PR + tests as specified in the original API
  request file.
- After CO ships, this endpoint joins the C.1 sister-app coordination
  cluster (no further action required from Data Hub).
