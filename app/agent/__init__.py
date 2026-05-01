"""Chat-agent package.

A tool-using LLM agent scoped to a single (user, client) pair. The
agent's only data access is via curated tools that re-verify the user's
permission to view the client_id on every call. The LLM never sees the
client_id directly — it's threaded by the runtime — so even a
prompt-injection couldn't trick it into reaching another client's data.

Pattern lifted from BCQT-System with Data Hub-specific tools (BCCT /
catalog / BOM / provenance alarms).

Structure:
- tools.py — TOOL_DEFINITIONS (OpenAI function-calling shape) +
  dispatch_tool(user, client_id, name, args)
- runtime.py — run_turn(thread_id, user, client_id, user_message)
- store.py — DB helpers for threads + messages
"""
