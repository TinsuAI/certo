"""hub.bcct_nb_codes — persisted BCCT paren extraction (#33, BACKLOG A.5).

The one deliberately persisted derivation in the catalog (brief
Decision 4): SQL cannot run the re2 parser rules (mig 050), so Python
extracts NB codes from goods_name and stores (client_id,
transaction_key, line_no, nb_code); views join it
(v_material_roles, v_material_classification — mig 091).

Invalidation is delete-and-rebuild per client (measured ~2s on
Growatt's 39k rows): triggered by a BCCT apply or any parser-rule
edit, backfilled at app boot when empty. NOT an incremental staleness
domain.
"""
from __future__ import annotations

from app.database import connect
from app.parsers.catalog_candidates import candidates_from_bcct_row
from app.parsers.client_parser_rules import load_rules
from app.stores.provenance import customs_code_placeholders


def rebuild_for_client(client_id: str) -> int:
    """Delete-and-rebuild the client's half of the link table.

    Clients without enabled internal_code rules (Johnson-shape) end up
    with an empty half. Returns the number of link rows written.
    """
    rules = load_rules(client_id=client_id, output_field="internal_code")
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "delete from hub.bcct_nb_codes where client_id = %s", (client_id,),
        )
        if not rules:
            return 0
        placeholders = customs_code_placeholders(cur, client_id=client_id)
        cur.execute(
            "select transaction_key, line_no, customs_code, goods_name "
            "from hub.bcct_rows where client_id = %s",
            (client_id,),
        )
        links: set[tuple[str, str, str]] = set()
        for txn, line, cc, gn in cur.fetchall():
            cands = candidates_from_bcct_row(
                {"customs_code": cc, "goods_name": gn},
                rules=rules, has_dual_system=True, placeholders=placeholders,
            )
            for code, kind in cands:
                if kind == "nb":
                    links.add((txn, line, code))
        if links:
            cur.executemany(
                "insert into hub.bcct_nb_codes "
                "(client_id, transaction_key, line_no, nb_code) "
                "values (%s, %s, %s, %s)",
                [(client_id, t, ln, code) for t, ln, code in links],
            )
        return len(links)


def rebuild_after_change(client_id: str) -> None:
    """Non-fatal trigger for ingest / rule-edit call sites (#32 pattern):
    a failed rebuild must not fail the write that triggered it — the
    boot backfill and the next trigger retry it."""
    import logging
    try:
        rebuild_for_client(client_id)
    except Exception:
        logging.getLogger(__name__).exception(
            "bcct_nb_codes rebuild failed for %s", client_id,
        )


def backfill_if_empty() -> list[str]:
    """Boot-time backfill: rebuild every client that has enabled
    internal_code rules and BCCT rows but no nb_codes rows yet.
    Idempotent; returns the client_ids that were filled."""
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            """
            select distinct r.client_id
              from hub.client_parser_rules r
             where r.output_field = 'internal_code' and r.enabled
               and exists (select 1 from hub.bcct_rows b
                            where b.client_id = r.client_id)
               and not exists (select 1 from hub.bcct_nb_codes n
                                where n.client_id = r.client_id)
            """
        )
        pending = [r[0] for r in cur.fetchall()]
    for cid in pending:
        rebuild_for_client(cid)
    return pending
