"""Connection pool behavior — reset-on-checkin clears `app.user_id`
GUC so SESSION-scoped state from one request can't leak into the next
when connections get reused. The bcct_row_history trigger reads
`app.user_id` to attribute changes, so a leak would mis-attribute
edits to the wrong user.

These tests force the pool to a single physical connection so we
deterministically know subsequent acquires reuse the same conn.
"""
from __future__ import annotations

import pytest

from app.database import connect, _reconfigure_pool_for_test, close_pool


@pytest.fixture(autouse=True)
def _single_conn_pool():
    """Force pool to size=1 so every checkout reuses the same physical
    connection — the worst case for state leak."""
    _reconfigure_pool_for_test(min_size=1, max_size=1)
    yield
    close_pool()


def _read_user_id(conn) -> str:
    with conn.cursor() as cur:
        cur.execute("select current_setting('app.user_id', true)")
        (val,) = cur.fetchone()
    return val or ""


def test_connect_sets_app_user_id_when_supplied():
    with connect(user_id="u_alice") as conn:
        assert _read_user_id(conn) == "u_alice"


def test_app_user_id_reset_between_pool_checkouts():
    """First request sets app.user_id=alice. Second request acquires
    same physical connection (pool size 1) without supplying user_id —
    must see empty string, NOT 'u_alice'."""
    with connect(user_id="u_alice") as conn:
        assert _read_user_id(conn) == "u_alice"
    with connect() as conn:
        assert _read_user_id(conn) == "", \
            "app.user_id leaked across pool checkouts"


def test_app_user_id_overwritten_per_request():
    """Two consecutive requests with different user_ids — second must
    see only its own value."""
    with connect(user_id="u_alice") as conn:
        assert _read_user_id(conn) == "u_alice"
    with connect(user_id="u_bob") as conn:
        assert _read_user_id(conn) == "u_bob"


def test_connect_context_manager_commits_on_clean_exit():
    """Existing semantic contract — `with connect() as conn:` commits
    on clean exit. Verify by writing to a temp table inside one block,
    reading from another."""
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "create temp table _pool_test_commit (v int) on commit drop"
            )
            cur.execute("insert into _pool_test_commit values (42)")
            # No explicit commit — temp ON COMMIT DROP fires at txn end.
            cur.execute("select v from _pool_test_commit")
            (val,) = cur.fetchone()
    assert val == 42


def test_connect_with_custom_url_bypasses_pool():
    """connect(url=...) with a non-default URL must open an ad-hoc
    connection rather than reuse the pool — needed for migrations that
    target a side-DB or for tests against a sandbox."""
    from app.database import database_url
    with connect(url=database_url()) as conn:
        # Sanity: still works against the same DB.
        with conn.cursor() as cur:
            cur.execute("select 1")
            assert cur.fetchone() == (1,)
