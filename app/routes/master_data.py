"""Admin UIs for master data: declaration type catalog + client type presets.

Both gated to dev/admin (can_manage_users). Lists, create, edit, disable.
System presets cannot be deleted; user presets can.
"""
from __future__ import annotations

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from app import auth
from app.stores import client_type_presets, declaration_types

router = APIRouter()


def _csv_to_codes(raw: str) -> list[str]:
    """Parse a comma/space/newline separated list of codes."""
    if not raw:
        return []
    parts: list[str] = []
    buf = ""
    for ch in raw:
        if ch in ",;\n\r\t ":
            if buf.strip():
                parts.append(buf.strip())
            buf = ""
        else:
            buf += ch
    if buf.strip():
        parts.append(buf.strip())
    return parts


# ── Declaration type catalog ───────────────────────────────────────────

@router.get("/admin/declaration-types", response_class=HTMLResponse)
async def declaration_types_view(request: Request, error: str | None = None,
                                 saved: bool = False):
    user = auth.require_user(request)
    if not auth.can_manage_users(user):
        raise HTTPException(403, "forbidden")
    rows = declaration_types.list_all()
    return request.app.state.templates.TemplateResponse(
        request, "admin/declaration_types.html",
        {"rows": rows, "error": error, "saved": saved,
         "active_root": "admin"},
    )


@router.post("/admin/declaration-types/new")
async def declaration_types_create(
    request: Request,
    code: str = Form(...),
    direction: str = Form(...),
    description: str = Form(""),
    notes: str = Form(""),
):
    user = auth.require_user(request)
    if not auth.can_manage_users(user):
        raise HTTPException(403, "forbidden")
    try:
        declaration_types.create(
            code=code, direction=direction, description=description,
            notes=notes, user_id=user.user_id,
        )
    except ValueError as exc:
        return RedirectResponse(
            url=f"/admin/declaration-types?error={exc}", status_code=303,
        )
    except Exception:
        return RedirectResponse(
            url="/admin/declaration-types?error=duplicate", status_code=303,
        )
    return RedirectResponse(url="/admin/declaration-types?saved=1", status_code=303)


@router.post("/admin/declaration-types/{code}/update")
async def declaration_types_update(
    request: Request, code: str,
    direction: str = Form(""),
    description: str = Form(""),
    notes: str = Form(""),
    is_active: str = Form("true"),
):
    user = auth.require_user(request)
    if not auth.can_manage_users(user):
        raise HTTPException(403, "forbidden")
    try:
        declaration_types.update(
            code,
            direction=direction or None,
            description=description,
            notes=notes,
            is_active=(is_active.strip().lower() == "true"),
            user_id=user.user_id,
        )
    except ValueError as exc:
        return RedirectResponse(
            url=f"/admin/declaration-types?error={exc}", status_code=303,
        )
    return RedirectResponse(url="/admin/declaration-types?saved=1", status_code=303)


# ── Client type presets ────────────────────────────────────────────────

@router.get("/admin/client-type-presets", response_class=HTMLResponse)
async def presets_view(request: Request, error: str | None = None,
                       saved: bool = False):
    user = auth.require_user(request)
    if not auth.can_manage_users(user):
        raise HTTPException(403, "forbidden")
    rows = client_type_presets.list_all()
    return request.app.state.templates.TemplateResponse(
        request, "admin/client_type_presets.html",
        {"rows": rows, "error": error, "saved": saved,
         "active_root": "admin"},
    )


@router.post("/admin/client-type-presets/new")
async def presets_create(
    request: Request,
    preset_key: str = Form(...),
    display_name: str = Form(...),
    default_eligible_import: str = Form(""),
    default_relevant_export: str = Form(""),
    notes: str = Form(""),
):
    user = auth.require_user(request)
    if not auth.can_manage_users(user):
        raise HTTPException(403, "forbidden")
    try:
        client_type_presets.create(
            preset_key=preset_key,
            display_name=display_name,
            default_eligible_import=_csv_to_codes(default_eligible_import),
            default_relevant_export=_csv_to_codes(default_relevant_export),
            notes=notes,
            user_id=user.user_id,
        )
    except ValueError as exc:
        return RedirectResponse(
            url=f"/admin/client-type-presets?error={exc}", status_code=303,
        )
    except Exception:
        return RedirectResponse(
            url="/admin/client-type-presets?error=duplicate", status_code=303,
        )
    return RedirectResponse(url="/admin/client-type-presets?saved=1", status_code=303)


@router.post("/admin/client-type-presets/{preset_key}/update")
async def presets_update(
    request: Request, preset_key: str,
    display_name: str = Form(""),
    default_eligible_import: str = Form(""),
    default_relevant_export: str = Form(""),
    notes: str = Form(""),
    is_active: str = Form("true"),
):
    user = auth.require_user(request)
    if not auth.can_manage_users(user):
        raise HTTPException(403, "forbidden")
    try:
        client_type_presets.update(
            preset_key,
            display_name=display_name or None,
            default_eligible_import=_csv_to_codes(default_eligible_import),
            default_relevant_export=_csv_to_codes(default_relevant_export),
            notes=notes,
            is_active=(is_active.strip().lower() == "true"),
            user_id=user.user_id,
        )
    except ValueError as exc:
        return RedirectResponse(
            url=f"/admin/client-type-presets?error={exc}", status_code=303,
        )
    return RedirectResponse(
        url="/admin/client-type-presets?saved=1", status_code=303,
    )


@router.post("/admin/client-type-presets/{preset_key}/delete")
async def presets_delete(request: Request, preset_key: str):
    user = auth.require_user(request)
    if not auth.can_manage_users(user):
        raise HTTPException(403, "forbidden")
    try:
        client_type_presets.delete(preset_key, user_id=user.user_id)
    except ValueError as exc:
        return RedirectResponse(
            url=f"/admin/client-type-presets?error={exc}", status_code=303,
        )
    return RedirectResponse(
        url="/admin/client-type-presets?saved=1", status_code=303,
    )


