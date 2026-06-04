# DH-side fix prompt — declarations download.zip omits file bytes

Hand this prompt to the Data Hub AI agent. It is self-contained (does not
require the CO repo). This is a DEFECT against an already-shipped endpoint,
not a new contract — the fix is a bug fix plus one provider test.

---

```
You are working in the Data Hub codebase. Fix a defect in an existing endpoint reported by the CO (certificate-of-origin) service.

## Endpoint
GET /v1/hub/clients/{client_id}/declarations/download.zip
Query: direction=import|export, declaration_nos=<comma-separated, ≤500>, filename=<optional>

This is the Bearer/service-token variant of the operator's cookie-session "Tải tờ khai" download. It was shipped so CO can fetch TKX/TKN customs files server-side and embed them in the consolidated dossier ZIP.

## Defect
The endpoint returns 200 with a ZIP that contains ONLY the manifest `DANH_SACH_TO_KHAI.txt` — the actual declaration files are missing, even when the declarations have files. The manifest itself proves the files exist and names them; the handler just never streams the blobs into the archive.

## Reproduction (prod, client johnson-vn)
Request:
  GET /v1/hub/clients/johnson-vn/declarations/download.zip?direction=import&declaration_nos=107271918940

Actual response: 200, application/zip, 351 bytes. Archive entries:
  DANH_SACH_TO_KHAI.txt        <-- the ONLY entry

That manifest contains:
  Tổng tờ khai yêu cầu: 1
  Đã có file: 1
  Thiếu file: 0
  == Tờ khai đã có file ==
  - 107271918940: 1 file(s)
      * 2025060921_107271918940.xls      <-- named but NOT in the zip

Same for export (308189816340 -> VNG26010020_308189816340.xls named, absent).

Cross-check, the metadata endpoint agrees a file exists:
  GET /v1/hub/clients/johnson-vn/declarations?direction=import&declaration_nos=107271918940
  -> {"declaration_no":"107271918940","file_count":1,"bcct_line_count":50,...}

The cookie-session browser route for the same declarations DOES include the .xls files. The Bearer route must return the same bytes.

## Expected
For each requested declaration that has files, the ZIP root must contain the actual file(s) PLUS the manifest:
  - All declaration files at the archive root, de-duplicated with `_1`/`_2` suffix on filename collision.
  - DANH_SACH_TO_KHAI.txt manifest (already correct — keep as is).
  - Zero-match case: a well-formed ZIP with the manifest + a NO_FILES_FOUND.txt marker.
Byte-identical to the cookie route for the same params.

## Likely root cause (confirm in code)
The Bearer handler builds DANH_SACH_TO_KHAI.txt from `hub.customs_declaration_files` metadata (row selection `(client_id, direction, declaration_no IN nos)` is correct — manifest is right) but never reads/streams the referenced blobs into the archive. The cookie route already does this; the Bearer handler is missing that blob-embedding step. Likely it shares the manifest builder but not the file-streaming loop. Reuse the cookie route's archive assembly so the two are identical.

## Acceptance
- download.zip (Bearer) for a declaration with file_count ≥ 1 returns a ZIP whose root contains the named .xls file(s) + the manifest — byte-identical to the cookie route for the same direction + declaration_nos.
- Files stream (don't buffer whole archive in memory); the cookie route already streams for the 500-declaration cap.
- Auth, params, and error cases unchanged (scope hub:read; 400 invalid_direction/declaration_nos_required/too_many; 401/403/404 as before).

## Provider tests (add/repair)
- Bearer token + hub:read + matching client, single declaration with a file -> 200 ZIP whose root contains that declaration's file(s) + manifest. (This is the test currently failing — today only the manifest is present.)
- Bearer route output == cookie route output (same bytes) for the same params. Golden test.
- Multi-declaration with filename collisions -> de-dup suffixing applied.
- Zero-match -> manifest + NO_FILES_FOUND.txt, no crash.
- Mixed (some have files, some don't) -> present files embedded; manifest "Thiếu file" section lists the rest; archive still well-formed.
- Auth/param negatives unchanged.

## CO side
No CO change required. CO already embeds whatever bytes this endpoint returns into the dossier's TKX/.../TKN/... archives. Once you include the file bytes, CO's dossier ZIP contains the customs files automatically. CO will re-run its container-side probe (download_declarations_zip + zipfile.namelist) to confirm the fix after you deploy.

After fixing, report the final archive layout and the provider-test results so CO can verify end-to-end.
```
