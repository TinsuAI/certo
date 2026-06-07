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


def _relation_from(severity: str, conversion: dict | None) -> tuple[str, bool]:
    """A.4.4: collapse this surface's family-severity + conversion plan
    into the shared `(relation, confirmed)` taxonomy. Derived (no extra DB
    call) and pinned to `classify_uom_relation` by a consistency test.

    `severity` stays family-based for the upload gate's banner; `relation`
    is the cross-surface vocabulary (equivalent/convertible/incompatible).
    """
    if severity == "info_alias":
        return "equivalent", True
    if severity == "info_family":
        return "convertible", True
    if severity == "warn_cross_family":
        # Cross-family is convertible iff a path exists (override row or
        # tier-A 1:1). tier-A's 1:1 is unconfirmed → confirmed=False.
        if conversion and not conversion.get("would_block"):
            confirmed = conversion.get("source") != "unconfirmed_default"
            return "convertible", confirmed
        return "incompatible", False
    # info_unknown (alias not resolvable) and any other → incompatible.
    return "incompatible", False


def compute_uom_drifts(client_id: str, rows: list[dict]) -> list[dict]:
    """Return UoM drift entries for parsed upload rows.

    Each `rows` item must carry `material_code` + `uom` keys. Repeated
    (material_code, uom) pairs collapse to a single drift entry.

    Returns severity-sorted list (worst first) of:
        {material_code, source_uom, source_canonical, source_dim,
         catalog_uom, catalog_canonical, catalog_dim,
         bcct_uoms: list[str], severity, message,
         # Phase 2 conversion plan (added 2026-05-12):
         conversion: {factor: str|None, source: str|None,
                       target_uom: str|None, would_block: bool} | None}

    Phase 2: when catalog has a UoM, consult `make_uom_lookup` to
    produce a `conversion` block per drift entry. Tier-B (no factor
    + cross-family non-tier-A) sets `would_block=True` so preview can
    surface "thiếu hệ số, chưa thể quy đổi" UI prompt.
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

    # Phase 2: build a uom_lookup once for this client to compute the
    # conversion plan per drift entry. Lazy import to avoid pulling
    # the store layer at module import time.
    from app.stores.uom import make_uom_lookup
    uom_lookup = make_uom_lookup(client_id)

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

        # Phase 2 conversion plan: only when catalog has a UoM (the
        # convertible target). BCCT-side comparator is informational
        # only; flatten engine converts toward catalog at materialize
        # time.
        conversion: dict | None = None
        if cat_uom:
            match = uom_lookup(code, src_uom, cat_uom)
            if match is None:
                # Tier-B without override row → would block conversion.
                # OR unknown alias on either side.
                conversion = {
                    "factor": None,
                    "source": None,
                    "target_uom": cat_uom,
                    "would_block": True,
                }
            else:
                conversion = {
                    "factor": str(match.factor),
                    "source": match.source,
                    "target_uom": cat_uom,
                    "would_block": False,
                }

        # Phase 2 (2026-05-12 round 2): severity reflects FAMILY
        # relationship (invariant). Override row provides a conversion
        # PATH, but doesn't make families equal. Surface this via a
        # separate `resolved_by_override` flag so UI can show "khác họ
        # + đã có hệ số" instead of misleading "cùng họ".
        resolved_by_override = (
            severity == "warn_cross_family"
            and conversion is not None
            and conversion.get("source") in (
                "client_specific", "client_wide", "global", "alias"))

        relation, relation_confirmed = _relation_from(severity, conversion)

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
            "relation": relation,
            "relation_confirmed": relation_confirmed,
            "resolved_by_override": resolved_by_override,
            "message": _format_message(severity, code, src_uom,
                                       comparator, details,
                                       resolved_by_override=resolved_by_override,
                                       conversion=conversion),
            "conversion": conversion,
        })

    out.sort(key=lambda d: (_SEVERITY_RANK.get(d["severity"], 99),
                            d["material_code"]))
    return out


def _format_message(severity: str, code: str, src_uom: str,
                    comparator: str, details: dict, *,
                    resolved_by_override: bool = False,
                    conversion: dict | None = None) -> str:
    """Short Vietnamese phrasing per severity."""
    if severity == "warn_cross_family":
        if resolved_by_override and conversion:
            # Cross-family bridged by an explicit override row — surface
            # that the families STILL DIFFER but a factor was supplied
            # so conversion is possible.
            factor = conversion.get("factor", "?")
            return (f"Mã {code}: file ghi '{src_uom}' ({details['source_dim']}) "
                    f"khác họ với '{comparator}' ({details['target_dim']}); "
                    f"đã có hệ số {factor} ({conversion.get('source')}) "
                    f"— quy đổi được")
        return (f"Mã {code}: file ghi '{src_uom}' ({details['source_dim']}) "
                f"khác họ với '{comparator}' ({details['target_dim']}) — "
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
    """True if any drift requires staff acknowledgement before confirm.
    Phase 2 (2026-05-12): blocks only when conversion has no path
    (would_block=True OR no conversion plan computed at all).
    Same-family / alias / unconfirmed_default / client-override paths
    don't block — they convert (or default 1:1 with warning badge)."""
    for d in drifts:
        conv = d.get("conversion")
        if conv is None:
            # No conversion path computed (catalog UoM null OR alias
            # missing) AND severity is cross-family → genuine block.
            if d.get("severity") == "warn_cross_family":
                return True
            continue
        if conv.get("would_block"):
            return True
    return False
