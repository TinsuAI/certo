# Postgres Source Indexes

The app can keep JSON source files as the audit/source-of-truth layer while using PostgreSQL as a fast read model for C/O lookups.

## Environment

Set an app-specific connection string before running the app or index commands:

```bash
export BARRY_DATABASE_URL="postgresql://<user>:<password>@<host>:<port>/<database>"
```

Do not commit real connection strings. Keep them in local shell config, `.env`, or deployment secrets.

## Commands

Apply schema migrations:

```bash
npm run db:migrate
```

Rebuild indexes for a client from the existing local JSON source state:

```bash
npm run db:rebuild-source-index -- growatt
```

Start the demo as usual with `BARRY_DATABASE_URL` set. C/O dossier pages will use the Postgres index when rows exist for the client, and fall back to JSON files otherwise.

## Indexed Data

The first read model covers the current Growatt bottleneck:

- `bcct_rows`: hot BCCT lookup fields plus the original row payload as `jsonb`
- `bcct_invoice_index`: normalized invoice token to BCCT transaction key
- `co_stock_rows`: derived C/O stock rows plus payload as `jsonb`
- `source_index_metadata`: source version/count metadata for C/O snapshots and nav counts

Catalog and BCCT table screens still use the file-backed source workspace in this phase. Move those screens to SQL pagination separately when needed.
