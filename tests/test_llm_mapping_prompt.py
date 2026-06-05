"""Phase 4: smarter LLM column mapping.

- propose_header_mapping sends per-field definitions + abstain/magnitude
  guidance to the model.
- the suggestion merge only FILLS unresolved columns, never overrides a
  confident rigid match.
"""
from __future__ import annotations

from app import llm
from app.routes._mapping_flow import _merge_llm_into_unresolved


def test_merge_only_fills_unresolved():
    cols = [
        {"header": "Số tờ khai", "proposed": "declaration_no"},  # rigid OK
        {"header": "Cột lạ", "proposed": ""},                     # unresolved
    ]
    _merge_llm_into_unresolved(
        cols, {"Số tờ khai": "customs_code", "Cột lạ": "goods_name"})
    # rigid match preserved, NOT overridden by the LLM
    assert cols[0]["proposed"] == "declaration_no"
    # gap filled from the LLM
    assert cols[1]["proposed"] == "goods_name"


def test_propose_sends_definitions_and_abstain(monkeypatch):
    captured: dict = {}

    class FakeCompletions:
        def create(self, **kw):
            captured.update(kw)
            msg = type("M", (), {
                "content": '{"mapping": {"Đơn giá tính thuế": "unit_price"}}'})()
            choice = type("C", (), {"message": msg})()
            return type("R", (), {"choices": [choice]})()

    class FakeOpenAI:
        def __init__(self, **kw):
            self.chat = type("Chat", (), {"completions": FakeCompletions()})()

    import openai
    monkeypatch.setattr(openai, "OpenAI", FakeOpenAI)
    monkeypatch.setattr(llm, "_check_and_record_budget", lambda *a, **k: None)

    cfg = llm.LLMConfig(base_url="http://x/v1", model="m", api_key="k",
                        temperature=0.0, timeout_s=5, max_retries=1,
                        max_calls_per_day_per_client=50)
    out = llm.propose_header_mapping(
        client_id="c", module="bcct",
        headers=["Đơn giá tính thuế", "Đơn giá"],
        sample_rows=[["10136289.92", "380.7"]], cfg=cfg)

    assert out == {"Đơn giá tính thuế": "unit_price"}
    sys_msg = captured["messages"][0]["content"]
    user_msg = captured["messages"][1]["content"]
    # magnitude + abstain guidance present
    assert "ABSTAIN" in sys_msg
    assert "exchange_rate" in sys_msg
    # per-field definitions reached the model
    assert "field_definitions" in user_msg
    assert "unit_price_nt" in user_msg
