# Feature briefs

Each feature is documented here, following the Data Hub convention.

## Layout

A feature is either:

- **A flat file** `YYYY-MM-DD-slug.md` — when it has no screenshots.
- **A folder** `YYYY-MM-DD-slug/` containing:
  - `brief.md` — the spec / fix plan / audit notes.
  - `screenshots/` — visual evidence, grouped in subfolders by capture run
    (e.g. `screenshots/origin-ui-tweaks/`, `screenshots/prod-03-substitute.png`).

## Git policy

- `brief.md` (and flat `.md` briefs) **are committed**.
- `screenshots/` **is git-ignored** (`.ai/features/*/screenshots/` in `.gitignore`)
  — the PNGs are local-only to keep the repo lean. They organise the evidence
  logically next to the brief without bloating git with binaries.
- If a specific "hero" image really needs to be shared via git, commit that one
  file explicitly (`git add -f path`) or attach it to the PR; don't track the
  whole folder.

## Unsorted captures

Verification / audit / throwaway runs that aren't tied to a single feature stay
under the (also git-ignored) `.ai/screenshots/` folder until they're either
mapped to a feature or deleted.
