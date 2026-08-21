"""Stage D: LLM-driven parser-mapping fallback.

LLM API isn't called in tests — we monkeypatch `openai.OpenAI` to return
canned responses. Validates the contract (request shape, response parsing,
schema validation, budget enforcement, signature stability).
"""
from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from hub.app import llm, settings_store
from hub.app.parsers._excel import compute_file_signature


# ---------------------------------------------------------------------------
# settings_store
# ---------------------------------------------------------------------------

def test_settings_get_falls_back_to_default():
    assert settings_store.get("nonexistent_key", "default") == "default"


def test_settings_set_then_get_roundtrip():
    settings_store.set_many({"_test_key": "hello"})
    try:
        assert settings_store.get("_test_key") == "hello"
    finally:
        # Clean up
        from hub.app.database import connect
        with connect() as c:
            with c.cursor() as cur:
                cur.execute("delete from hub.app_settings where key='_test_key'")


def test_settings_get_int_recovers_from_bad_value():
    settings_store.set_many({"_test_int": "not-a-number"})
    try:
        assert settings_store.get_int("_test_int", 42) == 42
    finally:
        from hub.app.database import connect
        with connect() as c:
            with c.cursor() as cur:
                cur.execute("delete from hub.app_settings where key='_test_int'")


# ---------------------------------------------------------------------------
# compute_file_signature
# ---------------------------------------------------------------------------

def test_signature_is_stable_for_same_shape():
    a = compute_file_signature(client_id="x", module="bcct",
                               headers_per_sheet=[["A", "B", "C"]])
    b = compute_file_signature(client_id="x", module="bcct",
                               headers_per_sheet=[["A", "B", "C"]])
    assert a == b


def test_signature_invariant_under_column_order():
    a = compute_file_signature(client_id="x", module="bcct",
                               headers_per_sheet=[["A", "B", "C"]])
    b = compute_file_signature(client_id="x", module="bcct",
                               headers_per_sheet=[["C", "A", "B"]])
    assert a == b


def test_signature_changes_with_header_set():
    a = compute_file_signature(client_id="x", module="bcct",
                               headers_per_sheet=[["A", "B", "C"]])
    b = compute_file_signature(client_id="x", module="bcct",
                               headers_per_sheet=[["A", "B", "D"]])
    assert a != b


def test_signature_is_client_scoped():
    """Two clients with the same headers → different signatures.
    This prevents cross-client cache poisoning."""
    a = compute_file_signature(client_id="growatt", module="bcct",
                               headers_per_sheet=[["A", "B"]])
    b = compute_file_signature(client_id="dke", module="bcct",
                               headers_per_sheet=[["A", "B"]])
    assert a != b


def test_signature_is_module_scoped():
    a = compute_file_signature(client_id="x", module="bcct",
                               headers_per_sheet=[["A", "B"]])
    b = compute_file_signature(client_id="x", module="bom",
                               headers_per_sheet=[["A", "B"]])
    assert a != b


# ---------------------------------------------------------------------------
# LLM client (mocked OpenAI)
# ---------------------------------------------------------------------------

@pytest.fixture
def cfg_enabled():
    return llm.LLMConfig(
        base_url="https://example.invalid/v1",
        model="claude-sonnet-4-6",
        api_key="test-key",
        temperature=0.0,
        timeout_s=10,
        max_retries=1,
        max_calls_per_day_per_client=10,
    )


def _mock_openai_response(content: str):
    fake_completion = MagicMock()
    fake_completion.choices = [MagicMock()]
    fake_completion.choices[0].message.content = content
    fake_client = MagicMock()
    fake_client.chat.completions.create.return_value = fake_completion
    return fake_client


def _mock_openai_responses(contents: list[str]):
    """Yield each content string on successive calls (for self-correction
    retry loop testing)."""
    completions = []
    for c in contents:
        comp = MagicMock()
        comp.choices = [MagicMock()]
        comp.choices[0].message.content = c
        completions.append(comp)
    fake_client = MagicMock()
    fake_client.chat.completions.create.side_effect = completions
    return fake_client


def test_propose_returns_mapping_when_llm_responds_valid(cfg_enabled):
    response_json = json.dumps({
        "mapping": {
            "Số TK": "declaration_no",
            "Ngày ĐK": "registration_date",
            "Mã hàng": "customs_code",
        }
    })
    with patch("openai.OpenAI", return_value=_mock_openai_response(response_json)):
        result = llm.propose_header_mapping(
            client_id="growatt-vn", module="bcct",
            headers=["Số TK", "Ngày ĐK", "Mã hàng", "Junk col"],
            sample_rows=[["123", "2025-01-01", "X", "y"]],
            cfg=cfg_enabled,
        )
    assert result == {
        "Số TK": "declaration_no",
        "Ngày ĐK": "registration_date",
        "Mã hàng": "customs_code",
    }


def test_propose_drops_partial_invalid_silently(cfg_enabled):
    """LLM hallucinated ONE field but kept others valid → keep the valid
    ones, drop the invalid silently (no retry needed if any valid pair
    exists)."""
    response_json = json.dumps({
        "mapping": {
            "Số TK": "declaration_no",      # valid
            "Junk": "made_up_field",         # invalid header AND field
        }
    })
    with patch("openai.OpenAI", return_value=_mock_openai_response(response_json)):
        result = llm.propose_header_mapping(
            client_id="growatt-vn", module="bcct",
            headers=["Số TK"], sample_rows=[["123"]],
            cfg=cfg_enabled,
        )
    assert result == {"Số TK": "declaration_no"}


