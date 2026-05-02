"""BOM persistence + proposal-queue auto-rule."""
from __future__ import annotations

import hashlib
import json
import secrets
from typing import Any

from app.database import connect


def normalized_hash(rows: list[dict]) -> str:
    """Canonicalize BOM rows for idempotency: sort by (material_code, bom_variant_id),
    round qty to 9 decimals, NFC-trim text, exclude row_index."""
    canonical = []
    for r in sorted(rows, key=lambda r: (str(r.get("material_code", "")),
                                          str(r.get("bom_variant_id") or ""))):
        canonical.append({
            "material_code": (r.get("material_code") or "").strip(),
            "bom_code": (r.get("bom_code") or "") or None,
            "bom_variant_id": (r.get("bom_variant_id") or "") or None,
            "qty_per_unit": round(float(r.get("qty_per_unit") or 0), 9),
            "uom": (r.get("uom") or "") or None,
        })
    blob = json.dumps(canonical, sort_keys=True, ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()


def _next_version_no(cur, *, client_id: str, product_code: str) -> int:
    cur.execute(
        """
        select coalesce(max(version_no), 0) + 1
        from hub.bom_versions
        where client_id = %s and product_code = %s
        """,
        (client_id, product_code),
    )
    (n,) = cur.fetchone()
    return n


def create_version(*, client_id: str, product_code: str, rows: list[dict],
                   actor: str, intent: str, parent_version_id: str | None,
                   context: dict, source_upload_id: str | None) -> str | None:
    """Append a new BOM version. Idempotent on the constraint key. Returns version_id
    (or existing one if duplicate)."""
    nh = normalized_hash(rows)
    version_id = "bv_" + secrets.token_urlsafe(12)
    with connect() as conn:
        with conn.cursor() as cur:
            # Check idempotency manually to return existing version_id if dup.
            parent_norm = parent_version_id or "00000000-0000-0000-0000-000000000000"
            cur.execute(
                """
                select version_id from hub.bom_versions
                where client_id=%s and product_code=%s and actor=%s and intent=%s
                  and parent_norm=%s and normalized_hash=%s
                """,
                (client_id, product_code, actor, intent, parent_norm, nh),
            )
            existing = cur.fetchone()
            if existing:
                return existing[0]
            version_no = _next_version_no(cur, client_id=client_id, product_code=product_code)
            cur.execute(
                """
                insert into hub.bom_versions
                  (version_id, client_id, product_code, version_no, actor, intent,
                   parent_version_id, context, source_upload_id, normalized_hash,
                   row_count, status, published_at)
                values (%s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s, %s, %s, 'published', now())
                """,
                (version_id, client_id, product_code, version_no, actor, intent,
                 parent_version_id, json.dumps(context), source_upload_id, nh, len(rows)),
            )
            for i, r in enumerate(rows):
                cur.execute(
                    """
                    insert into hub.bom_version_rows
                      (version_id, row_index, material_code, bom_code, bom_variant_id,
                       qty_per_unit, uom, payload)
                    values (%s, %s, %s, %s, %s, %s, %s, %s::jsonb)
                    """,
                    (version_id, i, r["material_code"],
                     r.get("bom_code"), r.get("bom_variant_id"),
                     r.get("qty_per_unit") or 0, r.get("uom"),
                     json.dumps({k: v for k, v in r.items()
                                 if k not in {"material_code","bom_code","bom_variant_id","qty_per_unit","uom"}})),
                )
            cur.execute(
                """
                insert into hub.bom_audit_events (client_id, product_code, version_id, event_type, actor, details)
                values (%s, %s, %s, 'version.created', %s, %s::jsonb)
                """,
                (client_id, product_code, version_id, actor, json.dumps({"intent": intent})),
            )
    return version_id


def list_products_with_bom(client_id: str) -> list[dict]:
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                select product_code,
                       count(*) as n_versions,
                       max(version_no) as latest_version,
                       max(published_at) as last_published
                from hub.bom_versions
                where client_id = %s and tombstoned_at is null
                group by product_code
                order by max(published_at) desc nulls last
                """,
                (client_id,),
            )
            cols = [d[0] for d in cur.description]
            return [dict(zip(cols, r)) for r in cur.fetchall()]


def list_versions_for_product(*, client_id: str, product_code: str) -> list[dict]:
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                select version_id, version_no, actor, intent, parent_version_id,
                       row_count, normalized_hash, status, tombstoned_at,
                       created_at, published_at, context
                from hub.bom_versions
                where client_id = %s and product_code = %s
                order by version_no desc
                """,
                (client_id, product_code),
            )
            cols = [d[0] for d in cur.description]
            return [dict(zip(cols, r)) for r in cur.fetchall()]


