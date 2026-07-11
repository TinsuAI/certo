"""Catalog discovery — pending is computed, never stored (ADR-0001, #34).

Three kinds of information, three homes:
  pending  = derived      → hub.catalog_discovery(client) SQL function
  rejected = manual input → hub.catalog_rejections
  accepted = manual input → a row in hub.materials

Accept/reject/unreject write an audit event to hub.bom_audit_events
(event_type='catalog_candidate_decision' — same type the mig-092
history copy used), because decisions no longer live in a table row.
Unreject only lifts the suppression; it never touches materials or
code_mappings (the old `unreject_candidate` left both behind — that
bug dies with the table).
"""
from __future__ import annotations

import json

from app.database import connect


def discovery_rows(client_id: str) -> list[dict]:
    """All discovered codes for the client (pending + rejected), one
    function call. ~0.6-1.3s on Growatt — callers make exactly one call
    per request and filter in Python."""
    with connect() as conn, conn.cursor() as cur:
        cur.execute("select * from hub.catalog_discovery(%s)", (client_id,))
        cols = [d[0] for d in cur.description]
        return [dict(zip(cols, r)) for r in cur.fetchall()]


def get_row(client_id: str, code: str, code_kind: str | None = None) -> dict | None:
    with connect() as conn, conn.cursor() as cur:
        sql = "select * from hub.catalog_discovery(%s) where code = %s"
        params: list = [client_id, code]
        if code_kind:
            sql += " and code_kind = %s"
            params.append(code_kind)
        cur.execute(sql, params)
        row = cur.fetchone()
        if not row:
            return None
        cols = [d[0] for d in cur.description]
        return dict(zip(cols, row))


class AlreadyInCatalog(Exception):
    """The code is already a material — accept would clobber staff edits
    (the old accept's on-conflict overwrote name/category/status)."""


def _source_for(sources: list[str] | None) -> str:
    """materials.source from the originating stream. The old accept
    hardcoded 'bcct_observed' even for BOM-origin codes (#34 fix)."""
    s = set(sources or [])
    if "bcct" in s:
        return "bcct_observed"
    if "bom" in s:
        return "bom_observed"
    return "client_declared"  # bqd-only: the client's own mapping sheet


def _audit(cur, client_id: str, *, code: str, code_kind: str | None,
           action: str, actor: str, extra: dict | None = None) -> None:
    details = {"code": code, "code_kind": code_kind, "action": action}
    details.update(extra or {})
    cur.execute(
        "insert into hub.bom_audit_events "
        "(client_id, product_code, event_type, actor, details) "
        "values (%s, %s, 'catalog_candidate_decision', %s, %s::jsonb)",
        (client_id, code, actor, json.dumps(details, ensure_ascii=False,
                                            default=str)),
    )


def _auto_map(cur, client_id: str, code: str, code_kind: str) -> int:
    """Bidirectional NB↔HQ auto-mapping on accept, from the persisted
    paren links (the old version re-ran the regex scan per accept)."""
    if code_kind == "hq":
        cur.execute(
            """
            insert into hub.code_mappings (client_id, internal_code, customs_code)
            select distinct n.client_id, n.nb_code, trim(b.customs_code)
              from hub.bcct_nb_codes n
              join hub.bcct_rows b
                on b.client_id = n.client_id
               and b.transaction_key = n.transaction_key
               and b.line_no = n.line_no
             where n.client_id = %s and trim(b.customs_code) = %s
               and n.nb_code <> trim(b.customs_code)
               and exists (select 1 from hub.materials m
                            where m.client_id = n.client_id
                              and m.material_code = n.nb_code)
            on conflict do nothing
            """,
            (client_id, code),
        )
        return cur.rowcount
    if code_kind == "nb":
        cur.execute(
            """
            insert into hub.code_mappings (client_id, internal_code, customs_code)
            select distinct n.client_id, n.nb_code, trim(b.customs_code)
              from hub.bcct_nb_codes n
              join hub.bcct_rows b
                on b.client_id = n.client_id
               and b.transaction_key = n.transaction_key
               and b.line_no = n.line_no
              join hub.clients c on c.client_id = n.client_id
             where n.client_id = %s and n.nb_code = %s
               and nullif(trim(b.customs_code), '') is not null
               and trim(b.customs_code) <> n.nb_code
               and not (trim(b.customs_code) = any(c.customs_code_placeholders))
               and exists (select 1 from hub.materials m
                            where m.client_id = n.client_id
                              and m.material_code = trim(b.customs_code)
                              and m.code_kind = 'hq')
            on conflict do nothing
            """,
            (client_id, code),
        )
        return cur.rowcount
    return 0  # unified: no NB/HQ split, nothing to map


