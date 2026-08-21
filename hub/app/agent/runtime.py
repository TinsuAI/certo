"""Agent loop runtime.

Single entry point: `run_turn(thread_id, user, client_id, user_text)`.
Persists the user message, then runs an LLM-tool loop until the model
calls `submit_final_answer` or hits the round/tool budget.

Strict ACL: client_id is bound to the runtime call, NEVER read from
LLM message content. Each tool call passes through `dispatch_tool`
which re-verifies the user's permission to view client_id (defense
in depth — even if the LLM is prompt-injected to claim a different
client, the tool layer ignores that).
"""
from __future__ import annotations

import json
import logging
from typing import Any

from hub.app import auth, settings_store
from hub.app.agent import store, tools
from hub.app.llm import LLMConfig, LLMUnavailable, _check_and_record_budget

logger = logging.getLogger(__name__)


# Conservative budgets. Tune from production metrics later.
MAX_ROUNDS = 6   # LLM completion calls per turn
MAX_TOOL_CALLS = 12  # tool calls per turn

def _parse_tool_args(raw: str) -> tuple[dict, str | None]:
    """Robust args parser for the tool-call `arguments` string.

    Some OpenAI-compat endpoints (vLLM grammar mode, certain local
    servers under reasoning_effort) emit duplicated/concatenated JSON
    objects (e.g. `{"a":1}{"a":1}{"a":1}`). Attempt the simple parse
    first, then fall back to JSONDecoder.raw_decode which reads ONE
    object and stops; we use that object."""
    raw = (raw or "").strip()
    if not raw:
        return {}, None
    # Happy path
    try:
        v = json.loads(raw)
        return (v, None) if isinstance(v, dict) else ({}, "not an object")
    except json.JSONDecodeError:
        pass
    # Tolerate duplicated-concat: read first JSON object only.
    try:
        decoder = json.JSONDecoder()
        v, _idx = decoder.raw_decode(raw)
        if isinstance(v, dict):
            return v, None
        return {}, "not an object"
    except json.JSONDecodeError as e:
        return {}, str(e)


SYSTEM_PROMPT_TEMPLATE = """You are Data Hub's data-analyst assistant for one customs-compliance client at a time.

Hard rules:
1. Only answer about CLIENT_ID = `{client_id}`. Do NOT answer questions about other clients. If user asks about other clients, refuse politely.
2. Verify before stating numbers. Always call a tool to confirm a fact, even if it sounds obvious.
3. Use the smallest scope possible: filter by year / declaration / customs_code when the user is specific.
4. For business-rule, architecture, domain-term, or "what does X mean" questions, call `lookup_glossary` or `search_knowledge_base` before answering.
5. Reply in Vietnamese unless the user wrote English.
6. Cite the tool result you used in your final answer (e.g. "Theo query_bcct, có 5 tờ khai...").
7. End every turn by calling `submit_final_answer` with the user-facing reply text.
8. Never invent customs codes, declaration numbers, counts, regulations, or system behavior. If tools or knowledge search do not support the answer, say what is unknown.

Tools available:
- query_bcct — customs declarations
- query_catalog — material registry
- query_bom — bills of materials
- query_provenance_alarms — codes seen on BCCT but not registered
- query_uploads — file upload history (when, who, parse_status)
- query_bcct_history — per-row audit log (who changed what when)
- lookup_glossary — customs / domain term definitions
- search_knowledge_base — project glossary, decisions, and feature notes
- submit_final_answer — terminator
"""