# ── UoM standards (canonical + aliases) ────────────────────────────────

@router.get("/admin/uom", response_class=HTMLResponse)
async def uom_view(request: Request, error: str | None = None,
                   saved: bool = False):
    user = auth.require_user(request)
    if not auth.can_manage_users(user):
        raise HTTPException(403, "forbidden")
    from collections import defaultdict
    from app.stores import uom_standards
    from app.stores.uom import _TIER_A_FAMILIES
    canonicals = uom_standards.list_canonicals_with_alias_count()
    aliases = uom_standards.list_aliases()

    # Group synonym aliases under their canonical (skip the self-alias).
    syn_by_code: dict[str, list[str]] = defaultdict(list)
    for a in aliases:
        if a["alias_norm"] != a["uom_code"]:
            syn_by_code[a["uom_code"]].append(a["alias_norm"])

    for c in canonicals:
        c["aliases"] = syn_by_code.get(c["uom_code"], [])
        c["factor_disp"] = uom_standards.format_factor(c["base_factor"])
        c["is_base"] = float(c["base_factor"]) == 1.0

    # Group canonicals by family. A family is either "scaled" (real
    # numeric conversion via base_factor: mass/length/area/volume) or
    # "count" (discrete units, all base_factor 1, treated 1:1 in-family —
    # count/count_packaging/assembly). The two are presented differently.
    fam_map: dict[str, list[dict]] = defaultdict(list)
    for c in canonicals:
        fam_map[c["family"]].append(c)
    families = []
    # Scaled families first (they carry the conversion teaching value),
    # then count-like families; alpha within each group.
    for fam in sorted(fam_map, key=lambda f: (f in _TIER_A_FAMILIES, f)):
        items = sorted(fam_map[fam], key=lambda c: (not c["is_base"], c["uom_code"]))
        base_unit = next((c["uom_code"] for c in items if c["is_base"]), None)
        families.append({
            "name": fam,
            "is_count": fam in _TIER_A_FAMILIES,
            "base_unit": base_unit,
            "canonicals": items,
            "n": len(items),
        })

    return request.app.state.templates.TemplateResponse(
        request, "admin/uom.html",
        {"families": families, "canonicals": canonicals, "aliases": aliases,
         "valid_families": sorted(uom_standards.VALID_FAMILIES),
         "n_families": len(families),
         "error": error, "saved": saved,
         "active_root": "admin"},
    )


@router.post("/admin/uom/canonical/new")
async def uom_canonical_new(
    request: Request,
    uom_code: str = Form(...),
    family: str = Form(...),
    base_factor: str = Form("1"),
):
    user = auth.require_user(request)
    if not auth.can_manage_users(user):
        raise HTTPException(403, "forbidden")
    from app.stores import uom_standards
    try:
        uom_standards.create_canonical(
            uom_code=uom_code, family=family, base_factor=base_factor,
        )
    except uom_standards.UomStandardsError as exc:
        return RedirectResponse(
            url=f"/admin/uom?error={exc}", status_code=303,
        )
    return RedirectResponse(url="/admin/uom?saved=1", status_code=303)


@router.post("/admin/uom/canonical/{uom_code}/update")
async def uom_canonical_update(
    request: Request,
    uom_code: str,
    family: str = Form(...),
    base_factor: str = Form("1"),
):
    user = auth.require_user(request)
    if not auth.can_manage_users(user):
        raise HTTPException(403, "forbidden")
    from app.stores import uom_standards
    try:
        uom_standards.update_canonical(
            uom_code=uom_code, family=family, base_factor=base_factor,
        )
    except uom_standards.UomStandardsError as exc:
        return RedirectResponse(url=f"/admin/uom?error={exc}", status_code=303)
    return RedirectResponse(url="/admin/uom?saved=1", status_code=303)


@router.post("/admin/uom/canonical/{uom_code}/delete")
async def uom_canonical_delete(request: Request, uom_code: str):
    user = auth.require_user(request)
    if not auth.can_manage_users(user):
        raise HTTPException(403, "forbidden")
    from app.stores import uom_standards
    try:
        uom_standards.delete_canonical(uom_code)
    except uom_standards.UomStandardsError as exc:
        return RedirectResponse(url=f"/admin/uom?error={exc}", status_code=303)
    return RedirectResponse(url="/admin/uom?saved=1", status_code=303)


@router.post("/admin/uom/aliases/new")
async def uom_alias_new(
    request: Request,
    alias_norm: str = Form(...),
    uom_code: str = Form(...),
):
    user = auth.require_user(request)
    if not auth.can_manage_users(user):
        raise HTTPException(403, "forbidden")
    from app.stores import uom_standards
    try:
        uom_standards.create_alias(alias_norm=alias_norm, uom_code=uom_code)
    except uom_standards.UomStandardsError as exc:
        return RedirectResponse(
            url=f"/admin/uom?error={exc}", status_code=303,
        )
    return RedirectResponse(url="/admin/uom?saved=1", status_code=303)


@router.post("/admin/uom/aliases/{alias_norm}/delete")
async def uom_alias_delete(request: Request, alias_norm: str):
    user = auth.require_user(request)
    if not auth.can_manage_users(user):
        raise HTTPException(403, "forbidden")
    from app.stores import uom_standards
    try:
        uom_standards.delete_alias(alias_norm)
    except uom_standards.UomStandardsError as exc:
        return RedirectResponse(
            url=f"/admin/uom?error={exc}", status_code=303,
        )
    return RedirectResponse(url="/admin/uom?saved=1", status_code=303)