def get_version_with_rows(version_id: str) -> dict | None:
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                select version_id, client_id, product_code, version_no, actor, intent,
                       parent_version_id, context, normalized_hash, row_count,
                       status, tombstoned_at, created_at, published_at
                from hub.bom_versions where version_id = %s
                """,
                (version_id,),
            )
            row = cur.fetchone()
            if not row:
                return None
            cols = [d[0] for d in cur.description]
            version = dict(zip(cols, row))
            cur.execute(
                """
                select row_index, material_code, bom_code, bom_variant_id,
                       qty_per_unit, uom, payload
                from hub.bom_version_rows where version_id = %s
                order by row_index
                """,
                (version_id,),
            )
            cols2 = [d[0] for d in cur.description]
            rows = [dict(zip(cols2, r)) for r in cur.fetchall()]
            return {"version": version, "rows": rows}


# ---- Proposal queue ----

def proposal_requires_parent_version(*, actor: str, intent: str) -> bool:
    return actor == "co_system" or intent == "modified_for_case"


def validate_proposal_contract(*, actor: str, intent: str,
                               parent_version_id: str | None) -> None:
    if proposal_requires_parent_version(actor=actor, intent=intent) and not parent_version_id:
        raise ValueError("parent_version_id is required for CO modified_for_case proposals")


def submit_proposal(*, client_id: str, product_code: str, actor: str, intent: str,
                    parent_version_id: str | None, context: dict,
                    rows: list[dict]) -> dict:
    """Submit a BOM proposal. Auto-rule evaluates synchronously. Returns
    {status, ...} dict."""
    validate_proposal_contract(
        actor=actor, intent=intent, parent_version_id=parent_version_id,
    )
    proposal_id = "prop_" + secrets.token_urlsafe(12)
    nh = normalized_hash(rows)

    # Idempotency: if a same-key proposal exists, return its outcome.
    with connect() as conn:
        with conn.cursor() as cur:
            parent_norm = parent_version_id or "00000000-0000-0000-0000-000000000000"
            cur.execute(
                """
                select proposal_id, status, materialized_version_id, decision_reason,
                       failed_conditions
                from hub.bom_change_requests
                where client_id=%s and product_code=%s and actor=%s and intent=%s
                  and coalesce(parent_version_id, '00000000-0000-0000-0000-000000000000') = %s
                  and normalized_hash=%s
                order by created_at desc limit 1
                """,
                (client_id, product_code, actor, intent, parent_norm, nh),
            )
            existing = cur.fetchone()
            if existing:
                return {
                    "proposal_id": existing[0],
                    "status": existing[1],
                    "version_id": existing[2],
                    "decision_reason": existing[3],
                    "failed_conditions": existing[4] or [],
                    "idempotent": True,
                }

    decision = _auto_evaluate(
        client_id=client_id, product_code=product_code,
        parent_version_id=parent_version_id, context=context, rows=rows,
    )

    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                insert into hub.bom_change_requests
                  (proposal_id, client_id, product_code, actor, intent,
                   parent_version_id, context, rows_payload, normalized_hash,
                   status, decided_at, decided_by, decision_reason, failed_conditions)
                values (%s, %s, %s, %s, %s, %s, %s::jsonb, %s::jsonb, %s,
                        %s, now(), 'auto-rule', %s, %s::jsonb)
                """,
                (proposal_id, client_id, product_code, actor, intent,
                 parent_version_id, json.dumps(context), json.dumps(rows), nh,
                 "approved" if decision["approved"] else "rejected",
                 decision["reason"], json.dumps(decision.get("failed", []))),
            )
    if decision["approved"]:
        version_id = create_version(
            client_id=client_id, product_code=product_code, rows=rows,
            actor=actor, intent=intent, parent_version_id=parent_version_id,
            context={**context, "proposal_id": proposal_id},
            source_upload_id=None,
        )
        with connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "update hub.bom_change_requests set materialized_version_id=%s where proposal_id=%s",
                    (version_id, proposal_id),
                )
        return {
            "proposal_id": proposal_id, "status": "approved",
            "version_id": version_id, "decision_reason": decision["reason"],
            "failed_conditions": [],
        }
    # Auto-rule rejected this proposal — fan-out to every staff member
    # with edit access to the client so someone can review/override.
    try:
        from app import notifications as _notifs
        user_ids = _notifs.staff_with_edit_access_to_client(client_id)
        _notifs.notify_many(
            user_ids=user_ids, kind="bom_proposal_rejected",
            title=f"BOM proposal cho {product_code} bị reject",
            body=(f"Reason: {decision['reason']}. "
                  f"Cần staff review thủ công."),
            link_url=f"/clients/{client_id}/proposals",
            client_id=client_id, related_kind="bom_change_requests",
            related_id=proposal_id,
        )
    except Exception:
        pass  # notification is non-critical

    return {
        "proposal_id": proposal_id, "status": "rejected",
        "version_id": None, "decision_reason": decision["reason"],
        "failed_conditions": decision.get("failed", []),
    }


