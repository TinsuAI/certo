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


def import_csv(*, client_id: str, csv_text: str,
                source: str = "imported") -> dict:
    """Parse CSV (header: material_code,from_uom,to_uom,factor[,notes])
    and upsert each row. Returns counts dict.

    Empty material_code → client-wide override (NULL). Whitespace
    stripped. Lines starting with '#' or empty are skipped.
    """
    n_inserted = 0
    n_failed = 0
    errors: list[str] = []
    reader = csv.DictReader(io.StringIO(csv_text))
    expected = {"material_code", "from_uom", "to_uom", "factor"}
    if reader.fieldnames is None:
        raise FactorError("CSV has no header")
    field_set = {f.strip() for f in reader.fieldnames}
    missing = expected - field_set
    if missing:
        raise FactorError(
            f"CSV missing required columns: {sorted(missing)}"
        )
    for row_n, row in enumerate(reader, start=2):  # row 1 is header
        if not any((v or "").strip() for v in row.values()):
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
            "errors": errors[:20]}  # cap displayed errors
