"""Supplier origin-evidence flags — append-only event store (ticket #11).

Every flip of a supplier's Phụ lục X / import-C/O flag writes one row to
`co_supplier_evidence_events` (migration 019); current state = the latest
event per (client_id, supplier_key); the table is itself the flip log.

Storage follows the co_stock_events precedent: Postgres when
`BARRY_DATABASE_URL` is configured, otherwise `store_available()` is False and
the curation routes refuse the write loudly (a silently dropped evidence flag
would understate RVC forever).
"""
from __future__ import annotations

import secrets

from app.database import connect, database_url
from app.supplier_identity import supplier_key as normalize_supplier_key

EVIDENCE_KINDS = {"phu_luc_x", "co_import"}
ACTIONS = {"on", "off"}

EVIDENCE_KIND_LABELS = {
    "phu_luc_x": "Phụ lục X",
    "co_import": "C/O nhập khẩu",
}


def store_available() -> bool:
    return bool(database_url())


def record_flip(
    *,
    client_id: str,
    supplier_name: str,
    action: str,
    evidence_kind: str,
    actor_id: str = "",
    actor_email: str = "",
    note: str = "",
) -> dict:
    """Append one flip event. The supplier key is normalized HERE with the one
    shared function — callers pass the raw display name."""
    if action not in ACTIONS:
        raise ValueError(f"action must be one of {sorted(ACTIONS)}")
    if evidence_kind not in EVIDENCE_KINDS:
        raise ValueError(f"evidence_kind must be one of {sorted(EVIDENCE_KINDS)}")
    key = normalize_supplier_key(supplier_name)
    if not key:
        raise ValueError("supplier_name required")
    event = {
        "event_id": "sev_" + secrets.token_hex(10),
        "client_id": str(client_id or "").strip(),
        "supplier_key": key,
        "supplier_name": str(supplier_name or "").strip(),
        "action": action,
        "evidence_kind": evidence_kind,
        "actor_id": str(actor_id or "").strip(),
        "actor_email": str(actor_email or "").strip(),
        "note": str(note or "").strip(),
    }
    with connect() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                insert into co_supplier_evidence_events
                  (event_id, client_id, supplier_key, supplier_name, action,
                   evidence_kind, actor_id, actor_email, note)
                values (%(event_id)s, %(client_id)s, %(supplier_key)s, %(supplier_name)s,
                        %(action)s, %(evidence_kind)s, %(actor_id)s, %(actor_email)s, %(note)s)
                """,
                event,
            )
        connection.commit()
    return event


def current_flags(client_id: str) -> dict[str, dict]:
    """Latest event per supplier_key for a client. A supplier is FLAGGED iff
    its latest event has action='on'. Returns {} without a database."""
    if not store_available():
        return {}
    with connect() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                select distinct on (supplier_key)
                       supplier_key, supplier_name, action, evidence_kind,
                       actor_id, actor_email, note, created_at
                  from co_supplier_evidence_events
                 where client_id = %s
                 order by supplier_key, created_at desc, event_id desc
                """,
                (str(client_id or "").strip(),),
            )
            rows = cursor.fetchall()
    return {
        row[0]: {
            "supplier_key": row[0],
            "supplier_name": row[1],
            "action": row[2],
            "evidence_kind": row[3],
            "actor_id": row[4],
            "actor_email": row[5],
            "note": row[6],
            "created_at": row[7].isoformat() if row[7] else "",
        }
        for row in rows
    }


def flagged_suppliers(client_id: str) -> dict[str, dict]:
    """Only the suppliers whose CURRENT state is on — the read the Tính-time
    resolver uses."""
    return {
        key: entry
        for key, entry in current_flags(client_id).items()
        if entry.get("action") == "on"
    }


def list_events(client_id: str, supplier_key: str = "") -> list[dict]:
    if not store_available():
        return []
    query = """
        select event_id, supplier_key, supplier_name, action, evidence_kind,
               actor_id, actor_email, note, created_at
          from co_supplier_evidence_events
         where client_id = %s
    """
    params: list = [str(client_id or "").strip()]
    if supplier_key:
        query += " and supplier_key = %s"
        params.append(supplier_key)
    query += " order by created_at desc, event_id desc"
    with connect() as connection:
        with connection.cursor() as cursor:
            cursor.execute(query, params)
            rows = cursor.fetchall()
    return [
        {
            "event_id": row[0],
            "supplier_key": row[1],
            "supplier_name": row[2],
            "action": row[3],
            "evidence_kind": row[4],
            "actor_id": row[5],
            "actor_email": row[6],
            "note": row[7],
            "created_at": row[8].isoformat() if row[8] else "",
        }
        for row in rows
    ]
