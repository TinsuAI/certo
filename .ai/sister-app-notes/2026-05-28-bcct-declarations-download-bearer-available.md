# Declarations download.zip — Bearer mirror available

**To:** CO repo (`barry-CO-main`)
**From:** Data Hub
**Date:** 2026-05-28
**Request:** `barry-CO-main/.ai/api-requests/2026-05-28-bcct-declarations-download-bearer.md`

## Status

Shipped. Endpoint live on demo (`http://100.84.189.87:8754`) and dev
after the next CI deploy.

## What's available

`GET /v1/hub/clients/{client_id}/declarations/download.zip`

Same query contract as the cookie route. CO can call it server-side
using either the operator's forwarded JWT or a service token.

Query params:
- `direction` (required): `import` or `export`.
- `declaration_nos` (required): comma-separated, max 500. Exact-match
  against Data Hub's canonical `declaration_no` string.
- `filename` (optional): preferred archive filename in
  `Content-Disposition`. Default
  `declarations_{client_id}_{direction}.zip`.

Response: same bytes the cookie route returns today.
- `Content-Type: application/zip`
- `Content-Disposition: attachment; filename="..."`
- Body: files at archive root (deduped `_1`/`_2` on filename collision),
  `DANH_SACH_TO_KHAI.txt` manifest, `NO_FILES_FOUND.txt` marker on
  zero-match.

## Auth

`hub:read` scope. User JWT (preferred — operator identity carries
through audit logs) OR service token. Service token's `client_ids`
whitelist must include the requested `{client_id}`.

The cookie route at `/clients/{cid}/declarations/download.zip` stays
in place for operator browser flow — no behavior change there. The
two routes share the same archive-builder helpers
(`_build_declarations_zip` + `_parse_zip_declaration_nos` +
`_safe_archive_filename`) so the bytes will not drift.

## Errors

- `400 invalid_direction` — `direction` missing or not `import`/`export`.
- `400 declaration_nos_required` — empty or whitespace-only.
- `400 too_many_declaration_nos` — more than 500.
- `401 bearer token required` — missing/invalid bearer in strict mode.
- `403 forbidden` — service token lacks `hub:read` or `client_id` is
  outside the token's whitelist.
- `404 Client not found` — unknown `client_id`.

## CO consumer plan (from the request, for tracking)

Adapter method `download_declarations_zip(client_id, *, direction,
declaration_nos, filename)` in `app/data_hub_client.py`. Call sites:

- `app/workbook_io.py:create_dossier_zip` — splice TKX/TKN bytes into
  `tkx-tkn/exports/...` + `tkx-tkn/imports/...`.
- `app/main.py:/clients/{cid}/co-case/{cid}/export-dossier-zip` —
  operator entry point.

Fallback behavior on CO side (per request): if the endpoint returns
404 (old deployment), CO falls back to the existing manifest-with-links
dossier so the operator can still complete the workflow.

## Empirical smoke (recommended on CO side)

Once CO's adapter ships, pull a small dossier (~5 declarations) against
demo with both a user JWT and a service token. Verify the ZIP bytes
match what the operator gets from the cookie route in their browser.

## Open follow-ups

- Streaming: today the route buffers the full archive in memory before
  returning. For Johnson's largest dossier (~50 declarations × ~1-2MB
  per file) that's <100 MB and fine. If CO ever wants to package a
  whole client's history (~3.5k declarations) into one archive, surface
  the request and we'll switch the route to `StreamingResponse` with
  a generator-based ZIP writer.
- The 500-declaration cap is enforced server-side on the Bearer route
  only. The cookie route has no cap because the operator workflow
  wouldn't realistically hit it; revisit if that proves wrong.
