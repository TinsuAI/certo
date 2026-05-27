"""Phase 2 step 7 — admin store for `hub.client_uom_overrides`.

CRUD + CSV bulk import. Per-client scope (no global view).
"""
from __future__ import annotations

import csv
import io
from decimal import Decimal, InvalidOperation
from typing import Iterable

from app.database import connect


VALID_SOURCES = (
    "staff_form", "migration", "seed", "co_proposal",
    "supplier_data", "packaging_spec", "derived_average", "imported",
)


class FactorError(ValueError):
    """Raised on invalid factor input from staff."""


def list_factors(client_id: str) -> list[dict]:
    """All factor rows for a client, joined with material name when known.
    Sorted by is_cross_family DESC (cross-family rows surface first)
    then by material_code."""
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "select c.material_code, m.name, "
            "       c.from_uom, c.to_uom, c.factor::text, "
            "       c.source, c.is_cross_family, c.notes, c.created_at "
            "from hub.client_uom_overrides c "
            "left join hub.materials m "
            "  on m.client_id=c.client_id and m.material_code=c.material_code "
            "where c.client_id=%s "
            "order by c.is_cross_family desc, "
            "         coalesce(c.material_code, '') asc, "
            "         c.from_uom, c.to_uom",
            (client_id,),
        )
        return [{
            "material_code": r[0],
            "material_name": r[1],
            "from_uom": r[2], "to_uom": r[3], "factor": r[4],
            "source": r[5], "is_cross_family": r[6],
            "notes": r[7], "created_at": r[8],
        } for r in cur.fetchall()]


def stats(client_id: str) -> dict:
    """Counts for the admin list page header."""
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "select count(*), "
            "  count(*) filter (where is_cross_family) "
            "from hub.client_uom_overrides where client_id=%s",
            (client_id,),
        )
        total, xfam = cur.fetchone()
    return {"total": total, "cross_family": xfam}


def _validate(material_code: str | None, from_uom: str, to_uom: str,
              factor: str, source: str) -> tuple[str | None, str, str, Decimal]:
    """Return validated tuple or raise FactorError."""
    fu = (from_uom or "").strip()
    tu = (to_uom or "").strip()
    if not fu or not tu:
        raise FactorError("from_uom and to_uom required")
    if fu == tu:
        raise FactorError("from_uom and to_uom must differ")
    try:
        fac = Decimal(str(factor).strip())
    except (InvalidOperation, ValueError):
        raise FactorError(f"factor not numeric: {factor!r}")
    if fac <= 0:
        raise FactorError(f"factor must be positive (got {fac})")
    if source not in VALID_SOURCES:
        raise FactorError(
            f"source must be one of {VALID_SOURCES}; got {source!r}"
        )
    mc = (material_code or "").strip() or None
    return mc, fu, tu, fac


def create_factor(*, client_id: str, material_code: str | None,
                  from_uom: str, to_uom: str, factor: str,
                  source: str = "staff_form",
                  notes: str | None = None) -> None:
    mc, fu, tu, fac = _validate(material_code, from_uom, to_uom, factor, source)
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "insert into hub.client_uom_overrides "
            "(client_id, material_code, from_uom, to_uom, factor, "
            " source, notes) values (%s, %s, %s, %s, %s, %s, %s) "
            "on conflict (client_id, material_code_key, from_uom, to_uom) "
            "do update set factor=excluded.factor, source=excluded.source, "
            "              notes=excluded.notes",
            (client_id, mc, fu, tu, fac, source, notes),
        )
    # Audit 2026-05-27: per-material overrides resolve drift that
    # mig-071 helper accounts for. Reconcile downstream artifacts so
    # the new override actually clears any pre-existing flag.
    if mc:
        from app.stores.bom_staleness import reconcile_for_material
        reconcile_for_material(client_id, mc)


def update_factor(*, client_id: str, material_code: str | None,
                  from_uom: str, to_uom: str, factor: str,
                  source: str = "staff_form",
                  notes: str | None = None) -> None:
    mc, fu, tu, fac = _validate(material_code, from_uom, to_uom, factor, source)
    mc_key = mc or ""
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "update hub.client_uom_overrides "
            "set factor=%s, source=%s, notes=%s "
            "where client_id=%s and material_code_key=%s "
            "  and from_uom=%s and to_uom=%s",
            (fac, source, notes, client_id, mc_key, fu, tu),
        )
        if cur.rowcount == 0:
            raise FactorError("no matching factor row to update")
    if mc:
        from app.stores.bom_staleness import reconcile_for_material
        reconcile_for_material(client_id, mc)


def delete_factor(*, client_id: str, material_code: str | None,
                  from_uom: str, to_uom: str) -> None:
    mc_key = (material_code or "").strip() or ""
    fu = from_uom.strip()
    tu = to_uom.strip()
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "delete from hub.client_uom_overrides "
            "where client_id=%s and material_code_key=%s "
            "  and from_uom=%s and to_uom=%s",
            (client_id, mc_key, fu, tu),
        )
        if cur.rowcount == 0:
            raise FactorError("no matching factor row to delete")
    # Delete may UN-resolve drift on artifacts that previously relied on
    # this override. Reconcile to re-evaluate state.
    if mc_key:
        from app.stores.bom_staleness import reconcile_for_material
        reconcile_for_material(client_id, mc_key)


