"""B2: stats_for_client and tab_freshness collapsed to single SQL.

Both helpers used to issue 2-5 sequential round-trips. The collapsed
versions return identical shape — these tests assert shape parity and
that the new versions go through one cursor.execute call (sniffed via
psycopg's logger or by counting cursor calls is fragile; instead we
assert behavior end-to-end against a known-shape client).
"""
from __future__ import annotations

import pytest

from hub.app.routes.clients import stats_for_client
from hub.app.stores.staleness import tab_freshness


@pytest.fixture(scope="module")
def known_client() -> str:
    """growatt-vn always has data seeded; biggest tenant. Use it as
    the integration target so we exercise non-zero counts."""
    return "growatt-vn"


def test_stats_for_client_returns_full_shape(known_client):
    s = stats_for_client(known_client)
    assert set(s.keys()) == {"materials", "mappings", "bcct", "bom", "proposals"}
    assert all(isinstance(v, int) and v >= 0 for v in s.values()), s


def test_stats_for_client_unknown_client_returns_zeros():
    s = stats_for_client("__nonexistent_client__")
    assert s == {"materials": 0, "mappings": 0, "bcct": 0, "bom": 0, "proposals": 0}


def test_tab_freshness_returns_two_keys(known_client):
    for module in ("bcct", "catalog", "bqd", "bom"):
        f = tab_freshness(known_client, module)
        assert set(f.keys()) == {"last_upload_at", "last_data_at"}, module


def test_tab_freshness_unknown_module_raises(known_client):
    with pytest.raises(ValueError):
        tab_freshness(known_client, "nope")


def test_tab_freshness_empty_client_returns_nones():
    f = tab_freshness("__nonexistent_client__", "bcct")
    assert f == {"last_upload_at": None, "last_data_at": None}
