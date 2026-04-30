from __future__ import annotations

import argparse
import sys

from app.demo_data import get_client
from app.source_index_store import DATABASE_URL_ENV, get_source_index_store


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Manage Postgres source indexes.")
    subcommands = parser.add_subparsers(dest="command", required=True)
    subcommands.add_parser("migrate", help="Apply source index schema migrations.")
    rebuild = subcommands.add_parser("rebuild-client", help="Rebuild source indexes for one client from local JSON state.")
    rebuild.add_argument("client_id")
    args = parser.parse_args(argv)

    store = get_source_index_store()
    if store is None:
        print(f"{DATABASE_URL_ENV} is not set.", file=sys.stderr)
        return 2

    if args.command == "migrate":
        store.ensure_schema()
        print("Applied source index migrations.")
        return 0

    if args.command == "rebuild-client":
        result = store.rebuild_client_from_files(get_client(args.client_id))
        print(
            "Indexed {client_id}: {catalog_rows} catalog rows, {bcct_rows} BCCT rows, "
            "{invoice_tokens} invoice tokens, {co_stock_rows} C/O stock rows.".format(**result)
        )
        return 0

    return 2


if __name__ == "__main__":
    raise SystemExit(main())
