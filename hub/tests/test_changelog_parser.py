"""CHANGELOG.md parser (Keep a Changelog subset).

Feature brief: .ai/features/2026-06-07-app-versioning-changelog/brief.md
"""
from __future__ import annotations

from hub.app.changelog import parse_changelog

SAMPLE = """# Changelog

## [Unreleased]
### Mới
- Tính năng đang phát triển.

## [0.2.0] — 2026-06-07
### Mới
- Trang "Có gì mới".
- Hiển thị phiên bản ứng dụng.
### Sửa lỗi
- Sửa lỗi A.

## [0.1.0] - 2026-04-30
### Mới
- Bản scaffold đầu tiên.
"""


def test_parses_versions_in_file_order():
    releases = parse_changelog(SAMPLE)
    assert [r["version"] for r in releases] == ["Unreleased", "0.2.0", "0.1.0"]


def test_unreleased_flagged():
    releases = parse_changelog(SAMPLE)
    assert releases[0]["unreleased"] is True
    assert releases[1]["unreleased"] is False


def test_date_parsed_for_both_dash_styles():
    releases = parse_changelog(SAMPLE)
    assert releases[1]["date"] == "2026-06-07"  # em-dash
    assert releases[2]["date"] == "2026-04-30"  # hyphen


def test_sections_and_bullets():
    releases = parse_changelog(SAMPLE)
    v020 = releases[1]
    assert [s["title"] for s in v020["sections"]] == ["Mới", "Sửa lỗi"]
    assert v020["sections"][0]["entries"] == [
        'Trang "Có gì mới".',
        "Hiển thị phiên bản ứng dụng.",
    ]


def test_empty_and_malformed_do_not_crash():
    assert parse_changelog("") == []
    assert parse_changelog("just some prose, no headings") == []
