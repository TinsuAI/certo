# Data Hub Defect: declarations download.zip returns manifest only, omits file bytes

**Type:** Defect against an existing, already-approved contract
(`.ai/api-requests/2026-05-28-bcct-declarations-download-bearer.md`).
**Severity:** High — blocks the consolidated CO dossier ZIP from
including the actual TKX/TKN declaration files.
**Endpoint:** `GET /v1/hub/clients/{client_id}/declarations/download.zip`
**Date:** 2026-06-04
**Reported by:** CO (barry-CO)

## Symptom

When an operator exports the dossier `.zip` from CO's Review step, the
`TKX/…zip` and `TKN/…zip` archives embedded in the dossier contain only
a `DANH_SACH_TO_KHAI.txt` manifest — none of the actual declaration
files. The operator gets a text list instead of the customs files.

CO embeds verbatim whatever bytes Data Hub's `download.zip` returns, so
the defect is entirely on the Data Hub side; CO needs no change.

## Evidence (probed against prod Data Hub, client `johnson-vn`)

Service-token and operator-JWT flows both reproduce. Single import
declaration `107271918940` (Data Hub UI shows `FILE = 1`, `✓ Có TK`):

Request:
```
GET /v1/hub/clients/johnson-vn/declarations/download.zip
    ?direction=import&declaration_nos=107271918940
```

Response: `200`, `application/zip`, 351 bytes. Archive contents:
```
DANH_SACH_TO_KHAI.txt   (277 bytes)   ← the ONLY entry
```

The manifest itself confirms the file exists and even names it:
```
Tổng tờ khai yêu cầu: 1
Đã có file: 1
Thiếu file: 0
== Tờ khai đã có file ==
- 107271918940: 1 file(s)
    * 2025060921_107271918940.xls      ← named, but NOT included in the zip
```

Same result for export direction (`308189816340` →
`VNG26010020_308189816340.xls` named in manifest, absent from zip).

Cross-check — the metadata endpoint also reports the file exists:
```
GET /v1/hub/clients/johnson-vn/declarations?direction=import&declaration_nos=107271918940
→ {"declaration_no":"107271918940","direction":"import","bcct_line_count":50,"file_count":1,"earliest_bcct_date":"2025-06-16"}
```

## Expected (per the approved 2026-05-28 contract)

The contract's Response section and provider tests require the file
bytes, not just the manifest:

- Response body: "All declaration files at the archive root
  (de-duplicated with `_1`/`_2` on filename collision)." + the manifest.
- Provider test: "Bearer token … → 200 ZIP with the **same bytes as the
  cookie route** would return for the same params."
- Provider test: "Single declaration → 200, archive **contains only that
  declaration's files**."

The current implementation returns the manifest the contract asks for
but drops the declaration files — so it fails the two provider tests
above. The cookie-session browser route returns the files; the Bearer
route must return the same bytes.

## Likely root cause (for Data Hub to confirm)

The Bearer handler appears to build the `DANH_SACH_TO_KHAI.txt` manifest
from `hub.customs_declaration_files` metadata but never streams the
referenced blobs into the archive. The file selection logic
(`(client_id, direction, declaration_no IN nos)`) resolves the rows
(manifest is correct) — only the blob-embedding step is missing
relative to the cookie route.

## Acceptance

- `download.zip` (Bearer) for a declaration with `file_count ≥ 1`
  returns a ZIP whose root contains the named `.xls` file(s) plus the
  manifest — byte-identical to the cookie route for the same params.
- Re-run the existing contract's provider tests; the "same bytes as
  cookie route" and "single declaration contains its files" cases must
  pass.

## CO side

No change required. CO's `download_declarations_zip` adapter and the
dossier builder already embed the returned ZIP; once Data Hub includes
the file bytes, the dossier's `TKX/…` and `TKN/…` archives will contain
the customs files automatically. Verified probe scripts used above can
be re-run from the `co-app-1` container to confirm the fix.
