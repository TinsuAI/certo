from __future__ import annotations

from fastapi import HTTPException, Request

from app import co_auth


async def large_request_form(request: Request):
    try:
        return await request.form(max_fields=100000, max_files=2000)
    except TypeError:
        return await request.form()


def require_local_source_writes() -> None:
    if co_auth.data_hub_source_mode_enabled():
        raise HTTPException(
            status_code=409,
            detail="Shared source data is read-only in CO when DATA_HUB_ENABLED is active. Use Data Hub for source changes.",
        )
