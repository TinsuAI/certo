"""Lightweight read helpers over hub.materials shared across modules."""
from __future__ import annotations

from app.database import connect


def known_material_codes(client_id: str) -> set[str]:
    """All catalog material_codes for a client — used to decide whether a code
    referenced elsewhere (NXT / inventory line) links to a catalog detail page.
    """
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "select material_code from hub.materials where client_id=%s",
            (client_id,),
        )
        return {r[0] for r in cur.fetchall()}
