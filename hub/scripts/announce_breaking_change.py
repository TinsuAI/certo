#!/usr/bin/env -S uv run python
"""Parse the most recent `## YYYY-MM-DD — Breaking: ...` entry from
docs/API_CHANGELOG.md and fan-out a notification to all dev + admin
users (CO + BCQT operator accounts read the same bell).

Run after committing a breaking-change entry to the changelog. Idempotent
on the headline string — re-running with the same headline pings users
again, so don't run twice unless intentional.

Usage:
  uv run python scripts/announce_breaking_change.py            # dry-run
  uv run python scripts/announce_breaking_change.py --confirm  # send

Exit codes:
  0  notification sent (or dry-run printed)
  1  no Breaking entry found in changelog
  2  could not connect / no recipients
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

CHANGELOG = (
    Path(__file__).resolve().parent.parent / "docs" / "API_CHANGELOG.md"
)

BREAKING_HEADING = re.compile(
    r"^##\s+(\d{4}-\d{2}-\d{2})\s+—\s+Breaking:\s+(.+?)\s*$",
    re.MULTILINE,
)


def find_latest_breaking(text: str) -> tuple[str, str] | None:
    """Return (date, summary) of the latest `## ... — Breaking:` entry."""
    matches = list(BREAKING_HEADING.finditer(text))
    if not matches:
        return None
    # Latest by date string (YYYY-MM-DD sorts lexicographically).
    latest = max(matches, key=lambda m: m.group(1))
    return latest.group(1), latest.group(2)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--confirm", action="store_true",
                        help="Actually send the notification (default: dry-run).")
    parser.add_argument("--changelog", default=str(CHANGELOG),
                        help="Path to API_CHANGELOG.md")
    args = parser.parse_args()

    text = Path(args.changelog).read_text(encoding="utf-8")
    latest = find_latest_breaking(text)
    if not latest:
        print("No `## ... — Breaking:` entry found in changelog. Nothing to announce.",
              file=sys.stderr)
        return 1
    date, summary = latest
    headline = f"[{date}] {summary}"
    print(f"Latest breaking entry: {headline}")
    if not args.confirm:
        print("Dry-run. Re-run with --confirm to send.")
        return 0

    # Lazy-import so dry-run can work without a DB connection.
    try:
        from hub.app.notifications import notify_api_contract_changed
    except Exception as exc:
        print(f"Failed to import notifier: {exc}", file=sys.stderr)
        return 2
    try:
        n = notify_api_contract_changed(summary=headline)
    except Exception as exc:
        print(f"Failed to send: {exc}", file=sys.stderr)
        return 2
    if n == 0:
        print("No active dev/admin recipients found.", file=sys.stderr)
        return 2
    print(f"Sent to {n} dev/admin user(s).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
