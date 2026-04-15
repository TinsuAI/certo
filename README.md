# barry-CO

Local-first CO preparation workspace for agency staff. The app currently boots as a discovery dashboard over the supplied case archives so the next implementation steps can be grounded in real documents, statuses, and workflow artifacts.

## Stack

- Next.js 16 App Router
- TypeScript
- React 19
- Local filesystem discovery against `data/extracted/CO`
- `node-unrar-js` for opening nested `.rar` archives

## Commands

```bash
npm run dev
npm run build
npm run lint
npm run extract:rars
```

## Data Notes

- The source archive lives under `data/`.
- Extracted working files are expected under `data/extracted/CO`.
- `data/` is gitignored on purpose; agency documents stay local.

## Current Bootstrap Scope

- App scaffolded and ready for feature work
- Initial dashboard reads real extracted case folders
- ZIPs expanded locally
- RAR extraction can be rerun with `npm run extract:rars`
