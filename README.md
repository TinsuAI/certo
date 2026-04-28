# barry-CO

Discovery workspace for a future CO webapp for agency staff. The current bootstrap is intentionally limited to project metadata, archive extraction, and data exploration of the supplied agency files.

## Current Scope

- Keep project context and decisions in `.ai/`
- Extract ZIP and RAR source archives under local-only `data/`
- Explore the dataset and document its structure before choosing application architecture
- Maintain shared project docs in `docs/`
- Run a first-pass C/O preparation demo webapp for simple Growatt-style cases

## Commands

```bash
npm run extract:rars
npm run co:serve
```

Open the demo app at `http://127.0.0.1:8001/clients`.

## Data Notes

- The source archive lives under `data/`.
- Extracted working files are expected under `data/extracted/CO`.
- `data/` is gitignored on purpose; agency documents stay local.
- Shared business and analysis docs live in `docs/`
