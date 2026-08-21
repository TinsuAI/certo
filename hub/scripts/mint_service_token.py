"""Mint, list, delete, and revoke service-account tokens.

Service tokens are non-human identities for sister-app integration
(CO write-back, BCQT consumer reads, future cron jobs). The token's
`sub` becomes 'svc:<name>'; `scopes[]` is enforced per endpoint;
`client_ids[]` is an optional whitelist (omit for "all clients").

Usage:
  uv run python scripts/mint_service_token.py create \\
      --name co --scopes hub:read,bom:propose --description "CO production" \\
      --created-by admin@data-hub.local
  # → prints token to stdout ONCE. Save it; you cannot retrieve it later.

  uv run python scripts/mint_service_token.py list
  uv run python scripts/mint_service_token.py delete --name co
  uv run python scripts/mint_service_token.py revoke-jti \\
      --jti <hex> --revoked-by admin@data-hub.local --reason "leak suspected"

If you forgot the token, the only path is `delete` + `create` again with
a fresh name (or recreate the same name; old token is rejected because
the row is gone).
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

# Make the app package importable when run from repo root.
_REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO))

from app import jwt_issuer  # noqa: E402
from app.stores import service_accounts as sa_store  # noqa: E402


_NAME_RE = re.compile(r"^[a-z][a-z0-9_-]{0,31}$")


def cmd_create(args: argparse.Namespace) -> int:
    name = args.name.strip()
    if not _NAME_RE.match(name):
        print(f"error: --name must match /^[a-z][a-z0-9_-]{{0,31}}$/; got {name!r}",
              file=sys.stderr)
        return 2
    scopes = [s.strip() for s in args.scopes.split(",") if s.strip()]
    if not scopes:
        print("error: --scopes must list at least one non-empty scope", file=sys.stderr)
        return 2

    # Distinguish "flag not passed" (None → all clients) from "passed empty"
    # (footgun — operator probably meant 'no clients' but that would be
    # nonsensical anyway). Refuse the empty case explicitly.
    if args.client_ids is not None:
        if not args.client_ids.strip():
            print("error: --client-ids was empty; pass a comma-separated list, "
                  "or omit the flag entirely for 'all clients'", file=sys.stderr)
            return 2
        client_ids: list[str] | None = [
            c.strip() for c in args.client_ids.split(",") if c.strip()
        ]
        if not client_ids:
            print("error: --client-ids parsed to empty list; check formatting",
                  file=sys.stderr)
            return 2
    else:
        client_ids = None

    if sa_store.get_account(name) is not None:
        print(f"error: service account '{name}' already exists; "
              f"delete it first or pick a different name", file=sys.stderr)
        return 2

    sa_store.create_account(
        name=name, description=args.description,
        scopes=scopes, client_ids=client_ids, created_by=args.created_by,
    )
    out = jwt_issuer.make_service_token(
        name=name, scopes=scopes, client_ids=client_ids,
        ttl_seconds=args.ttl_seconds,
    )
    print(f"# service account '{name}' created")
    print(f"# scopes: {','.join(scopes) or '(none)'}")
    print(f"# client_ids: {','.join(client_ids) if client_ids else '(all)'}")
    print(f"# expires_in: {out['expires_in']}s")
    print(f"# jti: {out['jti']}")
    print()
    print(out["access_token"])
    return 0


def cmd_list(_args: argparse.Namespace) -> int:
    rows = sa_store.list_accounts()
    if not rows:
        print("(no service accounts)")
        return 0
    for r in rows:
        wl = ",".join(r["client_ids"]) if r["client_ids"] else "(all)"
        last = r["last_used_at"].isoformat() if r["last_used_at"] else "(never)"
        print(f"{r['name']:20s}  scopes={','.join(r['scopes']):30s}  "
              f"clients={wl:20s}  last_used={last}")
    return 0


def cmd_delete(args: argparse.Namespace) -> int:
    if not sa_store.delete_account(args.name):
        print(f"error: no such account '{args.name}'", file=sys.stderr)
        return 2
    print(f"deleted service account '{args.name}' — all tokens for it now reject")
    return 0


def cmd_revoke_jti(args: argparse.Namespace) -> int:
    sa_store.revoke_jti(jti=args.jti, revoked_by=args.revoked_by, reason=args.reason)
    print(f"revoked jti {args.jti}; matching token now rejects")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.strip().splitlines()[0])
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_create = sub.add_parser("create", help="mint a new service account + token")
    p_create.add_argument("--name", required=True, help="account name; sub becomes svc:<name>")
    p_create.add_argument("--scopes", required=True,
                          help="comma-separated, e.g. hub:read,bom:propose")
    p_create.add_argument("--description", default="")
    p_create.add_argument("--client-ids", default=None,
                          help="comma-separated whitelist; omit for all clients. "
                               "Refused if passed but empty.")
    p_create.add_argument("--created-by", required=True, help="audit: who minted this")
    p_create.add_argument("--ttl-seconds", type=int, default=None,
                          help="token TTL in seconds; default = service_token_ttl_seconds setting (30d)")
    p_create.set_defaults(func=cmd_create)

    p_list = sub.add_parser("list", help="list all service accounts")
    p_list.set_defaults(func=cmd_list)

    p_del = sub.add_parser("delete", help="delete a service account; revokes all its tokens")
    p_del.add_argument("--name", required=True)
    p_del.set_defaults(func=cmd_delete)

    p_revoke = sub.add_parser("revoke-jti", help="add a specific jti to the blacklist")
    p_revoke.add_argument("--jti", required=True)
    p_revoke.add_argument("--revoked-by", required=True)
    p_revoke.add_argument("--reason", default="")
    p_revoke.set_defaults(func=cmd_revoke_jti)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
