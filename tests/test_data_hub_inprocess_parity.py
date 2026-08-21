"""In-process Data Hub client must be indistinguishable from the HTTP one.

Phase 1 replaces HTTP calls with in-process ones. The guarantee that makes that
safe is exact-output parity: for the same query, `InProcessDataHubClient` must
return what `DataHubClient` returns over the wire. Same pattern the repo already
uses to lock `material_catalog` against the heavy `material_rows` path.

These tests seed their own client in an isolated database and never touch the
real corpus. They skip when no Postgres is configured.
"""
from __future__ import annotations

import os
import secrets

import pytest

# Defaults to the same throwaway database `hub/tests/conftest.py` uses, so this
# runs by default instead of silently skipping. Never the real corpus: the
# fixture seeds its own random-suffixed client and deletes it afterwards.
TEST_DB = os.environ.get(
    "DATA_HUB_TEST_DATABASE_URL", "postgresql:///co_test?host=/var/run/postgresql"
)


def _database_reachable() -> bool:
    try:
        import psycopg

        with psycopg.connect(TEST_DB, connect_timeout=2):
            return True
    except Exception:  # noqa: BLE001
        return False


pytestmark = pytest.mark.skipif(
    not _database_reachable(),
    reason=f"no Postgres at {TEST_DB}",
)


@pytest.fixture(scope="module")
def hub_db():
    """Point the Data Hub half at the throwaway database for this module only."""
    previous = os.environ.get("DATA_HUB_DATABASE_URL")
    os.environ["DATA_HUB_DATABASE_URL"] = TEST_DB
    from hub.app.database import apply_migrations

    apply_migrations()
    yield
    if previous is None:
        os.environ.pop("DATA_HUB_DATABASE_URL", None)
    else:
        os.environ["DATA_HUB_DATABASE_URL"] = previous


@pytest.fixture(scope="module")
def seeded_client(hub_db):
    """A client with enough materials to force multi-page HTTP pagination."""
    from hub.app.database import connect

    client_id = f"parity-{secrets.token_hex(4)}"
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "insert into hub.clients (client_id, name) values (%s, %s)",
            (client_id, "Parity Fixture"),
        )
        for i in range(250):
            cur.execute(
                """insert into hub.materials
                   (client_id, material_code, name, category, status, uom, hs_code)
                   values (%s, %s, %s, %s, %s, %s, %s)""",
                (client_id, f"M{i:05d}", f"Material {i}", "nvl", "active", "PCS", "1234567890"),
            )
        conn.commit()
    yield client_id
    with connect() as conn, conn.cursor() as cur:
        cur.execute("delete from hub.clients where client_id = %s", (client_id,))
        conn.commit()


@pytest.fixture(scope="module")
def clients(seeded_client):
    """One bridged client and one extraction client, same auth."""
    from app.data_hub_client import DataHubClient
    from app.data_hub_inprocess import InProcessDataHubClient, SyncASGITransport
    from hub.app.main import app as hub_app

    # Module-scoped, so restore it — leaking this disables auth for every hub
    # test that runs afterwards and turns their 401 assertions into 200s.
    previous_auth = os.environ.get("DATA_HUB_API_AUTH_DISABLED")
    os.environ["DATA_HUB_API_AUTH_DISABLED"] = "1"
    bridged = DataHubClient(
        base_url="http://data-hub.internal",
        token="",
        transport=SyncASGITransport(hub_app),
    )
    inprocess = InProcessDataHubClient(token="")
    try:
        yield bridged, inprocess, seeded_client
    finally:
        bridged.close()
        inprocess.close()
        if previous_auth is None:
            os.environ.pop("DATA_HUB_API_AUTH_DISABLED", None)
        else:
            os.environ["DATA_HUB_API_AUTH_DISABLED"] = previous_auth


def test_list_materials_matches_the_http_path_exactly(clients):
    """The extraction override returns the same rows the paginated route does."""
    bridged, inprocess, client_id = clients

    over_http = bridged.list_materials(client_id, limit=100)
    in_process = inprocess.list_materials(client_id)

    assert len(over_http) == 250, "fixture must span more than one page"
    assert in_process == over_http


def test_list_materials_honours_the_status_filter_identically(clients):
    bridged, inprocess, client_id = clients

    assert inprocess.list_materials(client_id, status="active") == bridged.list_materials(
        client_id, status="active", limit=100
    )
    assert inprocess.list_materials(client_id, status="tombstoned") == []


def test_unknown_client_is_rejected_in_process_too(clients):
    """A missing client must not read as an empty catalog."""
    import httpx

    _, inprocess, _ = clients
    with pytest.raises(httpx.HTTPStatusError):
        inprocess.list_materials("no-such-client-parity")


def test_service_account_scoping_is_enforced_in_process(clients, monkeypatch):
    """The in-process path must refuse a client outside the token's whitelist.

    Without this the extraction would bypass `_require_can_view_client` and any
    CO session could read any client's corpus — with no test failing.
    """
    from fastapi import HTTPException

    _, inprocess, client_id = clients
    monkeypatch.setenv("DATA_HUB_API_AUTH_DISABLED", "0")
    monkeypatch.setattr(
        "hub.app.routes.api._require_token",
        lambda header, scope="hub:read": {"typ": "service", "client_ids": ["someone-else"]},
    )
    with pytest.raises(HTTPException) as excinfo:
        inprocess.list_materials(client_id)
    assert excinfo.value.status_code == 403
