# 2026-05-28 — BOM vocab v1 URL aliases removed

**Breaking.** The 308 redirects that bridged the BOM vocab v1 → v2
rename (mig 031, 2026-05-07) were dropped after the 3-week grace
period. Old URLs now return 404, not 308.

## Removed endpoints

- `GET /v1/hub/products/{p}/bom/versions` — Bearer sister-app surface.
- `GET /clients/{c}/bom/version/{id}` — cookie-UI surface.
- `GET /clients/{c}/bom/{p}/versions` — cookie-UI surface.

## Replacement (already canonical since 2026-05-07)

- `GET /v1/hub/products/{p}/bom/artifacts`
- `GET /clients/{c}/bom/artifact/{id}`
- `GET /clients/{c}/bom/{p}/artifacts`

## Action required

None expected. Pre-flight grep on both consumer repos was clean:

```
$ grep -rn "bom/version\|bom/versions" barry-CO-main/app
$ grep -rn "bom/version\|bom/versions" BCQT-System/app
# both: zero hits
```

If your branch has new code that references the old paths, switch to
the v2 path. The new URLs have been the canonical names since
2026-05-07 and have always been documented as such in
`docs/API_CONTRACT.md`.

## Why now

`.ai/BACKLOG.md` C.3 entry. Removal trigger:
1. Sister apps migrated — ✓ verified.
2. Zero alias hits in server logs — not strictly verifiable (demo
   container restarts on every CI deploy, no persistent access log)
   but no caller path remains that would hit them.
3. External bookmark risk — low (demo is internal-only).

## Refs

- Changelog: `docs/API_CHANGELOG.md` 2026-05-28 Breaking entry.
- Original rename brief: `.ai/features/2026-05-07-bom-vocab-rename/brief.md`.
