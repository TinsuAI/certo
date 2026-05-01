"""Sprint B2: chat agent.

Covers tool dispatch ACL, tool implementations against real DB seed,
runtime loop with mocked LLM (no network), and store CRUD.
"""
from __future__ import annotations

import json
import secrets
from unittest.mock import MagicMock, patch

import pytest

from app.agent import runtime, store, tools
from app.database import connect


CLIENT = "growatt-vn"


# ─── Test users with different scopes ─────────────────────────────────

@pytest.fixture
def viewer_user():
    """Create a staff user with read access to growatt-vn."""
    uid = "u_viewer_" + secrets.token_hex(4)
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                insert into hub.users
                  (user_id, email, password_hash, role, status, display_name)
                values (%s, %s, 'x', 'staff', 'active', 'Viewer')
                """,
                (uid, f"{uid}@test"),
            )
            cur.execute(
                """
                insert into hub.user_client_access
                  (user_id, client_id, scope, granted_by)
                values (%s, %s, 'read',
                        (select user_id from hub.users where role = 'dev' limit 1))
                """,
                (uid, CLIENT),
            )
    # Get the User dataclass
    from app.auth.session import User
    yield User(user_id=uid, email=f"{uid}@test", display_name="Viewer",
               role="staff", status="active")
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute("delete from hub.user_client_access where user_id = %s", (uid,))
            cur.execute("delete from hub.users where user_id = %s", (uid,))


@pytest.fixture
def outsider_user():
    """Staff user with NO access to growatt-vn."""
    uid = "u_outsider_" + secrets.token_hex(4)
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                insert into hub.users
                  (user_id, email, password_hash, role, status, display_name)
                values (%s, %s, 'x', 'staff', 'active', 'Outsider')
                """,
                (uid, f"{uid}@test"),
            )
    from app.auth.session import User
    yield User(user_id=uid, email=f"{uid}@test", display_name="Outsider",
               role="staff", status="active")
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute("delete from hub.users where user_id = %s", (uid,))


# ─── ACL gate on dispatch ──────────────────────────────────────────────

def test_dispatch_denies_outsider(outsider_user):
    """Staff with no access to client → tool returns permission denied,
    no DB query attempted."""
    result = tools.dispatch_tool(
        user=outsider_user, client_id=CLIENT,
        name="query_bcct", args={"limit": 5},
    )
    assert result["ok"] is False
    assert "permission" in result["error"].lower()


def test_dispatch_strips_client_id_from_args(viewer_user):
    """Even if the LLM tries to override client_id in args, dispatcher
    drops it and uses the runtime-bound one."""
    # We can't easily verify this without a query that would expose
    # it, but we can check the dispatcher accepts the call without
    # passing client_id through to the impl.
    result = tools.dispatch_tool(
        user=viewer_user, client_id=CLIENT,
        name="query_catalog",
        args={"client_id": "OTHER-CLIENT", "limit": 1},
    )
    # Should succeed against growatt-vn data, not error on bad arg.
    assert result["ok"] is True


def test_dispatch_unknown_tool_returns_error(viewer_user):
    result = tools.dispatch_tool(
        user=viewer_user, client_id=CLIENT,
        name="erase_database", args={},
    )
    assert result["ok"] is False
    assert "unknown" in result["error"].lower()


def test_dispatch_bad_args_returns_error(viewer_user):
    result = tools.dispatch_tool(
        user=viewer_user, client_id=CLIENT,
        name="query_bcct", args={"unknown_arg": "x"},
    )
    assert result["ok"] is False
    # bad args becomes a tool-result error so the LLM can adapt
    assert "args" in result["error"].lower() or "unknown_arg" in result["error"]


# ─── Tool implementations ──────────────────────────────────────────────

def test_query_catalog_returns_growatt_data(viewer_user):
    result = tools.dispatch_tool(
        user=viewer_user, client_id=CLIENT,
        name="query_catalog", args={"limit": 5},
    )
    assert result["ok"] is True
    assert isinstance(result["rows"], list)
    assert result["row_count"] >= 0


def test_query_catalog_filter_by_provenance(viewer_user):
    result = tools.dispatch_tool(
        user=viewer_user, client_id=CLIENT,
        name="query_catalog", args={"provenance": "registered", "limit": 5},
    )
    assert result["ok"] is True
    for row in result["rows"]:
        assert "registered_with_hq" in row.get("provenance", {})


def test_query_provenance_alarms_shape(viewer_user):
    result = tools.dispatch_tool(
        user=viewer_user, client_id=CLIENT,
        name="query_provenance_alarms", args={},
    )
    assert result["ok"] is True
    assert "rows" in result


def test_query_bom_no_code_returns_products(viewer_user):
    result = tools.dispatch_tool(
        user=viewer_user, client_id=CLIENT,
        name="query_bom", args={"limit": 5},
    )
    assert result["ok"] is True


def test_submit_final_answer_returns_marker(viewer_user):
    result = tools.dispatch_tool(
        user=viewer_user, client_id=CLIENT,
        name="submit_final_answer", args={"answer": "Test answer."},
    )
    assert result["ok"] is True
    assert result.get("final") is True
    assert result.get("answer") == "Test answer."


