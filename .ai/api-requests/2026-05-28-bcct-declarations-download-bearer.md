# Data Hub API Request: Bearer-aware declarations download

## Use Case
CO is redesigning the "Review & Xuất" step (step 6) to produce a single
self-contained dossier ZIP that contains everything an operator needs
to file with HQ:

- Bảng kê C/O xlsx
- All uploaded supporting chứng từ (already inside CO state)
- **All related TKX (export) and TKN (import) declaration files,
  consolidated and sorted by declaration_no**
- Sensible filenames

Today, the operator downloads TKX/TKN files via
`/clients/{cid}/declarations/download.zip` from their browser
(cookie-session route). CO server can't fetch those files because the
download endpoint is cookie-only — the docstring even says so. So
the consolidated dossier ZIP can't include the declaration files
themselves, only manifest links — which forces the operator to do a
second manual step.

We need a Bearer/service-token-aware variant that CO can call
server-side using the operator's JWT (forwarded through CO).

## Existing Endpoint Gap

- `GET /clients/{client_id}/declarations/download.zip` — cookie-session
  only. `auth.current_user(request)` returns None for Bearer callers
  and 303 redirects to `/login?next=...`. Not usable from CO server.
- `GET /v1/hub/clients/{client_id}/declarations` — Bearer-aware, but
  returns metadata (file_count, earliest_bcct_date), no actual file
  bytes.
- No other Bearer surface for the customs file blobs.

## Proposed Contract
Method and path:
`GET /v1/hub/clients/{client_id}/declarations/download.zip`

Query parameters (mirror the cookie route exactly so CO can reuse the
same query-builder logic):
- `direction`: required — `import` or `export`.
- `declaration_nos`: required — comma-separated list of declaration
  numbers, max ~500 entries per call.
- `filename`: optional — preferred archive filename in the
  `Content-Disposition` header. When omitted, default to
  `declarations_{client_id}_{direction}.zip`.

Response:
- `200` — ZIP archive (the same bytes the cookie route returns today).
  Headers identical to the existing route: `Content-Type:
  application/zip`, `Content-Disposition: attachment; filename="..."`.
  Body layout matches the existing one:
  - All declaration files at the archive root (de-duplicated with
    `_1` / `_2` suffix on filename collision).
  - `DANH_SACH_TO_KHAI.txt` manifest listing each requested
    declaration_no + status + included filenames.
  - When zero files match, a well-formed ZIP with the manifest +
    `NO_FILES_FOUND.txt` marker.

Error cases:
- `400 invalid_direction` — direction not `import`/`export`.
- `400 declaration_nos_required` — empty/missing.
- `400 too_many_declaration_nos` — > 500.
- `401 bearer token required` — auth missing or invalid.
- `403 forbidden` — token can't view the client.
- `404 client not found`.

## Auth
Required scope:
`hub:read` (same scope as the rest of the BCCT/declaration metadata
APIs).

Client scoping rule:
Service-token `client_ids` whitelist must include `{client_id}`.
User JWT must carry a claim allowing this client (CO will forward the
operator's JWT via `Authorization: Bearer …` — that's how CO talks to
the rest of the `/v1/hub/...` surface today).

Token type:
User JWT (preferred — the operator's identity carries through audit)
OR service token (for unattended pipelines, if anyone needs that
later). Cookie-only is intentionally NOT in scope here; the existing
operator-browser route stays alongside.

## Data Semantics
Source of truth:
Same `hub.customs_declaration_files` table the cookie route reads.
Same row selection logic (`(client_id, direction, declaration_no IN
nos)`).

Precision requirements:
N/A — file blobs are passed through.

Pagination:
None. Single response carries the full archive. The cookie route
already streams this way for the same `declaration_nos` cap of 500;
behavior is identical.

Idempotency:
Read-only, naturally idempotent.

Versioning or pinning:
New URL path; no version conflict. CO will detect support by trying
the Bearer URL first and falling back to embedding manifest links
when the call returns 404 (deployment on old contract).

## Tests Required In Data Hub
Provider tests:
- Bearer token with `hub:read` + matching client_id → 200 ZIP with the
  same bytes as the cookie route would return for the same params.
- Bearer token with wrong client_id → 403.
- Missing Bearer → 401.
- Service token (admin) → 200.
- `direction` outside import/export → 400.
- `declaration_nos` empty → 400.
- `declaration_nos` > 500 → 400.
- Zero-match case → 200 with manifest + NO_FILES_FOUND.txt.
- Single declaration → 200, archive contains only that declaration's
  files.

Negative tests:
- File-storage path traversal attempts in declaration_nos → rejected.
- Concurrent calls for the same client/declaration set → consistent
  bytes (no race on the streaming).

Edge cases:
- Declaration referenced in `bcct_published_rows` but no file uploaded
  yet → manifest lists it as `Thiếu`, NO_FILES_FOUND marker not
  triggered for the overall archive.
- Declaration files larger than the runtime memory limit → response
  must stream (cookie route already does this).

## CO Consumer Plan
Adapter method to add in `app/data_hub_client.py`:
```python
def download_declarations_zip(
    self,
    client_id: str,
    *,
    direction: str,
    declaration_nos: list[str],
    filename: str = "",
) -> bytes:
    """Returns the raw ZIP bytes for inclusion in CO's dossier export.
    Raises httpx.HTTPStatusError on non-200; the dossier builder falls
    back to manifest-only mode (existing path) when Data Hub doesn't
    yet expose this endpoint.
    """
    path = f"/v1/hub/clients/{hub_path_part(client_id)}/declarations/download.zip"
    params = {
        "direction": direction,
        "declaration_nos": ",".join((declaration_nos or [])[:500]),
        "filename": filename or "",
    }
    response = self._client.get(path, params=params, headers=self._auth_headers())
    response.raise_for_status()
    return response.content
```

Call sites that will consume the adapter:
- `app/workbook_io.py:create_dossier_zip` — splice TKX bytes into
  `tkx-tkn/exports/...` and TKN bytes into `tkx-tkn/imports/...`.
- `app/main.py:/clients/{cid}/co-case/{cid}/export-dossier-zip`
  endpoint — passes the operator's resolved declaration_nos.

Consumer tests:
- Adapter constructs the path + query.
- Dossier builder reads the bytes and re-packs into the consolidated
  archive.
- Dossier builder falls back to manifest-only when Data Hub raises
  404 (old deployment).

## Approval
Data Hub contract owner:
TBD — request needs your sign-off before CO ships the consolidated
dossier ZIP path. Without it, CO falls back to a manifest-with-links
dossier so the operator can still complete the workflow, just with
one extra browser step to grab the TKX/TKN archive.

Approval date:

Data Hub commit:
