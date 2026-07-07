"""M2 — plan a batch NVL substitution across a case's origin sheets.

The client's flow: after running stock for the whole lô, a shared "sheet tổng hợp"
lists the short materials. Picking a substitute for one material should apply it
either to ONLY the sheets where it's short ("thay phần thiếu") or to EVERY sheet
that uses it ("thay hết"), then sync down to each sheet.

This module is the pure planner that turns that one choice into the flat
`substitutions` list `bulk_substitute_route` already consumes — it does NOT
mutate the case or touch stock. Locked sheets can't be edited, so they are left
out of the plan and reported separately (the caller/route skips them anyway).
"""
from __future__ import annotations

_MODES = {"only_short", "everywhere"}
_CARRIED_FIELDS = {"name", "uom", "hs_code", "norm_per_unit"}


def _active_material(product: dict, material_code: str) -> dict | None:
    """The first ACTIVE (non-deleted) material on `product` matching
    `material_code` — mirrors material_row_index's matching (falls back to
    internal_material_code). Returns the material dict (so callers can read its
    allocation_status), or None if the sheet doesn't use the code."""
    target = str(material_code or "").strip()
    if not target:
        return None
    for material in product.get("materials", []) or []:
        if material.get("deleted"):
            continue
        code = str(material.get("material_code") or material.get("internal_material_code") or "").strip()
        if code == target:
            return material
    return None


def plan_shortfall_substitution(
    case: dict,
    material_code: str,
    substitute_code: str,
    mode: str,
    *,
    substitute_fields: dict | None = None,
) -> dict:
    """Expand a single substitute choice into the per-product `substitutions`
    payload for bulk-substitute.

    `case` must be stock-allocated (materials carry allocation_status) and have
    sheet states attached (products carry origin_sheet_status). `mode`:
    "only_short" targets sheets where the material is `shortage`; "everywhere"
    targets every non-locked sheet using it (unknown mode → "only_short").
    Locked sheets are excluded and counted in `locked_count`.
    """
    mode = mode if mode in _MODES else "only_short"
    material_code = str(material_code or "").strip()
    substitute_code = str(substitute_code or "").strip()
    carried = {
        key: str(value or "").strip()
        for key, value in (substitute_fields or {}).items()
        if key in _CARRIED_FIELDS
    }

    substitutions: list[dict] = []
    using_count = short_count = locked_count = 0
    for product in case.get("products", []) or []:
        material = _active_material(product, material_code)
        if material is None:
            continue
        if str(product.get("origin_sheet_status") or "") == "locked":
            locked_count += 1
            continue
        using_count += 1
        is_short = str(material.get("allocation_status") or "") == "shortage"
        if is_short:
            short_count += 1
        if mode == "only_short" and not is_short:
            continue
        substitutions.append({
            "product_code": str(product.get("code") or "").strip(),
            "material_code": material_code,
            "substitute_code": substitute_code,
            **carried,
        })

    return {
        "substitutions": substitutions,
        "summary": {
            "material_code": material_code,
            "substitute_code": substitute_code,
            "mode": mode,
            "using_count": using_count,
            "short_count": short_count,
            "locked_count": locked_count,
            "target_count": len(substitutions),
        },
    }
