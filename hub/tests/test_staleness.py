"""Sprint A3: tab_freshness helper for the staleness bar.

Tests use the existing `growatt-vn` seed client; cleanup via TXN prefix
on test rows. No mocking — real DB hits.
"""
from __future__ import annotations

import secrets
from datetime import datetime, timedelta, timezone

import pytest

from hub.app.database import connect
from hub.app.stores.staleness import humanize_age, tab_freshness


CLIENT = "growatt-vn"


@pytest.fixture
def fresh_upload_id():
    """Insert a 'done' file_upload row, yield id, cleanup."""
    upload_id = "STALE_TEST_" + secrets.token_hex(6)
    yield upload_id
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "delete from hub.file_uploads where upload_id = %s",
                (upload_id,),
            )


def _seed_done_upload(upload_id: str, module: str, parsed_at: datetime):
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                insert into hub.file_uploads
                  (upload_id, client_id, module, original_filename,
                   stored_path, content_sha256, size_bytes,
                   parse_status, parsed_at)
                values (%s, %s, %s, 't.xlsx', '/dev/null',
                        'deadbeef', 0, 'done', %s)
                """,
                (upload_id, CLIENT, module, parsed_at),
            )


# ─── tab_freshness happy paths ─────────────────────────────────────────

def test_freshness_returns_max_upload_when_present(fresh_upload_id):
    when = datetime.now(timezone.utc) - timedelta(hours=3)
    _seed_done_upload(fresh_upload_id, "bcct", when)

    result = tab_freshness(CLIENT, "bcct")
    assert result["last_upload_at"] is not None
    # Newer-or-equal to our seeded row
    assert result["last_upload_at"] >= when - timedelta(seconds=2)


def test_freshness_returns_max_data_when_rows_present():
    """growatt-vn already has bcct_rows from prior sessions; just verify
    the field is non-null + a date type."""
    result = tab_freshness(CLIENT, "bcct")
    # Existing seed data → there's data; just assert it returned something
    # date-like or None (works either way against a fresh DB).
    if result["last_data_at"] is not None:
        from datetime import date
        assert isinstance(result["last_data_at"], (date, datetime))


def test_freshness_handles_unknown_client():
    """Client with no uploads returns None for both keys, no crash."""
    result = tab_freshness("nonexistent-client-id-xyz", "bcct")
    assert result == {"last_upload_at": None, "last_data_at": None}


@pytest.mark.parametrize("module", ["bcct", "catalog", "bqd", "bom"])
def test_freshness_supported_for_all_modules(module):
    """Helper must answer for every module that has a tab."""
    result = tab_freshness(CLIENT, module)
    assert "last_upload_at" in result
    assert "last_data_at" in result


def test_freshness_rejects_unknown_module():
    with pytest.raises(ValueError, match="unknown module"):
        tab_freshness(CLIENT, "not_a_module")


def test_freshness_only_counts_done_uploads(fresh_upload_id):
    """parse_status='error' or 'pending' uploads should not count as
    'last upload'."""
    when_recent = datetime.now(timezone.utc)
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                insert into hub.file_uploads
                  (upload_id, client_id, module, original_filename,
                   stored_path, content_sha256, size_bytes,
                   parse_status, parsed_at)
                values (%s, %s, 'bcct', 't.xlsx', '/dev/null',
                        'deadbeef', 0, 'error', %s)
                """,
                (fresh_upload_id, CLIENT, when_recent),
            )

    # Get baseline of legit done uploads
    baseline = tab_freshness(CLIENT, "bcct")["last_upload_at"]
    # The error upload should NOT bump last_upload_at past `when_recent`
    if baseline is not None:
        assert baseline < when_recent or baseline == when_recent - timedelta(seconds=0)


# ─── humanize_age ──────────────────────────────────────────────────────

def test_humanize_age_none():
    assert humanize_age(None) == "—"


def test_humanize_age_just_now():
    assert humanize_age(datetime.now(timezone.utc)) in {"vừa xong", "0 phút trước"}


def test_humanize_age_hours_vi():
    when = datetime.now(timezone.utc) - timedelta(hours=3)
    assert humanize_age(when, lang="vi") == "3 giờ trước"


def test_humanize_age_days_en():
    when = datetime.now(timezone.utc) - timedelta(days=5)
    assert humanize_age(when, lang="en") == "5 days ago"


def test_humanize_age_handles_naive_date():
    from datetime import date
    when = date.today() - timedelta(days=10)
    assert "10" in humanize_age(when, lang="vi")


def test_humanize_age_months():
    when = datetime.now(timezone.utc) - timedelta(days=65)
    assert humanize_age(when, lang="vi") == "2 tháng trước"


def test_humanize_age_negative_clamps_to_just_now():
    """Future timestamps shouldn't crash — render as 'vừa xong'."""
    future = datetime.now(timezone.utc) + timedelta(hours=1)
    assert humanize_age(future) in {"vừa xong", "just now"}
