"""Per-client master config UI (declaration types + fiscal year).

Mounted at /clients/{client_id}/declaration-config. Edit gated by
can_edit_client_config. Save bumps config_version + recomputes
config_hash via app.stores.client_config.upsert().
"""
from __future__ import annotations

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from hub.app import auth
from hub.app.routes.clients import get_client, stats_for_client
from hub.app.stores import client_config, client_type_presets, declaration_types

router = APIRouter()


def _csv_to_codes(raw: str) -> list[str]:
    """Parse comma/space/newline separated codes."""
    if not raw:
        return []
    out: list[str] = []
    buf = ""
    for ch in raw:
        if ch in ",;\n\r\t ":
            if buf.strip():
                out.append(buf.strip())
            buf = ""
        else:
            buf += ch
    if buf.strip():
        out.append(buf.strip())
    return out


@router.get("/clients/{client_id}/declaration-config", response_class=HTMLResponse)
async def declaration_config_view(request: Request, client_id: str,
                                   saved: bool = False, error: str | None = None):
    user = auth.require_user(request)
    if not auth.can_view_client(user, client_id):
        raise HTTPException(403, "forbidden")
    client = get_client(client_id)
    if not client:
        raise HTTPException(404, "Client not found")
    cfg = client_config.get_or_default(client_id)
    presets = client_type_presets.list_all(only_active=True)
    imports = declaration_types.list_all(only_active=True, direction="import")
    exports = declaration_types.list_all(only_active=True, direction="export")
    return request.app.state.templates.TemplateResponse(
        request, "clients/declaration_config.html",
        {
            "client": client,
            "stats": stats_for_client(client_id),
            "cfg": cfg,
            "presets": presets,
            "import_codes": imports,
            "export_codes": exports,
            "saved": saved,
            "error": error,
            "active_root": "clients",
            "active_tab": "config",
            "can_edit": auth.can_edit_client_config(user, client_id),
        },
    )


@router.post("/clients/{client_id}/declaration-config")
async def declaration_config_submit(
    request: Request, client_id: str,
    eligible_import_declaration_types: list[str] = Form(default_factory=list),
    relevant_export_declaration_types: list[str] = Form(default_factory=list),
    fiscal_year_start_month: int = Form(1),
    extra_eligible_import: str = Form(""),
    extra_relevant_export: str = Form(""),
):
    """Manual save → preset_key cleared (becomes 'tự cấu hình').

    Once staff edits the lists by hand, the snapshot no longer faithfully
    reflects a preset, so we drop the preset_key. To re-link to a preset,
    use the apply-preset button instead.
    """
    user = auth.require_user(request)
    if not auth.can_edit_client_config(user, client_id):
        raise HTTPException(403, "forbidden")
    if not get_client(client_id):
        raise HTTPException(404, "Client not found")
    eligible = list(eligible_import_declaration_types) + _csv_to_codes(extra_eligible_import)
    relevant = list(relevant_export_declaration_types) + _csv_to_codes(extra_relevant_export)
    try:
        client_config.upsert(
            client_id=client_id,
            preset_key=None,  # manual save = self-config, drop the preset link
            eligible_import_declaration_types=eligible,
            relevant_export_declaration_types=relevant,
            fiscal_year_start_month=fiscal_year_start_month,
            user_id=user.user_id,
        )
    except ValueError as exc:
        return RedirectResponse(
            url=f"/clients/{client_id}/declaration-config?error={exc}",
            status_code=303,
        )
    return RedirectResponse(
        url=f"/clients/{client_id}/declaration-config?saved=1",
        status_code=303,
    )


@router.post("/clients/{client_id}/declaration-config/apply-preset")
async def declaration_config_apply_preset(
    request: Request, client_id: str,
    preset_key: str = Form(...),
):
    user = auth.require_user(request)
    if not auth.can_edit_client_config(user, client_id):
        raise HTTPException(403, "forbidden")
    if not get_client(client_id):
        raise HTTPException(404, "Client not found")
    try:
        client_config.apply_preset(client_id, preset_key, user_id=user.user_id)
    except ValueError as exc:
        return RedirectResponse(
            url=f"/clients/{client_id}/declaration-config?error={exc}",
            status_code=303,
        )
    return RedirectResponse(
        url=f"/clients/{client_id}/declaration-config?saved=1",
        status_code=303,
    )
