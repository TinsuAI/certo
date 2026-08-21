"""hub.client_type_presets CRUD.

DNCX activity-type profiles (dncx, sxxk, gia_cong, manual, ...). Seeded
once from data/seeds/client_type_presets.yaml; staff manage via
/admin/client-type-presets.

System presets (is_system=true) cannot be deleted but can be edited
or disabled. User presets are fully deletable.
"""
from __future__ import annotations

from hub.app.database import connect


def list_all(*, only_active: bool = False) -> list[dict]:
    sql = """
        select preset_key, display_name, default_eligible_import,
               default_relevant_export, is_system, is_active, notes,
               created_at, updated_at
        from hub.client_type_presets
    """
    if only_active:
        sql += " where is_active = true"
    sql += " order by is_system desc, preset_key"
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(sql)
            cols = [d.name for d in cur.description]
            return [dict(zip(cols, row)) for row in cur.fetchall()]


def get(preset_key: str) -> dict | None:
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                select preset_key, display_name, default_eligible_import,
                       default_relevant_export, is_system, is_active, notes,
                       created_at, updated_at
                from hub.client_type_presets where preset_key = %s
                """,
                (preset_key,),
            )
            row = cur.fetchone()
            if not row:
                return None
            cols = [d.name for d in cur.description]
            return dict(zip(cols, row))


def create(*, preset_key: str, display_name: str,
           default_eligible_import: list[str] | None = None,
           default_relevant_export: list[str] | None = None,
           notes: str = "", user_id: str | None = None) -> dict:
    preset_key = (preset_key or "").strip().lower()
    if not preset_key:
        raise ValueError("preset_key is required")
    if not display_name.strip():
        raise ValueError("display_name is required")
    with connect(user_id=user_id) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                insert into hub.client_type_presets
                  (preset_key, display_name, default_eligible_import,
                   default_relevant_export, is_system, notes)
                values (%s, %s, %s, %s, false, %s)
                returning preset_key, display_name, default_eligible_import,
                          default_relevant_export, is_system, is_active,
                          notes, created_at, updated_at
                """,
                (
                    preset_key,
                    display_name.strip(),
                    [c.strip().upper() for c in (default_eligible_import or []) if c.strip()],
                    [c.strip().upper() for c in (default_relevant_export or []) if c.strip()],
                    notes,
                ),
            )
            cols = [d.name for d in cur.description]
            return dict(zip(cols, cur.fetchone()))


def update(preset_key: str, *, display_name: str | None = None,
           default_eligible_import: list[str] | None = None,
           default_relevant_export: list[str] | None = None,
           is_active: bool | None = None, notes: str | None = None,
           user_id: str | None = None) -> dict | None:
    sets: list[str] = []
    params: list = []
    if display_name is not None:
        if not display_name.strip():
            raise ValueError("display_name cannot be empty")
        sets.append("display_name = %s")
        params.append(display_name.strip())
    if default_eligible_import is not None:
        sets.append("default_eligible_import = %s")
        params.append([c.strip().upper() for c in default_eligible_import if c.strip()])
    if default_relevant_export is not None:
        sets.append("default_relevant_export = %s")
        params.append([c.strip().upper() for c in default_relevant_export if c.strip()])
    if is_active is not None:
        sets.append("is_active = %s")
        params.append(is_active)
    if notes is not None:
        sets.append("notes = %s")
        params.append(notes)
    if not sets:
        return get(preset_key)
    sets.append("updated_at = now()")
    params.append(preset_key)
    with connect(user_id=user_id) as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"""
                update hub.client_type_presets
                set {', '.join(sets)}
                where preset_key = %s
                returning preset_key, display_name, default_eligible_import,
                          default_relevant_export, is_system, is_active,
                          notes, created_at, updated_at
                """,
                params,
            )
            row = cur.fetchone()
            if not row:
                return None
            cols = [d.name for d in cur.description]
            return dict(zip(cols, row))


def delete(preset_key: str, *, user_id: str | None = None) -> bool:
    """Delete a user preset. System presets refuse delete.

    Returns True on success, False on not found. Raises ValueError on
    is_system=true preset.
    """
    existing = get(preset_key)
    if existing is None:
        return False
    if existing["is_system"]:
        raise ValueError("System presets cannot be deleted; disable instead")
    with connect(user_id=user_id) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "delete from hub.client_type_presets where preset_key = %s",
                (preset_key,),
            )
    return True
