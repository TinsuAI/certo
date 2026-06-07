"""Minimal Keep a Changelog parser — no markdown dependency.

The CHANGELOG.md format is constrained, so a line scanner is enough:

    ## [x.y.z] — YYYY-MM-DD   (or "- " hyphen; date optional)
    ## [Unreleased]
    ### Section title
    - bullet item

Returns releases in file order (newest first by convention). Bullets are
plain strings; HTML escaping happens at render time via Jinja autoescape.
"""
from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path

_CHANGELOG = Path(__file__).resolve().parent.parent / "CHANGELOG.md"

# "## [0.2.0] — 2026-06-07" / "## [Unreleased]" — em-dash or hyphen sep.
_REL = re.compile(
    r"^##\s+\[(?P<version>[^\]]+)\]\s*(?:[—\-]\s*(?P<date>\S+))?\s*$"
)
_SECTION = re.compile(r"^###\s+(?P<title>.+?)\s*$")
_BULLET = re.compile(r"^[-*]\s+(?P<item>.+?)\s*$")


def parse_changelog(text: str) -> list[dict]:
    releases: list[dict] = []
    cur_rel: dict | None = None
    cur_section: dict | None = None
    for line in text.splitlines():
        m = _REL.match(line)
        if m:
            cur_rel = {
                "version": m.group("version").strip(),
                "date": (m.group("date") or "").strip() or None,
                "unreleased": m.group("version").strip().lower() == "unreleased",
                "sections": [],
            }
            releases.append(cur_rel)
            cur_section = None
            continue
        if cur_rel is None:
            continue
        m = _SECTION.match(line)
        if m:
            cur_section = {"title": m.group("title").strip(), "entries": []}
            cur_rel["sections"].append(cur_section)
            continue
        m = _BULLET.match(line)
        if m and cur_section is not None:
            cur_section["entries"].append(m.group("item").strip())
    return releases


@lru_cache(maxsize=1)
def _read(mtime: float) -> list[dict]:  # mtime keys the cache
    try:
        return parse_changelog(_CHANGELOG.read_text(encoding="utf-8"))
    except OSError:
        return []


def load_changelog() -> list[dict]:
    try:
        mtime = _CHANGELOG.stat().st_mtime
    except OSError:
        return []
    return _read(mtime)
