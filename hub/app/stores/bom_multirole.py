"""Ingest-time multi-role warning — surfaces codes that are about to be
added as a BOM component (BTP/NVL) but were already EXPORTED in this
client's BCCT history.

A code exported in BCCT is a finished/semi-finished good in its own
right. When the same code appears as a *component* inside another
product's BOM, it is being used as a sub-assembly (BTP) — a genuine
multi-role situation (a code that is simultaneously a finished good and
a sub-component, e.g. rework / cải chế). Staff should confirm the intent
before the upload commits.

Advisory only: never blocks confirm (cf. compute_uom_drifts which can
block on cross-family drift). The catalog graph remains the source of
truth for roles; this is a heads-up at the moment of ingest.

Known limitation (shared with v_material_roles + compute_uom_drifts):
matches the upload's component codes against ``bcct_rows.customs_code``
only. Growatt-style agency NVL codes that live inside ``goods_name``
parens are invisible here — same gap tracked by backlog A.5. Acceptable
for an advisory signal.
"""
from __future__ import annotations

from hub.app.database import connect


def compute_multirole_warnings(
    client_id: str, products: dict[str, list[dict]]
) -> list[dict]:
    """Return multi-role warnings for an upload's component codes.

    ``products`` is the preview shape ``{product_code: [row, ...]}`` where
    each row carries a ``material_code``. The root ``product_code`` keys
    are the BOM owners (parents); their *component* ``material_code``
    values are the candidates for "added as BTP".

    Returns a list (sorted by export_count desc, then code) of:
        {code, export_count, export_declarations: int}
    one entry per distinct exported component code.
    """
    if not products:
        return []

    component_codes: set[str] = set()
    for rows in products.values():
        if not isinstance(rows, list):
            continue
        for r in rows:
            if not isinstance(r, dict):
                continue
            code = r.get("material_code")
            if code:
                component_codes.add(str(code))

    if not component_codes:
        return []

    codes = sorted(component_codes)
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "select customs_code, count(*) as n_rows, "
            "       count(distinct declaration_no) as n_decls "
            "from hub.bcct_rows "
            "where client_id = %s and direction = 'export' "
            "  and customs_code = any(%s) "
            "group by customs_code",
            (client_id, codes),
        )
        rows = cur.fetchall()

    out = [
        {"code": code, "export_count": int(n_rows),
         "export_declarations": int(n_decls)}
        for code, n_rows, n_decls in rows
    ]
    out.sort(key=lambda d: (-d["export_count"], d["code"]))
    return out