def run_turn(*, thread_id: str, user, client_id: str, user_text: str,
             cfg: LLMConfig | None = None) -> str:
    """Append the user's message, run the agent loop, return the final
    answer text. Idempotent on failure: tool errors become tool-result
    messages so the LLM can adapt; runtime errors raise."""
    if not settings_store.chat_agent_enabled():
        raise LLMUnavailable("Chat Agent is disabled in technical settings.")

    cfg = cfg or LLMConfig.load()
    if not cfg.is_enabled():
        raise LLMUnavailable("LLM not configured. Set keys at /admin/settings/technical.")

    # Defense: re-verify permission before any LLM call.
    auth.require_can_view_client(user, client_id)

    # Persist user turn.
    store.append_message(thread_id=thread_id, role="user", content=user_text)

    # Build messages: system + history.
    history = store.list_messages(thread_id=thread_id)
    messages: list[dict[str, Any]] = [
        {"role": "system",
         "content": SYSTEM_PROMPT_TEMPLATE.format(client_id=client_id)},
    ]
    messages.extend(store.to_openai_messages(history))

    from openai import OpenAI
    oai = OpenAI(
        base_url=cfg.base_url,
        api_key=cfg.api_key or "not-needed",
        timeout=cfg.timeout_s,
        max_retries=cfg.max_retries,
    )

    rounds = 0
    tool_calls_total = 0
    final_answer: str | None = None

    while rounds < MAX_ROUNDS and final_answer is None:
        rounds += 1
        _check_and_record_budget(client_id, cfg)
        try:
            completion = oai.chat.completions.create(
                model=cfg.model,
                messages=messages,
                tools=tools.tool_definitions_for_user(user),
                temperature=cfg.temperature,
            )
        except Exception as e:  # noqa: BLE001
            logger.exception("agent.run_turn: LLM call raised")
            err = f"LLM error ({type(e).__name__}). Vui lòng thử lại."
            store.append_message(thread_id=thread_id, role="assistant",
                                 content=err)
            return err

        msg = completion.choices[0].message
        # Persist + push the assistant turn.
        assistant_content = msg.content or ""
        tc_list = []
        if getattr(msg, "tool_calls", None):
            tc_list = [
                {
                    "id": tc.id,
                    "type": "function",
                    "function": {
                        "name": tc.function.name,
                        "arguments": tc.function.arguments,
                    },
                }
                for tc in msg.tool_calls
            ]
        store.append_message(
            thread_id=thread_id, role="assistant",
            content=assistant_content, tool_calls=tc_list or None,
        )
        messages.append({
            "role": "assistant",
            "content": assistant_content,
            **({"tool_calls": tc_list} if tc_list else {}),
        })

        if not tc_list:
            # No tool call → LLM gave a direct answer. Treat as final.
            final_answer = assistant_content or "(Không có nội dung)"
            break

        # Dispatch each tool call. submit_final_answer terminates the loop.
        for tc in tc_list:
            tool_calls_total += 1
            if tool_calls_total > MAX_TOOL_CALLS:
                final_answer = (
                    "Đã quá giới hạn số lần gọi tool trong 1 lượt. "
                    "Hãy thử chia câu hỏi nhỏ hơn."
                )
                store.append_message(
                    thread_id=thread_id, role="assistant",
                    content=final_answer,
                )
                break

            name = tc["function"]["name"]
            raw_args = tc["function"]["arguments"] or "{}"
            args, args_parse_error = _parse_tool_args(raw_args)
            if args_parse_error is not None:
                # Surface to the LLM as a tool result so it can retry
                # with valid args. Don't dispatch with args={}.
                store.append_message(
                    thread_id=thread_id, role="tool",
                    content=json.dumps(
                        {"ok": False,
                         "error": f"argument parse error: {args_parse_error}. "
                                  f"Send valid JSON object only, no extra text."},
                        ensure_ascii=False,
                    ),
                    tool_call_id=tc["id"], tool_name=name,
                )
                messages.append({
                    "role": "tool",
                    "tool_call_id": tc["id"],
                    "name": name,
                    "content": json.dumps(
                        {"ok": False, "error": "bad arguments"},
                        ensure_ascii=False,
                    ),
                })
                continue

            if name == "submit_final_answer":
                final_answer = (args.get("answer") or "").strip() or "(Trống)"
                # Persist a tool-result row so history is complete.
                store.append_message(
                    thread_id=thread_id, role="tool",
                    content=json.dumps({"ok": True, "final": True},
                                       ensure_ascii=False),
                    tool_call_id=tc["id"], tool_name=name,
                )
                # Persist a final assistant message with the user-facing
                # answer text so the chat UI renders it cleanly. Without
                # this row, the answer is buried inside tool_calls JSON
                # and the conversation appears blank.
                store.append_message(
                    thread_id=thread_id, role="assistant",
                    content=final_answer,
                )
                break

            result = tools.dispatch_tool(
                user=user, client_id=client_id,
                name=name, args=args,
            )
            result_str = json.dumps(result, ensure_ascii=False, default=str)
            store.append_message(
                thread_id=thread_id, role="tool",
                content=result_str,
                tool_call_id=tc["id"], tool_name=name,
            )
            messages.append({
                "role": "tool",
                "tool_call_id": tc["id"],
                "name": name,
                "content": result_str,
            })

    if final_answer is None:
        final_answer = (
            "Đã đạt giới hạn vòng lặp mà chưa có câu trả lời. "
            "Hãy thử hỏi cụ thể hơn."
        )
        store.append_message(
            thread_id=thread_id, role="assistant", content=final_answer,
        )

    return final_answer
