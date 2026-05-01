"""Admin-tunable settings backed by `hub.app_settings`.

Pattern mirrors `~/workspace/client/BCQT-System/app/settings_store.py`. Kept
deliberately thin: get / set / get_many, all string values; callers coerce
to int/float as needed so a bad value never crashes the call site (the
caller falls back to a constant default).

Not meant for per-client knobs (those live in `hub.clients`). Not meant
for secrets in a multi-tenant deployment — single-tenant trusted-admin
model is acceptable for hub MVP. Multi-tenant rewrite needs a real
secrets store.
"""
from __future__ import annotations

import logging
from typing import Iterable

from app.database import connect

logger = logging.getLogger(__name__)

# Keys consumed by `app/llm.py`; kept here so the settings UI and the
# read-through code agree on what's tunable.
LLM_KEYS: tuple[str, ...] = (
    "llm_base_url",
    "llm_model",
    "llm_api_key",
    "llm_temperature",
    "llm_timeout_s",
    "llm_max_retries",
    "llm_max_calls_per_day_per_client",
)


def get(key: str, default: str | None = None) -> str | None:
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute("select value from hub.app_settings where key = %s", (key,))
            row = cur.fetchone()
    return row[0] if row and row[0] is not None else default


def get_many(keys: Iterable[str]) -> dict[str, str]:
    keys_t = tuple(keys)
    if not keys_t:
        return {}
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "select key, value from hub.app_settings where key = any(%s)",
                (list(keys_t),),
            )
            return {k: v for k, v in cur.fetchall() if v is not None}


def set_many(values: dict[str, str], *, updated_by: str | None = None) -> None:
    if not values:
        return
    with connect() as conn:
        with conn.cursor() as cur:
            for key, val in values.items():
                cur.execute(
                    """
                    insert into hub.app_settings (key, value, updated_at, updated_by)
                    values (%s, %s, now(), %s)
                    on conflict (key) do update
                      set value = excluded.value,
                          updated_at = now(),
                          updated_by = excluded.updated_by
                    """,
                    (key, val, updated_by),
                )


def get_int(key: str, default: int) -> int:
    raw = get(key)
    if raw is None or raw == "":
        return default
    try:
        return int(raw)
    except (TypeError, ValueError):
        logger.warning("settings_store.get_int(%r): bad value %r, using default %r",
                       key, raw, default)
        return default


def get_float(key: str, default: float) -> float:
    raw = get(key)
    if raw is None or raw == "":
        return default
    try:
        return float(raw)
    except (TypeError, ValueError):
        logger.warning("settings_store.get_float(%r): bad value %r, using default %r",
                       key, raw, default)
        return default
