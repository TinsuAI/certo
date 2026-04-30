from __future__ import annotations

import argparse
import sys

from app.app_state_store import get_app_state_store
from app.client_config_store import config_path, default_config, migrate_config, read_json
from app.client_registry import get_client, seed_clients
from app.source_index_store import DATABASE_URL_ENV, get_source_index_store


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Manage Postgres app state and source indexes.")
    subcommands = parser.add_subparsers(dest="command", required=True)
    subcommands.add_parser("migrate", help="Apply database schema migrations.")
    subcommands.add_parser("import-app-state", help="Import seed clients and local client config JSON into Postgres.")
    subcommands.add_parser("import-workflow-state", help="Import local BOM and C/O case workflow state into Postgres.")
    rebuild = subcommands.add_parser("rebuild-client", help="Rebuild source indexes for one client from local JSON state.")
    rebuild.add_argument("client_id")
    args = parser.parse_args(argv)

    store = get_source_index_store()
    if store is None:
        print(f"{DATABASE_URL_ENV} is not set.", file=sys.stderr)
        return 2

    if args.command == "migrate":
        store.ensure_schema()
        print("Applied database migrations.")
        return 0

    if args.command == "import-app-state":
        app_store = get_app_state_store()
        if app_store is None:
            print(f"{DATABASE_URL_ENV} is not set.", file=sys.stderr)
            return 2
        imported = 0
        for client in seed_clients():
            app_store.upsert_client(client)
            app_store.upsert_client_config(client, config_for_import(client))
            imported += 1
        print(f"Imported {imported} clients and client configs.")
        return 0

    if args.command == "import-workflow-state":
        from app.bom_store import load_state as load_bom_state
        from app.bom_store import save_state as save_bom_state
        from app.co_case_store import load_state as load_case_state
        from app.co_case_store import save_state as save_case_state

        imported = 0
        for client in seed_clients():
            save_bom_state(client["id"], load_bom_state(client))
            save_case_state(client["id"], load_case_state(client["id"]))
            imported += 1
        print(f"Imported BOM and C/O case workflow state for {imported} clients.")
        return 0

    if args.command == "rebuild-client":
        result = store.rebuild_client_from_files(get_client(args.client_id))
        print(
            "Indexed {client_id}: {catalog_rows} catalog rows, {bcct_rows} BCCT rows, "
            "{invoice_tokens} invoice tokens, {co_stock_rows} C/O stock rows.".format(**result)
        )
        return 0

    return 2


def config_for_import(client: dict) -> dict:
    path = config_path(client["id"])
    if path.exists():
        return migrate_config(read_json(path), client)
    return default_config(client)


if __name__ == "__main__":
    raise SystemExit(main())