def accept_code(client_id: str, *, code: str, code_kind: str, actor: str,
                name: str, category: str, status: str = "under_review",
                uom: str | None = None,
                production_source: str | None = None,
                supplier_hint: str | None = None,
                sources: list[str] | None = None) -> dict:
    """Accept = insert the material. Returns {source, mappings_added}.

    `sources` (from the discovery row) decides materials.source; pass it
    to avoid a second discovery call when the route already has the row.
    """
    source = _source_for(sources)
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            """
            insert into hub.materials
              (client_id, material_code, name, category, status, source,
               uom, code_kind, production_source, supplier_hint, provenance)
            values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, '{}'::jsonb)
            on conflict (client_id, material_code) do nothing
            returning material_code
            """,
            (client_id, code, name, category, status, source,
             uom or None, code_kind, production_source or None,
             supplier_hint or None),
        )
        if cur.fetchone() is None:
            raise AlreadyInCatalog(code)
        # Accepting lifts a prior suppression on the same string.
        cur.execute(
            "delete from hub.catalog_rejections "
            "where client_id = %s and code = %s",
            (client_id, code),
        )
        n_map = _auto_map(cur, client_id, code, code_kind)
        _audit(cur, client_id, code=code, code_kind=code_kind,
               action="accept", actor=actor,
               extra={"name": name, "category": category, "status": status,
                      "source": source, "mappings_added": n_map})
    return {"source": source, "mappings_added": n_map}


def reject_code(client_id: str, *, code: str, code_kind: str | None,
                actor: str, reason: str | None = None) -> None:
    """Suppress the string. Re-rejecting updates reason/actor/time."""
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            """
            insert into hub.catalog_rejections
              (client_id, code, code_kind, reason, rejected_by)
            values (%s, %s, %s, %s, %s)
            on conflict (client_id, code) do update
              set code_kind = excluded.code_kind,
                  reason = excluded.reason,
                  rejected_by = excluded.rejected_by,
                  rejected_at = now()
            """,
            (client_id, code, code_kind, reason or None, actor),
        )
        _audit(cur, client_id, code=code, code_kind=code_kind,
               action="reject", actor=actor, extra={"reason": reason})


def unreject_code(client_id: str, *, code: str, actor: str) -> bool:
    """Lift the suppression. Touches nothing else — no material delete,
    no mapping rollback (accept and reject are independent facts)."""
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "delete from hub.catalog_rejections "
            "where client_id = %s and code = %s returning code",
            (client_id, code),
        )
        lifted = cur.fetchone() is not None
        if lifted:
            _audit(cur, client_id, code=code, code_kind=None,
                   action="unreject", actor=actor)
    return lifted


def co_occurring_codes(client_id: str, code: str, code_kind: str) -> list[dict]:
    """Partner codes on the same BCCT rows, from the persisted links
    (the old version re-ran the regex scan per detail-page view)."""
    if code_kind == "unified":
        return []
    with connect() as conn, conn.cursor() as cur:
        if code_kind == "hq":
            cur.execute(
                """
                select n.nb_code as code, count(*) as n
                  from hub.bcct_nb_codes n
                  join hub.bcct_rows b
                    on b.client_id = n.client_id
                   and b.transaction_key = n.transaction_key
                   and b.line_no = n.line_no
                 where n.client_id = %s and trim(b.customs_code) = %s
                   and n.nb_code <> trim(b.customs_code)
                 group by n.nb_code
                 order by n desc, code
                 limit 50
                """,
                (client_id, code),
            )
        else:  # nb
            cur.execute(
                """
                select trim(b.customs_code) as code, count(*) as n
                  from hub.bcct_nb_codes n
                  join hub.bcct_rows b
                    on b.client_id = n.client_id
                   and b.transaction_key = n.transaction_key
                   and b.line_no = n.line_no
                  join hub.clients c on c.client_id = n.client_id
                 where n.client_id = %s and n.nb_code = %s
                   and nullif(trim(b.customs_code), '') is not null
                   and trim(b.customs_code) <> n.nb_code
                   and not (trim(b.customs_code)
                            = any(c.customs_code_placeholders))
                 group by trim(b.customs_code)
                 order by n desc, code
                 limit 50
                """,
                (client_id, code),
            )
        return [{"code": r[0], "n": r[1]} for r in cur.fetchall()]
