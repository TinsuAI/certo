"""Cross-source inconsistency warnings for catalog material detail page.

Each warning shape:
    {
        "kind": "hs_drift" | "uom_drift" | "origin_drift" |
                "direction_drift" | "mapping_drift",
        "severity": "info" | "warn" | "high",
        "count": int,                         # distinct values
        "evidence": [{"value": str, "n": int}, ...],
        "message": str,                       # short Vietnamese phrasing
    }
"""
from __future__ import annotations

from hub.app.database import connect


def _hs_drift(client_id: str, material_code: str) -> dict | None:
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            """
            select hs_code, count(*) as n from hub.bcct_rows
            where client_id=%s and customs_code=%s
              and hs_code is not null and hs_code <> ''
            group by hs_code order by n desc
            """,
            (client_id, material_code),
        )
        rows = cur.fetchall()
    if len(rows) <= 1:
        return None
    evidence = [{"value": v, "n": n} for v, n in rows]
    return {
        "kind": "hs_drift",
        "severity": "warn",
        "count": len(rows),
        "evidence": evidence,
        "message": f"Mã HQ này được khai với {len(rows)} mã HS khác nhau",
    }


def _uom_drift(client_id: str, material_code: str) -> dict | None:
    """Drift between materials.uom, BCCT.unit, BOM.uom — but only when
    canonical resolution shows real semantic conflict (different
    canonical codes). Synonyms (PCS == PIECE == ST) don't trigger.
    """
    from hub.app.stores.uom_standards import resolve_canonical

    sources: dict[str, set[str]] = {}
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "select uom from hub.materials where client_id=%s and material_code=%s",
            (client_id, material_code),
        )
        row = cur.fetchone()
        if row and row[0]:
            sources["catalog"] = {row[0]}
        cur.execute(
            "select distinct unit from hub.bcct_rows where client_id=%s "
            "and customs_code=%s and unit is not null and unit <> ''",
            (client_id, material_code),
        )
        bcct_uoms = {r[0] for r in cur.fetchall()}
        if bcct_uoms:
            sources["bcct"] = bcct_uoms
        cur.execute(
            """
            select distinct e.uom from hub.bom_edges e
              join hub.bom_artifacts a on a.artifact_id=e.artifact_id
             where a.client_id=%s and a.tombstoned_at is null
               and (e.parent_code=%s or e.child_code=%s)
               and e.uom is not null and e.uom <> ''
            """,
            (client_id, material_code, material_code),
        )
        bom_uoms = {r[0] for r in cur.fetchall()}
        if bom_uoms:
            sources["bom"] = bom_uoms

    all_values: set[str] = set()
    for s in sources.values():
        all_values.update(s)
    if not all_values:
        return None

    # Resolve each value to its canonical (or fall back to raw normalized
    # form for unknown aliases). Distinct CANONICALS = real drift.
    canonical_set: set[str] = set()
    for v in all_values:
        c = resolve_canonical(v) or (v or "").strip().lower()
        if c:
            canonical_set.add(c)
    if len(canonical_set) <= 1:
        return None

    # A.4.4: a UoM difference is only `warn` if it can't be resolved.
    # Classify each value against the catalog UoM (or, lacking one, a
    # deterministic anchor); convertible-and-confirmed differences are
    # `info` ("quy đổi được"), while incompatible OR tier-A-unconfirmed
    # (a 1:1 guess that needs sign-off) stay `warn` — same threshold as
    # the detail-page chip panel's `needs_attention`.
    from hub.app.stores.uom import classify_uom_relation
    anchor = next(iter(sources["catalog"])) if "catalog" in sources \
        else sorted(all_values)[0]
    needs_attention = False
    for v in all_values:
        if v == anchor:
            continue
        rel = classify_uom_relation(
            v, anchor, client_id=client_id, material_code=material_code)
        if rel.relation == "incompatible" or (
                rel.relation == "convertible" and not rel.confirmed):
            needs_attention = True
            break
    severity = "warn" if needs_attention else "info"

    evidence = [
        {"value": f"{src}: {','.join(sorted(vals))}", "n": len(vals)}
        for src, vals in sources.items()
    ]
    note = ("có đơn vị chưa quy đổi được" if severity == "warn"
            else "quy đổi được")
    return {
        "kind": "uom_drift",
        "severity": severity,
        "count": len(canonical_set),
        "evidence": evidence,
        "message": (f"UoM khác nhau giữa các nguồn "
                    f"({len(canonical_set)} đơn vị canonical) — {note}"),
    }


def _origin_drift(client_id: str, material_code: str) -> dict | None:
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            """
            select origin, count(*) as n from hub.bcct_rows
            where client_id=%s and customs_code=%s
              and origin is not null and origin <> ''
            group by origin order by n desc
            """,
            (client_id, material_code),
        )
        rows = cur.fetchall()
    if len(rows) <= 1:
        return None
    return {
        "kind": "origin_drift",
        "severity": "info",
        "count": len(rows),
        "evidence": [{"value": v, "n": n} for v, n in rows],
        "message": f"Xuất xứ khai báo với {len(rows)} giá trị khác nhau",
    }


def _direction_drift(client_id: str, material_code: str) -> dict | None:
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            """
            select direction, count(*) as n from hub.bcct_rows
            where client_id=%s and customs_code=%s
              and direction in ('import', 'export')
            group by direction
            """,
            (client_id, material_code),
        )
        rows = cur.fetchall()
    if len(rows) < 2:
        return None
    return {
        "kind": "direction_drift",
        "severity": "info",
        "count": 2,
        "evidence": [{"value": d, "n": n} for d, n in rows],
        "message": "Mã này khai cả nhập và xuất — có thể là multi-role",
    }


def _mapping_drift(client_id: str, material_code: str) -> dict | None:
    """Same NB → multiple HQ, or same HQ → multiple NB."""
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "select customs_code from hub.code_mappings "
            "where client_id=%s and internal_code=%s",
            (client_id, material_code),
        )
        as_nb = [r[0] for r in cur.fetchall()]
        cur.execute(
            "select internal_code from hub.code_mappings "
            "where client_id=%s and customs_code=%s",
            (client_id, material_code),
        )
        as_hq = [r[0] for r in cur.fetchall()]
    if len(as_nb) > 1:
        return {
            "kind": "mapping_drift",
            "severity": "info",
            "count": len(as_nb),
            "evidence": [{"value": v, "n": 1} for v in as_nb],
            "message": f"Mã NB này được map tới {len(as_nb)} mã HQ khác nhau",
        }
    if len(as_hq) > 1:
        return {
            "kind": "mapping_drift",
            "severity": "info",
            "count": len(as_hq),
            "evidence": [{"value": v, "n": 1} for v in as_hq],
            "message": f"Mã HQ này được map từ {len(as_hq)} mã NB khác nhau",
        }
    return None


def compute_warnings(client_id: str, material_code: str) -> list[dict]:
    """Return all warnings for this material, in order: high → warn → info."""
    out = []
    for fn in (_hs_drift, _uom_drift, _origin_drift,
               _direction_drift, _mapping_drift):
        w = fn(client_id, material_code)
        if w:
            out.append(w)
    severity_order = {"high": 0, "warn": 1, "info": 2}
    out.sort(key=lambda w: severity_order.get(w["severity"], 99))
    return out
