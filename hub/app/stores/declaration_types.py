"""hub.declaration_type_catalog CRUD.

Catalog of HQ customs declaration type codes (E11, E15, E31, ...). Seeded
once from data/seeds/declaration_types.yaml; staff manage via
/admin/declaration-types.
"""
from __future__ import annotations

from app.database import connect


def list_all(*, only_active: bool = False, direction: str | None = None) -> list[dict]:
    sql = """
        select code, direction, description, notes, is_active,
               created_at, updated_at
        from hub.declaration_type_catalog
    """
    where: list[str] = []
    params: list = []
    if only_active:
        where.append("is_active = true")
    if direction:
        where.append("direction = %s")
        params.append(direction)
    if where:
        sql += " where " + " and ".join(where)
    sql += " order by direction, code"
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            cols = [d.name for d in cur.description]
            return [dict(zip(cols, row)) for row in cur.fetchall()]


def get(code: str) -> dict | None:
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                select code, direction, description, notes, is_active,
                       created_at, updated_at
                from hub.declaration_type_catalog where code = %s
                """,
                (code,),
            )
            row = cur.fetchone()
            if not row:
                return None
            cols = [d.name for d in cur.description]
            return dict(zip(cols, row))


def create(*, code: str, direction: str, description: str = "",
           notes: str = "", user_id: str | None = None) -> dict:
    code = code.strip().upper()
    if not code:
        raise ValueError("code is required")
    if direction not in ("import", "export"):
        raise ValueError("direction must be 'import' or 'export'")
    with connect(user_id=user_id) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                insert into hub.declaration_type_catalog
                  (code, direction, description, notes)
                values (%s, %s, %s, %s)
                returning code, direction, description, notes, is_active,
                          created_at, updated_at
                """,
                (code, direction, description, notes),
            )
            cols = [d.name for d in cur.description]
            return dict(zip(cols, cur.fetchone()))


def update(code: str, *, direction: str | None = None,
           description: str | None = None, notes: str | None = None,
           is_active: bool | None = None,
           user_id: str | None = None) -> dict | None:
    sets: list[str] = []
    params: list = []
    if direction is not None:
        if direction not in ("import", "export"):
            raise ValueError("direction must be 'import' or 'export'")
        sets.append("direction = %s")
        params.append(direction)
    if description is not None:
        sets.append("description = %s")
        params.append(description)
    if notes is not None:
        sets.append("notes = %s")
        params.append(notes)
    if is_active is not None:
        sets.append("is_active = %s")
        params.append(is_active)
    if not sets:
        return get(code)
    sets.append("updated_at = now()")
    params.append(code)
    with connect(user_id=user_id) as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"""
                update hub.declaration_type_catalog
                set {', '.join(sets)}
                where code = %s
                returning code, direction, description, notes, is_active,
                          created_at, updated_at
                """,
                params,
            )
            row = cur.fetchone()
            if not row:
                return None
            cols = [d.name for d in cur.description]
            return dict(zip(cols, row))
