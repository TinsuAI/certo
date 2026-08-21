from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from hub.app import auth, settings_store
from hub.app.database import connect
from hub.app.main import app


CLIENT_ID = "toggle-agent-client"


@pytest.fixture
def restore_technical_settings():
    before = settings_store.get_many(settings_store.TECHNICAL_KEYS)
    yield
    restored = {k: before.get(k, "") for k in settings_store.TECHNICAL_KEYS}
    restored[settings_store.CHAT_AGENT_ENABLED_KEY] = before.get(
        settings_store.CHAT_AGENT_ENABLED_KEY, "true",
    )
    settings_store.set_many(restored)


@pytest.fixture
def dev_client():
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "select user_id from hub.users where role = 'dev' and status = 'active' limit 1"
            )
            row = cur.fetchone()
            assert row is not None, "no active dev user found"
            user_id = row[0]
            cur.execute(
                """
                insert into hub.clients (client_id, name, status)
                values (%s, 'Toggle Agent Client', 'active')
                on conflict (client_id) do nothing
                """,
                (CLIENT_ID,),
            )

    session_id = auth.create_session(user_id)
    client = TestClient(app)
    client.cookies.set(auth.SESSION_COOKIE, session_id)
    try:
        yield client
    finally:
        auth.revoke_session(session_id)
        with connect() as conn:
            with conn.cursor() as cur:
                cur.execute("delete from hub.clients where client_id = %s", (CLIENT_ID,))


def test_technical_settings_saves_chat_agent_toggle(
    dev_client, restore_technical_settings,
):
    off = dev_client.post(
        "/admin/settings/technical", data={}, follow_redirects=False,
    )
    assert off.status_code == 303
    assert settings_store.chat_agent_enabled() is False

    on = dev_client.post(
        "/admin/settings/technical",
        data={"chat_agent_enabled": "true"},
        follow_redirects=False,
    )
    assert on.status_code == 303
    assert settings_store.chat_agent_enabled() is True


def test_disabled_chat_agent_hides_ui_and_blocks_routes(
    dev_client, restore_technical_settings,
):
    settings_store.set_many({"chat_agent_enabled": "false"})

    page = dev_client.get(f"/clients/{CLIENT_ID}", follow_redirects=False)
    assert page.status_code == 200
    assert 'id="chat-widget"' not in page.text
    assert f'href="/clients/{CLIENT_ID}/agent"' not in page.text

    full_page = dev_client.get(
        f"/clients/{CLIENT_ID}/agent", follow_redirects=False,
    )
    widget = dev_client.get(
        f"/clients/{CLIENT_ID}/agent/_widget", follow_redirects=False,
    )
    assert full_page.status_code == 404
    assert widget.status_code == 404