def test_propose_self_corrects_when_first_attempt_all_invalid(cfg_enabled):
    """ALL mappings invalid → retry with feedback. LLM gets it right
    on the second attempt. Demonstrates the self-correction loop."""
    bad = json.dumps({"mapping": {"Hallucinated col": "made_up_field"}})
    good = json.dumps({"mapping": {"Số TK": "declaration_no"}})
    with patch("openai.OpenAI",
               return_value=_mock_openai_responses([bad, good])):
        result = llm.propose_header_mapping(
            client_id="growatt-vn", module="bcct",
            headers=["Số TK"], sample_rows=[["123"]],
            cfg=cfg_enabled,
        )
    assert result == {"Số TK": "declaration_no"}


def test_propose_raises_after_max_retries(cfg_enabled):
    """If LLM never returns valid mapping, raise after max_retries+1 attempts."""
    bad = json.dumps({"mapping": {"Hallucinated col": "made_up_field"}})
    with patch("openai.OpenAI",
               return_value=_mock_openai_responses([bad, bad, bad])):
        with pytest.raises(llm.LLMProposalError):
            llm.propose_header_mapping(
                client_id="growatt-vn", module="bcct",
                headers=["Số TK"], sample_rows=[["123"]],
                cfg=cfg_enabled,
            )


def test_propose_raises_on_malformed_json(cfg_enabled):
    with patch("openai.OpenAI", return_value=_mock_openai_response("not json at all")):
        with pytest.raises(llm.LLMProposalError):
            llm.propose_header_mapping(
                client_id="growatt-vn", module="bcct",
                headers=["Số TK"], sample_rows=[["123"]],
                cfg=cfg_enabled,
            )


def test_propose_raises_when_llm_disabled():
    cfg = llm.LLMConfig(base_url="", model="", api_key="", temperature=0.0,
                        timeout_s=10, max_retries=1,
                        max_calls_per_day_per_client=10)
    with pytest.raises(llm.LLMUnavailable):
        llm.propose_header_mapping(
            client_id="growatt-vn", module="bcct",
            headers=["X"], sample_rows=[["y"]], cfg=cfg,
        )


def test_propose_enforces_per_client_daily_budget(cfg_enabled):
    """When call_count exceeds max_calls_per_day_per_client → raise."""
    from hub.app.database import connect
    from datetime import date

    cfg = llm.LLMConfig(
        base_url="https://example.invalid/v1", model="claude-sonnet-4-6",
        api_key="test-key", temperature=0.0, timeout_s=10, max_retries=1,
        max_calls_per_day_per_client=2,
    )
    response_json = json.dumps({"mapping": {}})

    # Pre-seed 2 prior calls today for growatt-vn
    with connect() as c:
        with c.cursor() as cur:
            cur.execute(
                """
                insert into hub.llm_usage (date, client_id, call_count)
                values (%s, 'growatt-vn', 2)
                on conflict (date, client_id) do update set call_count = 2
                """,
                (date.today(),),
            )
    try:
        with patch("openai.OpenAI", return_value=_mock_openai_response(response_json)):
            with pytest.raises(llm.LLMUnavailable, match="budget exceeded"):
                llm.propose_header_mapping(
                    client_id="growatt-vn", module="bcct",
                    headers=["X"], sample_rows=[["y"]], cfg=cfg,
                )
    finally:
        with connect() as c:
            with c.cursor() as cur:
                cur.execute("delete from hub.llm_usage where client_id='growatt-vn' and date = current_date")


def test_list_models_returns_sorted_unique(cfg_enabled):
    """list_models surfaces /v1/models output, deduped + sorted."""
    fake_models = MagicMock()
    fake_models.data = [
        MagicMock(id="gpt-4o-mini"),
        MagicMock(id="claude-sonnet-4-6"),
        MagicMock(id="gpt-4o-mini"),  # dup
        MagicMock(id="llama-3.1-8b"),
    ]
    fake_client = MagicMock()
    fake_client.models.list.return_value = fake_models
    with patch("openai.OpenAI", return_value=fake_client):
        result = llm.list_models(cfg_enabled)
    assert result == ["claude-sonnet-4-6", "gpt-4o-mini", "llama-3.1-8b"]


def test_list_models_raises_when_disabled():
    cfg = llm.LLMConfig(base_url="", model="", api_key="", temperature=0.0,
                        timeout_s=10, max_retries=1,
                        max_calls_per_day_per_client=10)
    with pytest.raises(llm.LLMUnavailable):
        llm.list_models(cfg)


def test_list_models_raises_proposal_error_on_endpoint_failure(cfg_enabled):
    fake_client = MagicMock()
    fake_client.models.list.side_effect = RuntimeError("404 Not Found")
    with patch("openai.OpenAI", return_value=fake_client):
        with pytest.raises(llm.LLMProposalError, match="List models failed"):
            llm.list_models(cfg_enabled)


def test_propose_increments_usage_counter(cfg_enabled):
    from hub.app.database import connect
    from datetime import date

    response_json = json.dumps({"mapping": {}})
    test_client = "growatt-vn"

    with connect() as c:
        with c.cursor() as cur:
            cur.execute(
                "delete from hub.llm_usage where date = current_date and client_id=%s",
                (test_client,),
            )

    try:
        with patch("openai.OpenAI", return_value=_mock_openai_response(response_json)):
            llm.propose_header_mapping(
                client_id=test_client, module="bcct",
                headers=["X"], sample_rows=[["y"]], cfg=cfg_enabled,
            )
        with connect() as c:
            with c.cursor() as cur:
                cur.execute(
                    "select call_count from hub.llm_usage where date=current_date and client_id=%s",
                    (test_client,),
                )
                (n,) = cur.fetchone()
                assert n == 1
    finally:
        with connect() as c:
            with c.cursor() as cur:
                cur.execute(
                    "delete from hub.llm_usage where date=current_date and client_id=%s",
                    (test_client,),
                )
