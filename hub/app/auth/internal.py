"""Marks calls that originate inside this process.

CO and Data Hub are one process now, so a bridged read carries no bearer —
there is nobody left for CO to prove itself to. The API cannot simply stop
checking, though: the same routes are still served to the outside at
/hub/v1/hub/*. This flag distinguishes the two, and it is set by the in-process
transport rather than by a header, so an external request cannot forge it.
"""
from __future__ import annotations

from contextvars import ContextVar

INTERNAL_CALL: ContextVar[bool] = ContextVar("data_hub_internal_call", default=False)


def is_internal_call() -> bool:
    return INTERNAL_CALL.get()