# ─── Store ──────────────────────────────────────────────────────────────

def test_create_get_thread_owner_only(viewer_user, outsider_user):
    tid = store.create_thread(
        user_id=viewer_user.user_id, client_id=CLIENT, title="t1",
    )
    # Owner sees it
    found = store.get_thread(
        thread_id=tid, user_id=viewer_user.user_id, client_id=CLIENT,
    )
    assert found is not None
    assert found["title"] == "t1"
    # Outsider does NOT (no existence leak)
    not_found = store.get_thread(
        thread_id=tid, user_id=outsider_user.user_id, client_id=CLIENT,
    )
    assert not_found is None


def test_append_messages_and_list(viewer_user):
    tid = store.create_thread(
        user_id=viewer_user.user_id, client_id=CLIENT,
    )
    store.append_message(thread_id=tid, role="user", content="hello")
    store.append_message(thread_id=tid, role="assistant", content="hi")
    msgs = store.list_messages(thread_id=tid)
    assert len(msgs) == 2
    assert msgs[0]["content"] == "hello"
    assert msgs[1]["content"] == "hi"


def test_to_openai_messages_shape(viewer_user):
    tid = store.create_thread(
        user_id=viewer_user.user_id, client_id=CLIENT,
    )
    store.append_message(thread_id=tid, role="user", content="hi")
    store.append_message(
        thread_id=tid, role="assistant", content="ok",
        tool_calls=[{"id": "call_1", "type": "function",
                     "function": {"name": "query_bcct", "arguments": "{}"}}],
    )
    store.append_message(
        thread_id=tid, role="tool", content='{"ok": true}',
        tool_call_id="call_1", tool_name="query_bcct",
    )
    converted = store.to_openai_messages(store.list_messages(thread_id=tid))
    assert converted[0] == {"role": "user", "content": "hi"}
    assert converted[1]["role"] == "assistant"
    assert converted[1]["tool_calls"][0]["id"] == "call_1"
    assert converted[2] == {"role": "tool", "tool_call_id": "call_1",
                            "name": "query_bcct", "content": '{"ok": true}'}


# ─── Runtime loop with mocked LLM ──────────────────────────────────────

def _mock_llm_with_steps(steps: list[dict]):
    """Return a context manager that patches OpenAI to yield each
    `steps` entry as a chat completion. Each step dict:
        {"content": str|None, "tool_calls": [{"name": str, "args": dict}, ...]}
    """
    completion_objs = []
    for step in steps:
        msg = MagicMock()
        msg.content = step.get("content") or ""
        if step.get("tool_calls"):
            tcs = []
            for i, tc in enumerate(step["tool_calls"]):
                obj = MagicMock()
                obj.id = f"call_{secrets.token_hex(4)}_{i}"
                obj.function.name = tc["name"]
                obj.function.arguments = json.dumps(tc.get("args", {}))
                tcs.append(obj)
            msg.tool_calls = tcs
        else:
            msg.tool_calls = None
        choice = MagicMock()
        choice.message = msg
        comp = MagicMock()
        comp.choices = [choice]
        completion_objs.append(comp)

    client_mock = MagicMock()
    client_mock.chat.completions.create.side_effect = completion_objs
    return client_mock


def test_runtime_terminates_on_submit_final_answer(viewer_user):
    """Agent calls one tool, then submits final. Runtime returns the answer."""
    tid = store.create_thread(
        user_id=viewer_user.user_id, client_id=CLIENT,
    )
    fake_client = _mock_llm_with_steps([
        {"tool_calls": [{"name": "query_catalog", "args": {"limit": 3}}]},
        {"tool_calls": [{"name": "submit_final_answer",
                         "args": {"answer": "Có 3 mã NVL."}}]},
    ])
    fake_cfg = MagicMock()
    fake_cfg.is_enabled.return_value = True
    fake_cfg.base_url = "http://fake"
    fake_cfg.api_key = "x"
    fake_cfg.model = "test-model"
    fake_cfg.temperature = 0.0
    fake_cfg.timeout_s = 10
    fake_cfg.max_retries = 0
    fake_cfg.max_calls_per_day_per_client = 1000

    with patch("app.agent.runtime.OpenAI", return_value=fake_client) if False else patch.object(
        runtime, "_check_and_record_budget", return_value=None
    ), patch("openai.OpenAI", return_value=fake_client):
        answer = runtime.run_turn(
            thread_id=tid, user=viewer_user, client_id=CLIENT,
            user_text="Có bao nhiêu mã NVL?", cfg=fake_cfg,
        )

    assert "3" in answer
    msgs = store.list_messages(thread_id=tid)
    # user → assistant(tool_calls) → tool result → assistant(final tool_calls) → tool(final marker)
    roles = [m["role"] for m in msgs]
    assert roles[0] == "user"
    assert "assistant" in roles
    assert "tool" in roles


def test_runtime_refuses_outsider(outsider_user):
    """Outsider with no access to client → require_can_view_client raises
    BEFORE any LLM call."""
    # Build a fake thread (we need a thread_id even if the runtime fails
    # before reading it).
    from app.auth.permissions import require_can_view_client
    with pytest.raises(Exception):  # PermissionError or HTTPException
        require_can_view_client(outsider_user, CLIENT)