def _import_dicts(*, client_id: str, dicts: list[dict],
                   source: str) -> dict:
    """Common path for both CSV and XLSX imports."""
    n_inserted = 0
    n_failed = 0
    errors: list[str] = []
    for row_n, row in enumerate(dicts, start=2):  # row 1 is header
        if not any((str(v or "").strip()) for v in row.values()):
            continue
        try:
            create_factor(
                client_id=client_id,
                material_code=row.get("material_code"),
                from_uom=row.get("from_uom") or "",
                to_uom=row.get("to_uom") or "",
                factor=row.get("factor") or "",
                source=source,
                notes=row.get("notes") or None,
            )
            n_inserted += 1
        except FactorError as exc:
            n_failed += 1
            errors.append(f"row {row_n}: {exc}")
    return {"inserted": n_inserted, "failed": n_failed,
            "errors": errors[:20]}


_REQUIRED_COLS = {"material_code", "from_uom", "to_uom", "factor"}


def import_csv(*, client_id: str, csv_text: str,
                source: str = "imported") -> dict:
    """Parse CSV (header: material_code,from_uom,to_uom,factor[,notes])
    and upsert each row. Returns counts dict.

    Empty material_code → client-wide override (NULL). Whitespace
    stripped. Empty lines skipped.
    """
    reader = csv.DictReader(io.StringIO(csv_text))
    if reader.fieldnames is None:
        raise FactorError("CSV has no header")
    field_set = {f.strip() for f in reader.fieldnames}
    missing = _REQUIRED_COLS - field_set
    if missing:
        raise FactorError(
            f"CSV missing required columns: {sorted(missing)}")
    return _import_dicts(client_id=client_id, dicts=list(reader),
                          source=source)


def import_xlsx(*, client_id: str, xlsx_bytes: bytes,
                 source: str = "imported") -> dict:
    """Parse XLSX (first sheet, header in row 1). Same column contract
    as import_csv: material_code, from_uom, to_uom, factor[, notes]."""
    import openpyxl
    wb = openpyxl.load_workbook(io.BytesIO(xlsx_bytes), data_only=True,
                                  read_only=True)
    ws = wb.active
    if ws is None:
        raise FactorError("XLSX has no active sheet")
    rows = list(ws.iter_rows(values_only=True))
    if not rows:
        raise FactorError("XLSX is empty")
    headers = [str(c).strip() if c else "" for c in rows[0]]
    field_set = {h for h in headers if h}
    missing = _REQUIRED_COLS - field_set
    if missing:
        raise FactorError(
            f"XLSX missing required columns: {sorted(missing)}")
    dicts: list[dict] = []
    for row in rows[1:]:
        rec = {}
        for h, v in zip(headers, row):
            if not h:
                continue
            rec[h] = "" if v is None else str(v).strip()
        dicts.append(rec)
    wb.close()
    return _import_dicts(client_id=client_id, dicts=dicts, source=source)


def render_template_xlsx() -> bytes:
    """Generate a downloadable XLSX template with header + 2 example
    rows. Reflects current required-columns contract; regenerated on
    every download so always current."""
    import openpyxl
    from openpyxl.styles import Font, PatternFill, Alignment
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "uom-factors"
    headers = ["material_code", "from_uom", "to_uom", "factor", "notes"]
    for ci, h in enumerate(headers, 1):
        c = ws.cell(row=1, column=ci, value=h)
        c.font = Font(bold=True)
        c.fill = PatternFill("solid", fgColor="D9E1F2")
        c.alignment = Alignment(vertical="center")
    # Sample rows.
    samples = [
        ["M_EXAMPLE_1", "EA", "KG", "0.5", "1 chiếc nặng 0.5 kg (per supplier)"],
        ["M_EXAMPLE_2", "EA", "SETS", "4", "1 SETS gồm 4 EA"],
        ["", "g", "kg", "0.001", "client-wide: 1 g = 0.001 kg (cùng họ — thường không cần điền)"],
    ]
    for ri, sample in enumerate(samples, start=2):
        for ci, v in enumerate(sample, 1):
            ws.cell(row=ri, column=ci, value=v)
    # Column widths
    for ci, w in enumerate([20, 14, 14, 12, 60], 1):
        ws.column_dimensions[chr(64 + ci)].width = w
    # Instructions sheet
    inst = wb.create_sheet("Hướng dẫn")
    inst["A1"] = "Bảng nhập hệ số quy đổi đơn vị tính (UoM factors)"
    inst["A1"].font = Font(size=13, bold=True)
    lines = [
        "",
        "Cột bắt buộc: material_code, from_uom, to_uom, factor",
        "Cột tùy chọn: notes",
        "",
        "Quy ước:",
        "• material_code để TRỐNG = client-wide override (áp cho mọi mã trong client).",
        "• factor: số dương > 0. Hệ thống tự đổi sang Decimal.",
        "• Mỗi dòng = 1 cặp (material_code, from_uom, to_uom).",
        "  Trùng key (cùng material_code/from/to) sẽ ghi đè factor cũ.",
        "• Để xóa 1 hệ số: làm trên admin UI, không qua import.",
        "",
        "Khuyến nghị nhập:",
        "• Cross-family (count↔mass, EA↔KG): bắt buộc có factor (tier-B hard-block).",
        "• Cross-family count-ish (EA↔SETS, EA↔CAY): hệ thống tự dùng factor=1 nếu thiếu (tier-A unconfirmed_default), nhưng nên điền giá trị thật để mất badge cảnh báo.",
        "• Same-family (g↔kg, mm↔m): KHÔNG cần điền — hệ thống tự đổi qua uom_canonical.",
    ]
    for ri, line in enumerate(lines, start=2):
        inst.cell(row=ri, column=1, value=line).alignment = \
            Alignment(wrap_text=True, vertical="top")
    inst.column_dimensions["A"].width = 100
    out = io.BytesIO()
    wb.save(out)
    return out.getvalue()
