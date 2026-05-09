"""Ingest-time UoM drift detection — surfaces cross-source mismatch
between an upload's parsed rows and the catalog/BCCT history.

Used by BOM + BCCT preview routes to flag UoM disagreements before the
upload commits. Does NOT mutate parsed rows (no auto-conversion at
ingest); the flatten engine handles convertible drift deterministically
later via uom_canonical.base_factor.

Severity tiers (ordered from worst to mildest):
  warn_cross_family — different dimension (mass vs count). Likely
                      data corruption; staff must acknowledge before
                      confirm upload.
  info_family       — same family different canonical (gam ↔ kg). UI
                      shows banner; flatten will convert.
  info_unknown      — at least one side has unknown UoM alias (not in
                      hub.uom_aliases). Staff hint to add alias.
  info_alias        — synonym match (PCS == PIECE). Display only.

Counterpart compared against:
  - hub.materials.uom (catalog declaration).
  - distinct hub.bcct_rows.unit values for the same customs_code (BCCT
    history). Used as fallback when catalog lacks UoM.
"""
from __future__ import annotations

from app.database import connect
from app.stores.uom_standards import dimension_of, resolve_canonical


_SEVERITY_RANK = {
    "warn_cross_family": 0,
    "info_family": 1,
    "info_unknown": 2,
    "info_alias": 3,
}


def _classify(source_uom: str | None, target_uom: str | None) -> tuple[str, dict]:
    """Compare two UoM strings, return (severity, details).

    Returns severity 'none' when source matches target after canonical
    resolution AND alias normalization is identity (no drift to surface).
    """
    src_norm = (source_uom or "").strip().lower() or None
    tgt_norm = (target_uom or "").strip().lower() or None
    src_canon = resolve_canonical(source_uom)
    tgt_canon = resolve_canonical(target_uom)
    src_dim = dimension_of(source_uom)
    tgt_dim = dimension_of(target_uom)

    details = {
        "source_uom": source_uom,
        "source_canonical": src_canon,
        "source_dim": src_dim,
        "target_canonical": tgt_canon,
        "target_dim": tgt_dim,
    }

    if src_canon and tgt_canon and src_canon == tgt_canon:
        # Same canonical — could still be alias drift if raw strings
        # differ (e.g., PCS vs PIECE).
        if src_norm == tgt_norm:
            return "none", details
        return "info_alias", details

    if src_canon is None or tgt_canon is None:
        return "info_unknown", details

    if src_dim and tgt_dim and src_dim == tgt_dim:
        return "info_family", details

    return "warn_cross_family", details


def compute_uom_drifts(client_id: str, rows: list[dict]) -> list[dict]:
    """Return UoM drift entries for parsed upload rows.

    Each `rows` item must carry `material_code` + `uom` keys. Repeated
    (material_code, uom) pairs collapse to a single drift entry.

    Returns severity-sorted list (worst first) of:
        {material_code, source_uom, source_canonical, source_dim,
         catalog_uom, catalog_canonical, catalog_dim,
         bcct_uoms: list[str], severity, message}
    """
    # Dedupe parsed rows by (material_code, uom).
    seen_keys: set[tuple[str, str]] = set()
    parsed: list[tuple[str, str | None]] = []
    for r in rows:
        code = r.get("material_code")
        if not code:
            continue
        uom = (r.get("uom") or "").strip() or None
        key = (code, uom or "")
        if key in seen_keys:
            continue
        seen_keys.add(key)
        parsed.append((code, uom))

    if not parsed:
        return []

    codes = sorted({c for c, _ in parsed})

    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "select material_code, uom from hub.materials "
            "where client_id=%s and material_code = any(%s)",
            (client_id, codes),
        )
        catalog: dict[str, str | None] = {c: u for c, u in cur.fetchall()}
        cur.execute(
            "select customs_code, unit from hub.bcct_rows "
            "where client_id=%s and customs_code = any(%s) "
            "  and unit is not null and unit <> '' "
            "group by customs_code, unit",
            (client_id, codes),
        )
        bcct_by_code: dict[str, list[str]] = {}
        for code, unit in cur.fetchall():
            bcct_by_code.setdefault(code, []).append(unit)

    out: list[dict] = []
    for code, src_uom in parsed:
        if code not in catalog and code not in bcct_by_code:
            # Unknown code — not a drift signal here.
            continue

        cat_uom = catalog.get(code)
        bcct_uoms = bcct_by_code.get(code, [])

        # Determine the comparator: catalog UoM if set; otherwise the
        # most-common BCCT UoM (just take first; tie-breaks rare).
        comparator = cat_uom or (bcct_uoms[0] if bcct_uoms else None)
        if comparator is None:
            continue
        if src_uom is None:
            # Upload missing UoM is a different concern (validation), not
            # cross-source drift. Skip.
            continue

        severity, details = _classify(src_uom, comparator)
        if severity == "none":
            continue

        out.append({
            "material_code": code,
            "source_uom": src_uom,
            "source_canonical": details["source_canonical"],
            "source_dim": details["source_dim"],
            "catalog_uom": cat_uom,
            "catalog_canonical": resolve_canonical(cat_uom),
            "catalog_dim": dimension_of(cat_uom),
            "bcct_uoms": bcct_uoms,
            "severity": severity,
            "message": _format_message(severity, code, src_uom,
                                       comparator, details),
        })

    out.sort(key=lambda d: (_SEVERITY_RANK.get(d["severity"], 99),
                            d["material_code"]))
    return out


def _format_message(severity: str, code: str, src_uom: str,
                    comparator: str, details: dict) -> str:
    """Short Vietnamese phrasing per severity."""
    if severity == "warn_cross_family":
        return (f"Mã {code}: file ghi '{src_uom}' ({details['source_dim']}) "
                f"khác chiều với '{comparator}' ({details['target_dim']}) — "
                f"không thể quy đổi tự động")
    if severity == "info_family":
        return (f"Mã {code}: file ghi '{src_uom}', "
                f"tiêu chuẩn '{comparator}' (cùng họ "
                f"{details['source_dim']}); flatten sẽ tự quy đổi")
    if severity == "info_unknown":
        return (f"Mã {code}: '{src_uom}' hoặc '{comparator}' chưa "
                f"được khai trong uom_aliases — staff bổ sung")
    if severity == "info_alias":
        return (f"Mã {code}: '{src_uom}' và '{comparator}' là synonym "
                f"({details['source_canonical']})")
    return f"Mã {code}: drift {severity}"


def has_blocking_drift(drifts: list[dict]) -> bool:
    """True if any drift requires staff acknowledgement before
    confirm. Used by upload preview to gate the confirm button."""
    return any(d["severity"] == "warn_cross_family" for d in drifts)
