from __future__ import annotations

import argparse

from app.customs_fx_store import CUSTOMS_FX_CLIENT_ID, refresh_customs_exchange_rates


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="customs-fx")
    subcommands = parser.add_subparsers(dest="command", required=True)
    refresh = subcommands.add_parser("refresh", help="Fetch customs exchange rates and save them locally.")
    refresh.add_argument("--client-id", default=CUSTOMS_FX_CLIENT_ID)
    refresh.add_argument("--language", default="TIENG_VIET")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.command == "refresh":
        result = refresh_customs_exchange_rates(client_id=args.client_id, language=args.language)
        print(
            "customs_fx_refresh "
            f"backend={result['backend']} "
            f"fetched={result['fetched_row_count']} "
            f"saved={result['saved_row_count']} "
            f"currencies={result['currency_count']} "
            f"latest={result['latest_effective_date']}"
        )


if __name__ == "__main__":
    main()
