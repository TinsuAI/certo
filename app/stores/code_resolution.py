"""Code-mapping resolution worker — populates hub.code_mapping_resolutions.

For each Client, materializes the canonical (internal_code → customs_code)
disambiguation. Algorithm ported from bcqt-growatt/settlement/code_map.py:
- BQD (code_mappings) provides theoretical N-N pairings
- BCCT imports provide actual usage frequencies
- Resolution picks per-NB primary HQ:
    * identity (no BQD entry, NB == HQ in BCCT)
    * bqd_unique (BQD has exactly one HQ for this NB)
    * bcct_qty_pick (BQD has multiple; pick HQ with highest BCCT import qty)
    * fallback (BQD has multiple, no BCCT data — pick first)
"""
from __future__ import annotations

from collections import defaultdict
from typing import Iterable

from app.database import connect


def _load_bqd(cur, client_id: str) -> dict[str, list[str]]:
    cur.execute(
        "select internal_code, customs_code from hub.code_mappings where client_id = %s",
        (client_id,),
    )
    nb_to_hq: dict[str, list[str]] = defaultdict(list)
    for nb, hq in cur.fetchall():
        if hq not in nb_to_hq[nb]:
            nb_to_hq[nb].append(hq)
    return dict(nb_to_hq)


def _load_bcct_aggregates(cur, client_id: str) -> dict[str, dict[str, float]]:
    """Sum import quantities per (internal_code, customs_code).

    Used for 1:n disambiguation. Imports are the canonical "consumption side"
    per Growatt's algorithm; exports use a separate calc for TP if needed.
    """
    cur.execute(
        """
        select internal_code, customs_code, sum(coalesce(quantity, 0))
        from hub.bcct_rows
        where client_id = %s and direction = 'import'
          and internal_code is not null and customs_code is not null
        group by internal_code, customs_code
        """,
        (client_id,),
    )
    nb_hq_qty: dict[str, dict[str, float]] = defaultdict(dict)
    for nb, hq, qty in cur.fetchall():
        nb_hq_qty[nb][hq] = float(qty or 0)
    return dict(nb_hq_qty)


def _load_bcct_universe(cur, client_id: str) -> set[str]:
    """All internal codes seen in BCCT (any direction) — for identity fallback."""
    cur.execute(
        """
        select distinct internal_code from hub.bcct_rows
        where client_id = %s and internal_code is not null
        """,
        (client_id,),
    )
    return {nb for (nb,) in cur.fetchall()}


def resolve_for_dncx(client_id: str) -> dict:
    """Re-run resolution for one Client. Returns summary dict."""
    summary = {
        "identity": 0, "bqd_unique": 0, "bcct_qty_pick": 0,
        "fallback": 0, "manual_override": 0, "total": 0,
    }
    with connect() as conn:
        with conn.cursor() as cur:
            bqd = _load_bqd(cur, client_id)
            bcct = _load_bcct_aggregates(cur, client_id)
            bcct_universe = _load_bcct_universe(cur, client_id)

            # Universe of internal codes = union of BQD entries and ANY BCCT row.
            all_nbs: set[str] = set(bqd) | set(bcct) | bcct_universe
            cur.execute(
                "delete from hub.code_mapping_resolutions where client_id = %s",
                (client_id,),
            )
            for nb in sorted(all_nbs):
                bqd_hqs = bqd.get(nb, [])
                bcct_hqs = bcct.get(nb, {})
                if not bqd_hqs:
                    # No BQD entry — identity if BCCT confirms NB is also a customs code,
                    # otherwise treat as fallback to NB itself.
                    if nb in bcct and (nb in bcct_hqs or any(h == nb for h in bcct_hqs)):
                        resolved, basis = nb, "identity"
                    else:
                        resolved, basis = nb, "identity"
                elif len(bqd_hqs) == 1:
                    resolved, basis = bqd_hqs[0], "bqd_unique"
                else:
                    # 1:n BQD — pick by BCCT qty if available
                    if bcct_hqs:
                        candidates = {h: bcct_hqs.get(h, 0) for h in bqd_hqs}
                        if any(candidates.values()):
                            resolved = max(candidates, key=candidates.get)
                            basis = "bcct_qty_pick"
                        else:
                            resolved, basis = bqd_hqs[0], "fallback"
                    else:
                        resolved, basis = bqd_hqs[0], "fallback"

                cur.execute(
                    """
                    insert into hub.code_mapping_resolutions
                      (client_id, internal_code, resolved_customs_code, resolution_basis, details)
                    values (%s, %s, %s, %s, %s::jsonb)
                    """,
                    (client_id, nb, resolved, basis,
                     _details_payload(bqd_hqs, bcct_hqs, resolved, basis)),
                )
                summary[basis] += 1
                summary["total"] += 1

            # Backfill BCCT rows' resolved_customs_code
            cur.execute(
                """
                update hub.bcct_rows
                set resolved_customs_code = r.resolved_customs_code
                from hub.code_mapping_resolutions r
                where hub.bcct_rows.client_id = %s
                  and r.client_id = hub.bcct_rows.client_id
                  and r.internal_code = hub.bcct_rows.internal_code
                """,
                (client_id,),
            )
            # For rows where internal_code is null (no parse), fall back to customs_code.
            cur.execute(
                """
                update hub.bcct_rows set resolved_customs_code = customs_code
                where client_id = %s and internal_code is null
                  and resolved_customs_code is null and customs_code is not null
                """,
                (client_id,),
            )
    return summary


def _details_payload(bqd_hqs: list[str], bcct_hqs: dict[str, float],
                     resolved: str, basis: str) -> str:
    import json
    return json.dumps({
        "bqd_hqs": bqd_hqs,
        "bcct_qty_by_hq": bcct_hqs,
        "resolved": resolved,
        "basis": basis,
    })


def lookup_resolution(*, client_id: str, internal_code: str) -> dict | None:
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                select internal_code, resolved_customs_code, resolution_basis,
                       resolved_at, details
                from hub.code_mapping_resolutions
                where client_id = %s and internal_code = %s
                """,
                (client_id, internal_code),
            )
            row = cur.fetchone()
            if not row:
                return None
            return {
                "internal_code": row[0],
                "resolved_customs_code": row[1],
                "resolution_basis": row[2],
                "resolved_at": row[3],
                "details": row[4],
            }
