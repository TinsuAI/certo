from __future__ import annotations

from decimal import Decimal, InvalidOperation


def material_render_parts(material: dict) -> list[dict]:
    """Render-split fan-out (VN-origin ticket #7): one source material emits one
    display/export row per distinct (origin_status, bang_ke_origin_text) group of
    its allocation lines. The source material dict is never modified.

    The per-line fields arrive with the resolver/column-9 tickets; while absent,
    every line falls into the material's own group, so exactly one part renders
    and it is the material dict itself (identity — rendering byte-identical).

    Each part keeps the merged-declaration behaviour within its own lines, and
    the parts sum exactly to the line's quantity and money totals: unallocated
    shortfall quantity (which has no lawful value on the bảng kê) rides the part
    matching the material's own key, or the first part.
    """
    lines = material.get("allocation_lines") or []
    default_key = (
        str(material.get("origin_status") or "non_origin"),
        str(material.get("bang_ke_origin_text") or ""),
    )
    groups: dict[tuple[str, str], list[dict]] = {}
    for line in lines:
        key = (
            str(line.get("origin_status") or default_key[0]),
            str(line.get("bang_ke_origin_text") or default_key[1]),
        )
        groups.setdefault(key, []).append(line)
    if len(groups) <= 1:
        return [material]

    allocated_total = sum((_decimal(line.get("allocated_qty")) or Decimal("0") for line in lines), Decimal("0"))
    consumed_total = _decimal(material.get("consumed_qty"))
    residual = (consumed_total - allocated_total) if consumed_total is not None else Decimal("0")
    if residual < 0:
        residual = Decimal("0")
    residual_key = default_key if default_key in groups else next(iter(groups))

    sequence = str(material.get("material_sequence") or "")
    parts = []
    for index, (key, group_lines) in enumerate(groups.items()):
        origin_status, origin_text = key
        part_qty = sum((_decimal(line.get("allocated_qty")) or Decimal("0") for line in group_lines), Decimal("0"))
        if key == residual_key:
            part_qty += residual
        part_value = _sum_field(group_lines, "material_value")
        part = dict(material)
        part.update({
            "allocation_lines": list(group_lines),
            "origin_status": origin_status,
            "bang_ke_origin_text": origin_text,
            "consumed_qty": _text(part_qty),
            "material_value": part_value,
            "material_value_native": _sum_field(group_lines, "material_value_native"),
            "material_value_vnd": _sum_field(group_lines, "material_value_vnd"),
            "non_origin_cif_value": part_value if origin_status == "non_origin" else "",
            "non_origin_cif_value_vnd": _sum_field(group_lines, "material_value_vnd") if origin_status == "non_origin" else "",
            "source_row": _joined(group_lines, "source_row"),
            "import_declaration_no": _joined(group_lines, "import_declaration_no"),
            "import_declaration_date": _joined(group_lines, "import_declaration_date"),
            "import_line_no": _joined(group_lines, "import_line_no"),
            "customs_material_code": _joined(group_lines, "customs_material_code") or str(material.get("customs_material_code") or ""),
            "origin_country": _joined(group_lines, "origin_country"),
            "consignee_name": _joined(group_lines, "consignee_name"),
            "supplier_key": _joined(group_lines, "supplier_key"),
            "render_part_key": f"{sequence}:{origin_status}:{origin_text}",
            "render_part_count": len(groups),
        })
        parts.append(part)
    return parts


def _decimal(value) -> Decimal | None:
    text = str(value if value is not None else "").strip()
    if not text:
        return None
    try:
        return Decimal(text)
    except InvalidOperation:
        return None


def _text(value: Decimal) -> str:
    if value == value.to_integral():
        return str(value.quantize(Decimal("1")))
    return format(value.normalize(), "f").rstrip("0").rstrip(".")


def _sum_field(lines: list[dict], field: str) -> str:
    """Partial sum, mirroring the material builder: lines with no value are
    skipped (never zero-coerced), and "" only when NO line carries a value —
    so Σ(parts) == the material-level total by construction."""
    values = [value for value in (_decimal(line.get(field)) for line in lines) if value is not None]
    if not values:
        return ""
    return _text(sum(values, Decimal("0")))


def _joined(lines: list[dict], field: str) -> str:
    seen = []
    for line in lines:
        text = str(line.get(field) or "").strip()
        if text and text not in seen:
            seen.append(text)
    return ", ".join(seen)