def _auto_evaluate(*, client_id: str, product_code: str,
                   parent_version_id: str | None, context: dict,
                   rows: list[dict]) -> dict:
    """Apply 5-condition auto-rule. Speculative criteria — to be tuned with
    the first real CO modification implementation."""
    failed: list[str] = []

    # 1. Parent version exists for this dncx + product
    if parent_version_id is not None:
        with connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    select 1 from hub.bom_versions
                    where version_id=%s and client_id=%s and product_code=%s
                    """,
                    (parent_version_id, client_id, product_code),
                )
                if not cur.fetchone():
                    failed.append("parent_version_id_invalid")

    # 2. context.case_id presence — DROPPED in MVP per design decision (no service-discovery to CO yet).
    # Phase 2: validate against an active CO case via API.

    # 3 & 5. Row delta vs parent: only NVL substitutions; qty changes within tolerance; NVL count growth ≤ 1.
    if parent_version_id:
        with connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    select bom_proposal_qty_tolerance_pct from hub.clients where client_id = %s
                    """,
                    (client_id,),
                )
                row = cur.fetchone()
                tolerance = float(row[0]) if row else 5.0
                cur.execute(
                    """
                    select material_code, qty_per_unit
                    from hub.bom_version_rows where version_id=%s
                    """,
                    (parent_version_id,),
                )
                parent_rows = {m: float(q or 0) for (m, q) in cur.fetchall()}
        proposed_rows = {r["material_code"]: float(r.get("qty_per_unit") or 0) for r in rows}
        # qty change tolerance for kept materials
        for m, q in proposed_rows.items():
            if m in parent_rows and parent_rows[m] != 0:
                pct = abs(q - parent_rows[m]) / parent_rows[m] * 100
                if pct > tolerance:
                    failed.append(f"qty_delta_exceeds_tolerance:{m}:{pct:.2f}%")
        # anti-bloat
        added = set(proposed_rows.keys()) - set(parent_rows.keys())
        if len(added) > 1:
            failed.append(f"too_many_new_materials:{len(added)}")

    # 4. All material_codes exist + active in hub.materials
    if rows:
        with connect() as conn:
            with conn.cursor() as cur:
                codes = list({r["material_code"] for r in rows})
                cur.execute(
                    """
                    select customs_code from hub.materials
                    where client_id = %s and customs_code = any(%s) and status = 'active'
                    """,
                    (client_id, codes),
                )
                active = {c for (c,) in cur.fetchall()}
        missing = [c for c in codes if c not in active]
        if missing:
            failed.append(f"unknown_or_inactive_materials:{','.join(sorted(missing)[:5])}")

    if failed:
        return {"approved": False, "reason": "auto-rule rejected", "failed": failed}
    return {"approved": True, "reason": "auto-rule approved", "failed": []}
