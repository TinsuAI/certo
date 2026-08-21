"""Persist + confirm + link flatten decisions.

Lifecycle:
  1. preview-time: stash_decisions(pending_id, decisions) inserts pending rows.
  2. confirm-time: confirm_decision(decision_id, user_id, chosen_action) flips
     status to 'confirmed' or 'rejected'. Auto-decisions (`status='auto'`)
     bypass this step; they're inserted directly with status='auto' and never
     show up in the staff confirmation UI.
  3. materialization: link_to_version(decision_id, artifact_id) sets
     materialized_artifact_id once the corresponding version is committed.
"""
from __future__ import annotations

import json
import secrets
from typing import Sequence

from hub.app.database import connect
from hub.app.flatten.types import Decision


def _decision_id() -> str:
    return "dec_" + secrets.token_urlsafe(10)


def stash_decisions(*, pending_id: str, client_id: str,
                    decisions: Sequence[Decision]) -> dict[int, str]:
    """Insert decisions tied to a pending upload. Returns a mapping from
    each decision's positional index in the input sequence to its
    assigned decision_id. Auto-decisions land with status='auto'."""
    id_map: dict[int, str] = {}
    if not decisions:
        return id_map
    with connect() as conn:
        with conn.cursor() as cur:
            for i, d in enumerate(decisions):
                did = _decision_id()
                id_map[i] = did
                product_code = d.target_key.product_code if d.target_key else ""
                status = "auto" if not d.staff_confirmation_required else d.status
                cur.execute(
                    """
                    insert into hub.bom_flatten_decisions
                      (decision_id, pending_id, client_id, product_code,
                       decision_type, chosen_action, alternatives, evidence,
                       status, staff_confirmation_required)
                    values (%s, %s, %s, %s, %s, %s, %s::jsonb, %s::jsonb, %s, %s)
                    """,
                    (
                        did, pending_id, client_id, product_code,
                        d.decision_type, d.chosen_action,
                        json.dumps(d.alternatives, ensure_ascii=False),
                        json.dumps(d.evidence, ensure_ascii=False, default=str),
                        status, d.staff_confirmation_required,
                    ),
                )
    return id_map


def decisions_for_pending(pending_id: str) -> list[dict]:
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                select decision_id, decision_type, chosen_action, alternatives,
                       evidence, status, staff_confirmation_required,
                       confirmed_by, confirmed_at, materialized_artifact_id,
                       product_code
                from hub.bom_flatten_decisions
                where pending_id = %s
                order by created_at
                """,
                (pending_id,),
            )
            cols = [d[0] for d in cur.description]
            return [dict(zip(cols, r)) for r in cur.fetchall()]


def confirm_decision(*, decision_id: str, user_id: str | None,
                     chosen_action: str, status: str = "confirmed") -> None:
    if status not in ("confirmed", "rejected", "auto"):
        raise ValueError(f"invalid decision status: {status}")
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                update hub.bom_flatten_decisions
                set status = %s,
                    chosen_action = %s,
                    confirmed_by = %s,
                    confirmed_at = now()
                where decision_id = %s
                """,
                (status, chosen_action, user_id, decision_id),
            )


def link_to_version(*, decision_id: str, artifact_id: str) -> None:
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                update hub.bom_flatten_decisions
                set materialized_artifact_id = %s,
                    pending_id = null
                where decision_id = %s
                """,
                (artifact_id, decision_id),
            )
