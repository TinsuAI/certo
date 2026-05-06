"""BOM persistence + proposal-queue auto-rule + flatten materialization."""
from __future__ import annotations

import hashlib
import json
import secrets
from decimal import Decimal
from typing import Any, Iterable, Literal

from app.database import connect
from app.flatten import (
    FLATTEN_METHOD, FLATTEN_METHOD_VERSION, FlattenResult, FlattenedVersion,
    build_display_label,
)
from app.flatten.types import CatalogEntry, ParsedBom, ParsedRow
from app.stores import flatten_decisions as decisions_store


BomShape = Literal["raw_graph", "shallow", "full_flat"]


def bom_shape(flatten_status: str, flatten_strategy: str) -> BomShape:
    """Derive the v3 3-shape concept from existing flatten_status + flatten_strategy.

    - raw_graph: edges-only graph stored in hub.bom_edges (non_flattened).
    - shallow: flat rows where leaves may be NVL or BTP (BTP-boundary).
    - full_flat: flat rows where every leaf is NVL (BTPs fully exploded).

    Lives as a derivation, not a stored column, to avoid schema redundancy
    with flatten_status + flatten_strategy. Use this helper anywhere the
    semantic 3-shape framing is clearer than the underlying columns.
    """
    if flatten_status == "non_flattened":
        return "raw_graph"
    if flatten_strategy in ("manual_flat_as_provided", "purchased_btp_as_leaf"):
        return "shallow"
    if flatten_strategy in ("technical_exploded", "self_produced_btp_exploded"):
        return "full_flat"
    # mixed_confirmed and no_strategy with status=flattened: treat as shallow
    # (conservative — leaves may still include BTPs).
    return "shallow"


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


def normalized_edges_hash(edges: list[dict]) -> str:
    canonical = []
    for e in sorted(
        edges,
        key=lambda e: (
            str(e.get("root_code", "")),
            str(e.get("parent_code", "")),
            str(e.get("child_code", "")),
            int(e.get("row_index") or 0),
        ),
    ):
        canonical.append({
            "root_code": (e.get("root_code") or "").strip(),
            "parent_code": (e.get("parent_code") or "").strip(),
            "child_code": (e.get("child_code") or "").strip(),
            "qty_per_parent": round(float(e.get("qty_per_parent") or 0), 9),
            "uom": (e.get("uom") or "") or None,
            "level": e.get("level"),
            "node_path": (e.get("node_path") or "") or None,
            "sheet_name": (e.get("sheet_name") or "") or None,
            "source_row_no": e.get("source_row_no"),
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


def create_raw_version(*, client_id: str, product_code: str, edges: list[dict],
                       actor: str, intent: str,
                       parent_version_id: str | None,
                       context: dict, source_upload_id: str | None,
                       source_channel: str = "agency_upload",
                       bom_code: str | None = None,
                       bom_variant_id: str | None = None,
                       lineage: dict | None = None,
                       display_label: str | None = None,
                       cursor=None,
                       ) -> str | None:
    """Append a technical_raw BOM version backed by hub.bom_edges.

    Raw versions intentionally do not write hub.bom_version_rows; consumers
    should use a derived technical_flattened/staff_flat version for flat rows.
    """
    if cursor is not None:
        return _create_raw_version_inner(
            cursor,
            client_id=client_id, product_code=product_code, edges=edges,
            actor=actor, intent=intent, parent_version_id=parent_version_id,
            context=context, source_upload_id=source_upload_id,
            source_channel=source_channel, bom_code=bom_code,
            bom_variant_id=bom_variant_id, lineage=lineage,
            display_label=display_label,
        )
    with connect() as conn:
        with conn.cursor() as cur:
            return _create_raw_version_inner(
                cur,
                client_id=client_id, product_code=product_code, edges=edges,
                actor=actor, intent=intent, parent_version_id=parent_version_id,
                context=context, source_upload_id=source_upload_id,
                source_channel=source_channel, bom_code=bom_code,
                bom_variant_id=bom_variant_id, lineage=lineage,
                display_label=display_label,
            )


def _create_raw_version_inner(cur, *, client_id, product_code, edges,
                              actor, intent, parent_version_id, context,
                              source_upload_id, source_channel, bom_code,
                              bom_variant_id, lineage, display_label):
    if not edges:
        from app.parsers.bom_adapters import BomParseError
        raise BomParseError("Raw BOM requires at least one edge")
    bad_qty = [
        (i, e.get("parent_code"), e.get("child_code"), e.get("qty_per_parent"))
        for i, e in enumerate(edges)
        if e.get("qty_per_parent") is None or float(e.get("qty_per_parent") or 0) <= 0
    ]
    if bad_qty:
        from app.parsers.bom_adapters import BomParseError
        sample = ", ".join(
            f"row {i} ({p!r}->{c!r})={q!r}"
            for i, p, c, q in bad_qty[:5]
        )
        raise BomParseError(
            f"Raw BOM has {len(bad_qty)} edge(s) with qty_per_parent <= 0. "
            f"First few: {sample}",
        )

    nh = normalized_edges_hash(edges)
    version_id = "bv_" + secrets.token_urlsafe(12)
    bom_code_norm = bom_code or ""
    bom_variant_id_norm = bom_variant_id or "default"
    parent_norm = parent_version_id or "00000000-0000-0000-0000-000000000000"
    flatten_strategy = "no_strategy"
    cur.execute(
        """
        select version_id from hub.bom_versions
        where client_id=%s and product_code=%s and actor=%s and intent=%s
          and parent_norm=%s and normalized_hash=%s
          and coalesce(flatten_strategy,'') = %s
          and coalesce(bom_variant_id,'default') = %s
        """,
        (client_id, product_code, actor, intent, parent_norm, nh,
         flatten_strategy, bom_variant_id_norm),
    )
    existing = cur.fetchone()
    if existing:
        return existing[0]

    version_no = _next_version_no_for_variant(
        cur, client_id=client_id, product_code=product_code,
        bom_variant_id=bom_variant_id_norm,
    )
    label = display_label or build_display_label(
        product_code=product_code,
        bom_variant_id=bom_variant_id_norm,
        version_no=version_no,
        source_bom_kind="technical_raw",
        flatten_status="non_flattened",
        flatten_strategy=flatten_strategy,
    )
    cur.execute(
        """
        insert into hub.bom_versions
          (version_id, client_id, product_code, version_no, actor, intent,
           parent_version_id, context, source_upload_id, normalized_hash,
           row_count, status, published_at,
           source_bom_kind, flatten_status, flatten_strategy,
           source_channel, bom_code, bom_variant_id, lineage,
           display_label, flatten_method, flatten_method_version)
        values (%s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s, %s, %s,
                'published', now(),
                'technical_raw', 'non_flattened', %s,
                %s, %s, %s, %s::jsonb,
                %s, 'none', '0')
        """,
        (version_id, client_id, product_code, version_no, actor, intent,
         parent_version_id, json.dumps(context), source_upload_id, nh, len(edges),
         flatten_strategy, source_channel, bom_code_norm or None,
         bom_variant_id_norm,
         json.dumps(lineage or {}, ensure_ascii=False, default=str), label),
    )
    for i, e in enumerate(edges):
        payload = dict(e.get("payload") or {})
        cur.execute(
            """
            insert into hub.bom_edges
              (version_id, row_index, root_code, parent_code, child_code,
               qty_per_parent, uom, level, node_path, sheet_name,
               source_row_no, payload)
            values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb)
            """,
            (
                version_id, int(e.get("row_index") if e.get("row_index") is not None else i),
                e["root_code"], e["parent_code"], e["child_code"],
                e["qty_per_parent"], e.get("uom"), e.get("level"),
                e.get("node_path"), e.get("sheet_name"), e.get("source_row_no"),
                json.dumps(payload, ensure_ascii=False, default=str),
            ),
        )
    cur.execute(
        """
        insert into hub.bom_audit_events
          (client_id, product_code, version_id, event_type, actor, details)
        values (%s, %s, %s, 'version.created', %s, %s::jsonb)
        """,
        (client_id, product_code, version_id, actor,
         json.dumps({"intent": intent,
                     "source_bom_kind": "technical_raw",
                     "flatten_status": "non_flattened",
                     "flatten_strategy": flatten_strategy})),
    )
    return version_id


def create_version(*, client_id: str, product_code: str, rows: list[dict],
                   actor: str, intent: str, parent_version_id: str | None,
                   context: dict, source_upload_id: str | None,
                   # Flatten/identity fields — defaults preserve manual_flat
                   # backward compat. Caller (create_flattened_version_set)
                   # overrides these for technical_flatten.
                   source_bom_kind: str = "manual_flat",
                   flatten_status: str = "not_applicable",
                   flatten_strategy: str = "manual_flat_as_provided",
                   source_channel: str = "agency_upload",
                   bom_code: str | None = None,
                   bom_variant_id: str | None = None,
                   lineage: dict | None = None,
                   flatten_method: str = "none",
                   flatten_method_version: str = "0",
                   display_label: str | None = None,
                   # /rev finding C1: optional cursor for transactional
                   # composition with create_flattened_version_set.
                   cursor=None,
                   ) -> str | None:
    """Append a new BOM version. Idempotent on the constraint key.
    Returns version_id (or existing one if duplicate).

    If `cursor` is provided, runs SQL ops on it without managing the
    connection lifecycle — caller (create_flattened_version_set) is
    responsible for transaction boundaries. Otherwise opens a fresh
    connection + transaction.
    """
    if cursor is not None:
        return _create_version_inner(
            cursor,
            client_id=client_id, product_code=product_code, rows=rows,
            actor=actor, intent=intent, parent_version_id=parent_version_id,
            context=context, source_upload_id=source_upload_id,
            source_bom_kind=source_bom_kind, flatten_status=flatten_status,
            flatten_strategy=flatten_strategy, source_channel=source_channel,
            bom_code=bom_code, bom_variant_id=bom_variant_id,
            lineage=lineage, flatten_method=flatten_method,
            flatten_method_version=flatten_method_version,
            display_label=display_label,
        )
    with connect() as conn:
        with conn.cursor() as cur:
            return _create_version_inner(
                cur,
                client_id=client_id, product_code=product_code, rows=rows,
                actor=actor, intent=intent, parent_version_id=parent_version_id,
                context=context, source_upload_id=source_upload_id,
                source_bom_kind=source_bom_kind, flatten_status=flatten_status,
                flatten_strategy=flatten_strategy, source_channel=source_channel,
                bom_code=bom_code, bom_variant_id=bom_variant_id,
                lineage=lineage, flatten_method=flatten_method,
                flatten_method_version=flatten_method_version,
                display_label=display_label,
            )


def _create_version_inner(cur, *, client_id, product_code, rows, actor, intent,
                          parent_version_id, context, source_upload_id,
                          source_bom_kind, flatten_status, flatten_strategy,
                          source_channel, bom_code, bom_variant_id, lineage,
                          flatten_method, flatten_method_version, display_label):
    nh = normalized_hash(rows)
    version_id = "bv_" + secrets.token_urlsafe(12)
    bom_code_norm = bom_code or ""
    bom_variant_id_norm = bom_variant_id or "default"
    parent_norm = parent_version_id or "00000000-0000-0000-0000-000000000000"
    cur.execute(
        """
        select version_id from hub.bom_versions
        where client_id=%s and product_code=%s and actor=%s and intent=%s
          and parent_norm=%s and normalized_hash=%s
          and coalesce(flatten_strategy,'') = %s
          and coalesce(bom_variant_id,'default') = %s
        """,
        (client_id, product_code, actor, intent, parent_norm, nh,
         flatten_strategy, bom_variant_id_norm),
    )
    existing = cur.fetchone()
    if existing:
        return existing[0]
    version_no = _next_version_no_for_variant(
        cur, client_id=client_id, product_code=product_code,
        bom_variant_id=bom_variant_id_norm,
    )
    label = display_label or build_display_label(
        product_code=product_code,
        bom_variant_id=bom_variant_id_norm,
        version_no=version_no,
        source_bom_kind=source_bom_kind,
        flatten_status=flatten_status,
        flatten_strategy=flatten_strategy,
    )
    cur.execute(
        """
        insert into hub.bom_versions
          (version_id, client_id, product_code, version_no, actor, intent,
           parent_version_id, context, source_upload_id, normalized_hash,
           row_count, status, published_at,
           source_bom_kind, flatten_status, flatten_strategy,
           source_channel, bom_code, bom_variant_id, lineage,
           display_label, flatten_method, flatten_method_version)
        values (%s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s, %s, %s,
                'published', now(),
                %s, %s, %s, %s, %s, %s, %s::jsonb,
                %s, %s, %s)
        """,
        (version_id, client_id, product_code, version_no, actor, intent,
         parent_version_id, json.dumps(context), source_upload_id, nh, len(rows),
         source_bom_kind, flatten_status, flatten_strategy,
         source_channel, bom_code_norm or None, bom_variant_id_norm,
         json.dumps(lineage or {}, ensure_ascii=False, default=str),
         label, flatten_method, flatten_method_version),
    )
    # Belt-and-suspenders qty validation. DB has chk_qty_per_unit_positive
    # (migration 026) so the INSERT would error anyway, but pre-validating
    # here surfaces a precise message ("row N: material X qty=...") instead
    # of a generic constraint-violation rollback the user has to puzzle out.
    bad_qty = [
        (i, r.get("material_code"), r.get("qty_per_unit"))
        for i, r in enumerate(rows)
        if r.get("qty_per_unit") is None or float(r.get("qty_per_unit") or 0) <= 0
    ]
    if bad_qty:
        from app.parsers.bom_adapters import BomParseError
        sample = ", ".join(f"row {i} ({mat!r})={q!r}" for i, mat, q in bad_qty[:5])
        raise BomParseError(
            f"BOM has {len(bad_qty)} row(s) with qty_per_unit <= 0 or NULL. "
            f"Fix the source workbook or remove these rows. First few: {sample}",
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
             r["qty_per_unit"], r.get("uom"),
             json.dumps({k: v for k, v in r.items()
                         if k not in {"material_code","bom_code","bom_variant_id","qty_per_unit","uom"}},
                        default=str)),
        )
    cur.execute(
        """
        insert into hub.bom_audit_events (client_id, product_code, version_id, event_type, actor, details)
        values (%s, %s, %s, 'version.created', %s, %s::jsonb)
        """,
        (client_id, product_code, version_id, actor,
         json.dumps({"intent": intent,
                     "source_bom_kind": source_bom_kind,
                     "flatten_status": flatten_status,
                     "flatten_strategy": flatten_strategy})),
    )
    return version_id


def _next_version_no_for_variant(cur, *, client_id: str, product_code: str,
                                 bom_variant_id: str) -> int:
    """Variant-scoped version_no — spec §3A: 'version_no must not mix
    unrelated variants. If bom_variant_id creates a distinct variant,
    version_no must be scoped to that variant key.'"""
    cur.execute(
        """
        select coalesce(max(version_no), 0) + 1
        from hub.bom_versions
        where client_id = %s and product_code = %s
          and coalesce(bom_variant_id, 'default') = %s
        """,
        (client_id, product_code, bom_variant_id),
    )
    (n,) = cur.fetchone()
    return n


_BOM_PRODUCTS_ORDER_DEFAULT = (
    "a.n_non_flattened desc, a.last_published desc nulls last"
)


def list_products_with_bom(client_id: str, *,
                           q: str | None = None,
                           order_by: str = _BOM_PRODUCTS_ORDER_DEFAULT,
                           limit: int = 50, offset: int = 0) -> list[dict]:
    """List BOM products plus flatten-aware metadata per product.

    Per-product fields:
      n_versions:           total alive versions (any flatten_status).
      n_flattened:          count where flatten_status in (flattened, not_applicable).
      n_non_flattened:      count where flatten_status = non_flattened.
      n_dual_variants:      count of distinct flatten_strategies among
                            flattened versions — >1 ⇒ dual-source variants live.
      latest_version:       max version_no.
      last_published:       most recent published_at.
      latest_flatten_status: status of the most-recently-published version.
      product_kind:         'btp' if hub.materials.category in (btp_sx,btp_nm),
                            else 'tp'. Falls back to 'tp' when no catalog entry.
    Used by bom.html for status badges + the All/Flattened/Non-flattened filter.

    `q` filters by product_code substring (ILIKE). `order_by`,
    `limit`, `offset` drive pagination + caller-chosen sort.
    """
    where_q = ""
    params_q: list = []
    if q:
        where_q = " and product_code ilike %s"
        params_q = [f"%{q}%"]
    sql = f"""
        with v as (
            select product_code, version_no, published_at, flatten_status,
                   flatten_strategy,
                   row_number() over (
                       partition by product_code
                       order by published_at desc nulls last, version_no desc
                   ) as rn
            from hub.bom_versions
            where client_id = %s and tombstoned_at is null{where_q}
        ),
        aggr as (
            select product_code,
                   count(*) as n_versions,
                   count(*) filter (where flatten_status in ('flattened','not_applicable')) as n_flattened,
                   count(*) filter (where flatten_status = 'non_flattened') as n_non_flattened,
                   count(distinct flatten_strategy) filter (where flatten_status = 'flattened') as n_strategies,
                   max(version_no) as latest_version,
                   max(published_at) as last_published
            from v group by product_code
        )
        select a.product_code, a.n_versions, a.n_flattened, a.n_non_flattened,
               a.n_strategies, a.latest_version, a.last_published,
               latest.flatten_status as latest_flatten_status,
               coalesce(m.category, 'tp') as raw_category
        from aggr a
        left join v latest on latest.product_code = a.product_code and latest.rn = 1
        left join hub.materials m
               on m.client_id = %s and m.customs_code = a.product_code
        order by {order_by}
        limit %s offset %s
    """
    params = [client_id, *params_q, client_id, limit, offset]
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            cols = [d[0] for d in cur.description]
            out = []
            for r in cur.fetchall():
                d = dict(zip(cols, r))
                # Catalog says BTP iff category in btp_*; otherwise treat as TP.
                d["product_kind"] = "btp" if d.pop("raw_category") in ("btp_sx", "btp_nm") else "tp"
                d["n_dual_variants"] = d.pop("n_strategies")
                out.append(d)
            return out


def count_products_with_bom(client_id: str, *, q: str | None = None) -> int:
    """Count distinct BOM products matching the same filter shape as
    `list_products_with_bom`."""
    where_q = ""
    params: list = [client_id]
    if q:
        where_q = " and product_code ilike %s"
        params.append(f"%{q}%")
    sql = f"""
        select count(distinct product_code)
        from hub.bom_versions
        where client_id = %s and tombstoned_at is null{where_q}
    """
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            (n,) = cur.fetchone()
    return n


def list_versions_for_product(*, client_id: str, product_code: str) -> list[dict]:
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                select v.version_id, v.version_no, v.actor, v.intent, v.parent_version_id,
                       v.row_count, v.normalized_hash, v.status, v.tombstoned_at,
                       v.created_at, v.published_at, v.context,
                       v.bom_variant_id, v.source_bom_kind, v.source_channel,
                       v.flatten_status, v.flatten_strategy,
                       p.version_no       as parent_version_no,
                       p.bom_variant_id   as parent_variant_id,
                       p.flatten_status   as parent_flatten_status,
                       p.flatten_strategy as parent_flatten_strategy
                from hub.bom_versions v
                left join hub.bom_versions p on p.version_id = v.parent_version_id
                where v.client_id = %s and v.product_code = %s
                order by v.created_at desc, v.version_no desc
                """,
                (client_id, product_code),
            )
            cols = [d[0] for d in cur.description]
            out = []
            for r in cur.fetchall():
                row = dict(zip(cols, r))
                row["bom_shape"] = bom_shape(
                    row.get("flatten_status") or "",
                    row.get("flatten_strategy") or "",
                )
                if row.get("parent_version_id"):
                    row["parent_shape"] = bom_shape(
                        row.get("parent_flatten_status") or "",
                        row.get("parent_flatten_strategy") or "",
                    )
                else:
                    row["parent_shape"] = None
                out.append(row)
            return out


def get_version_with_rows(version_id: str) -> dict | None:
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                select version_id, client_id, product_code, version_no, actor, intent,
                       parent_version_id, context, normalized_hash, row_count,
                       status, tombstoned_at, tombstone_reason, created_at, published_at,
                       source_bom_kind, flatten_status, flatten_strategy,
                       source_channel, bom_code, bom_variant_id, lineage,
                       display_label, flatten_method, flatten_method_version
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
            cur.execute(
                """
                select row_index, root_code, parent_code, child_code,
                       qty_per_parent, uom, level, node_path, sheet_name,
                       source_row_no, payload
                from hub.bom_edges where version_id = %s
                order by row_index
                """,
                (version_id,),
            )
            cols3 = [d[0] for d in cur.description]
            edges = [dict(zip(cols3, r)) for r in cur.fetchall()]
            unresolved = get_unresolved_for_version(version_id)
            decisions = get_decisions_for_version(version_id)
            return {
                "version": version, "rows": rows, "edges": edges,
                "unresolved": unresolved, "decisions": decisions,
            }


def get_lineage_for_version(version_id: str, *, max_depth: int = 12) -> dict:
    """Return ancestor chain (root → ... → parent) and direct descendants
    for a given version_id. Each node carries human-readable identity:
    version_id, version_no, bom_variant_id, shape (derived), intent, actor,
    status, tombstoned_at, created_at.

    `truncated` flag is set if max_depth was hit before reaching a root —
    callers can render a "(older ancestors hidden)" marker.
    `missing_parent_id` is the dangling parent_version_id when the chain
    broke because a parent row was deleted."""

    def _row_to_node(cur, row) -> dict:
        node = dict(zip([d[0] for d in cur.description], row))
        node["bom_shape"] = bom_shape(
            node.get("flatten_status") or "",
            node.get("flatten_strategy") or "",
        )
        return node

    fields = (
        "version_id, version_no, bom_variant_id, intent, actor, status, "
        "tombstoned_at, created_at, parent_version_id, "
        "flatten_status, flatten_strategy"
    )
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"select {fields} from hub.bom_versions where version_id = %s",
                (version_id,),
            )
            row = cur.fetchone()
            if row is None:
                return {"ancestors": [], "descendants": [],
                        "truncated": False, "missing_parent_id": None}
            current_node = _row_to_node(cur, row)

            ancestors: list[dict] = []
            seen: set[str] = {version_id}
            truncated = False
            missing_parent_id: str | None = None
            for _ in range(max_depth):
                parent_id = current_node.get("parent_version_id")
                if not parent_id:
                    break
                if parent_id in seen:
                    break
                seen.add(parent_id)
                cur.execute(
                    f"select {fields} from hub.bom_versions where version_id = %s",
                    (parent_id,),
                )
                prow = cur.fetchone()
                if prow is None:
                    missing_parent_id = parent_id
                    break
                parent_node = _row_to_node(cur, prow)
                ancestors.append(parent_node)
                current_node = parent_node
            else:
                # for-else: ran max_depth iterations without breaking → check
                # if there's still an unfetched parent above the wall.
                if current_node.get("parent_version_id"):
                    truncated = True
            ancestors.reverse()

            cur.execute(
                f"select {fields} from hub.bom_versions where parent_version_id = %s "
                "order by version_no desc, created_at desc",
                (version_id,),
            )
            descendants = [_row_to_node(cur, r) for r in cur.fetchall()]

            return {"ancestors": ancestors, "descendants": descendants,
                    "truncated": truncated, "missing_parent_id": missing_parent_id}


# ---- Proposal queue ----

PROPOSAL_MODES = ("auto", "manual", "hybrid")


class ProposalNotFound(Exception):
    pass


class ProposalNotPending(Exception):
    """Raised when an action requires status='pending' but the proposal
    has already been decided or withdrawn."""


def proposal_requires_parent_version(*, actor: str, intent: str) -> bool:
    return actor == "co_system" or intent == "modified_for_case"


def validate_proposal_contract(*, actor: str, intent: str,
                               parent_version_id: str | None) -> None:
    if proposal_requires_parent_version(actor=actor, intent=intent) and not parent_version_id:
        raise ValueError("parent_version_id is required for CO modified_for_case proposals")


def _client_proposal_mode(client_id: str) -> str:
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "select bom_proposal_mode from hub.clients where client_id = %s",
                (client_id,),
            )
            row = cur.fetchone()
    return (row[0] if row else "auto") or "auto"


def _notify_pending_review(*, client_id: str, product_code: str,
                           proposal_id: str, decision_reason: str | None) -> None:
    """Fan-out a 'pending review' notification to every staff member with
    edit access to the client. Non-critical — swallow errors."""
    try:
        from app import notifications as _notifs
        user_ids = _notifs.staff_with_edit_access_to_client(client_id)
        body = f"Reason: {decision_reason}." if decision_reason else "Đang chờ duyệt thủ công."
        _notifs.notify_many(
            user_ids=user_ids, kind="bom_proposal_pending",
            title=f"BOM proposal cho {product_code} cần duyệt",
            body=body,
            link_url=f"/clients/{client_id}/proposals/{proposal_id}",
            client_id=client_id, related_kind="bom_change_requests",
            related_id=proposal_id,
        )
    except Exception:
        pass


def submit_proposal(*, client_id: str, product_code: str, actor: str, intent: str,
                    parent_version_id: str | None, context: dict,
                    rows: list[dict]) -> dict:
    """Submit a BOM proposal. Branches on the client's bom_proposal_mode:

      auto    — auto-rule decides synchronously (existing behaviour).
      manual  — every proposal lands in 'pending'; a reviewer must act.
      hybrid  — auto-rule approves clean proposals; rule rejections fall
                through to 'pending' (with failed_conditions) for override.

    Returns {proposal_id, status, version_id?, decision_reason,
    failed_conditions, idempotent?}.
    """
    validate_proposal_contract(
        actor=actor, intent=intent, parent_version_id=parent_version_id,
    )
    proposal_id = "prop_" + secrets.token_urlsafe(12)
    nh = normalized_hash(rows)
    mode = _client_proposal_mode(client_id)

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
                  and status <> 'withdrawn'
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

    if mode == "manual":
        decision = {"approved": False, "reason": None, "failed": []}
        landed_status = "pending"
        decided_by = None
        decision_reason = None
    else:
        decision = _auto_evaluate(
            client_id=client_id, product_code=product_code,
            parent_version_id=parent_version_id, context=context, rows=rows,
        )
        if decision["approved"]:
            landed_status = "approved"
            decided_by = "auto-rule"
            decision_reason = decision["reason"]
        elif mode == "hybrid":
            landed_status = "pending"
            decided_by = None
            decision_reason = None
        else:  # auto + auto-rule rejected
            landed_status = "rejected"
            decided_by = "auto-rule"
            decision_reason = decision["reason"]

    decided_at_clause = "now()" if landed_status != "pending" else "null"
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"""
                insert into hub.bom_change_requests
                  (proposal_id, client_id, product_code, actor, intent,
                   parent_version_id, context, rows_payload, normalized_hash,
                   status, decided_at, decided_by, decision_reason, failed_conditions)
                values (%s, %s, %s, %s, %s, %s, %s::jsonb, %s::jsonb, %s,
                        %s, {decided_at_clause}, %s, %s, %s::jsonb)
                """,
                (proposal_id, client_id, product_code, actor, intent,
                 parent_version_id, json.dumps(context), json.dumps(rows), nh,
                 landed_status, decided_by, decision_reason,
                 json.dumps(decision.get("failed", []))),
            )

    if landed_status == "approved":
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

    if landed_status == "pending":
        _notify_pending_review(
            client_id=client_id, product_code=product_code,
            proposal_id=proposal_id,
            decision_reason=(
                f"auto-rule rejected: {decision['reason']}"
                if mode == "hybrid" else None
            ),
        )
        return {
            "proposal_id": proposal_id, "status": "pending",
            "version_id": None, "decision_reason": None,
            "failed_conditions": decision.get("failed", []),
        }

    # auto mode + auto-rule rejected: legacy notification path so reviewers
    # know there's a rejection worth eyeballing.
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
        pass

    return {
        "proposal_id": proposal_id, "status": "rejected",
        "version_id": None, "decision_reason": decision["reason"],
        "failed_conditions": decision.get("failed", []),
    }


def get_proposal(proposal_id: str) -> dict | None:
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                select proposal_id, client_id, product_code, actor, intent,
                       parent_version_id, context, rows_payload, status,
                       decided_at, decided_by, decision_reason,
                       failed_conditions, materialized_version_id,
                       normalized_hash, created_at
                from hub.bom_change_requests where proposal_id = %s
                """,
                (proposal_id,),
            )
            row = cur.fetchone()
            if not row:
                return None
            cols = [d[0] for d in cur.description]
            return dict(zip(cols, row))


def approve_proposal(*, proposal_id: str, decided_by: str,
                     reason: str | None = None) -> dict:
    """Materialize a pending proposal as a new BOM version."""
    proposal = get_proposal(proposal_id)
    if not proposal:
        raise ProposalNotFound(proposal_id)
    if proposal["status"] != "pending":
        raise ProposalNotPending(proposal["status"])
    rows = proposal["rows_payload"] or []
    context = dict(proposal["context"] or {})
    version_id = create_version(
        client_id=proposal["client_id"], product_code=proposal["product_code"],
        rows=rows, actor=proposal["actor"], intent=proposal["intent"],
        parent_version_id=proposal["parent_version_id"],
        context={**context, "proposal_id": proposal_id},
        source_upload_id=None,
    )
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                update hub.bom_change_requests
                set status='approved', decided_at=now(), decided_by=%s,
                    decision_reason=%s, materialized_version_id=%s
                where proposal_id=%s
                """,
                (decided_by, reason or "manual approve", version_id, proposal_id),
            )
    try:
        from app import notifications as _notifs
        user_ids = _notifs.staff_with_edit_access_to_client(proposal["client_id"])
        _notifs.notify_many(
            user_ids=user_ids, kind="bom_proposal_approved",
            title=f"BOM proposal cho {proposal['product_code']} đã duyệt",
            body=f"Approved by {decided_by}.",
            link_url=f"/clients/{proposal['client_id']}/proposals/{proposal_id}",
            client_id=proposal["client_id"],
            related_kind="bom_change_requests", related_id=proposal_id,
        )
    except Exception:
        pass
    return {"proposal_id": proposal_id, "status": "approved", "version_id": version_id}


def reject_proposal(*, proposal_id: str, decided_by: str, reason: str) -> dict:
    """Mark a pending proposal as rejected with a reviewer-supplied reason."""
    proposal = get_proposal(proposal_id)
    if not proposal:
        raise ProposalNotFound(proposal_id)
    if proposal["status"] != "pending":
        raise ProposalNotPending(proposal["status"])
    reason_clean = (reason or "").strip() or "rejected"
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                update hub.bom_change_requests
                set status='rejected', decided_at=now(), decided_by=%s,
                    decision_reason=%s
                where proposal_id=%s
                """,
                (decided_by, reason_clean, proposal_id),
            )
    return {"proposal_id": proposal_id, "status": "rejected"}


def withdraw_proposal(*, proposal_id: str, by: str) -> dict:
    """Submitter or reviewer rescinds a still-pending proposal."""
    proposal = get_proposal(proposal_id)
    if not proposal:
        raise ProposalNotFound(proposal_id)
    if proposal["status"] != "pending":
        raise ProposalNotPending(proposal["status"])
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                update hub.bom_change_requests
                set status='withdrawn', decided_at=now(), decided_by=%s,
                    decision_reason='withdrawn'
                where proposal_id=%s
                """,
                (by, proposal_id),
            )
    return {"proposal_id": proposal_id, "status": "withdrawn"}


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


# ─── Flatten lookups (used by the upload route to build FlattenContext) ──

def make_bcct_import_lookup(client_id: str):
    """Return a callable `(material_code) -> bool` answering: has this code
    appeared on any IMPORT BCCT declaration for this client? Preloads the
    full set so per-row lookups during flatten are O(1).

    Spec §5: BCCT import evidence is scoped to the same client and to import
    declarations only. Export evidence does not qualify."""
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                select distinct customs_code from hub.bcct_rows
                where client_id = %s and direction = 'import'
                  and customs_code is not null and customs_code <> ''
                """,
                (client_id,),
            )
            seen = {r[0] for r in cur.fetchall()}
    return lambda code: code in seen


def make_catalog_lookup(client_id: str):
    """Return a callable `(material_code) -> CatalogEntry | None` from
    hub.materials. Preloaded so per-row lookups are O(1)."""
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                select customs_code, category, status, unit
                from hub.materials where client_id = %s
                """,
                (client_id,),
            )
            entries = {r[0]: CatalogEntry(
                material_code=r[0], category=r[1], status=r[2], unit=r[3],
            ) for r in cur.fetchall()}
    return lambda code: entries.get(code)


def make_current_db_btp_lookup(client_id: str):
    """Return a callable `(material_code, bom_code, bom_variant_id) ->
    list[ParsedRow] | None` returning the rows of the most-recent published
    flattened/manual_flat version for that (product_code) at the requested
    variant. Used by the flattener as the fallback when same-upload doesn't
    have a child BOM."""
    # Preload: latest published flattened or not_applicable version per
    # (product_code, bom_variant_id). Excludes 'modified_for_case' (per the
    # existing /latest semantics).
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                with latest as (
                    select distinct on (product_code, coalesce(bom_variant_id, 'default'))
                        product_code, bom_variant_id, version_id, bom_code,
                        version_no, published_at
                    from hub.bom_versions
                    where client_id = %s
                      and tombstoned_at is null
                      and status = 'published'
                      and intent in ('asserted_technical','staff_edit','derived')
                      and flatten_status in ('flattened','not_applicable')
                    order by product_code, coalesce(bom_variant_id, 'default'),
                             published_at desc nulls last, version_no desc
                )
                select l.product_code, l.bom_variant_id, l.version_id,
                       r.material_code, r.bom_code, r.bom_variant_id,
                       r.qty_per_unit, r.uom
                from latest l
                left join hub.bom_version_rows r on r.version_id = l.version_id
                """,
                (client_id,),
            )
            rows_by_key: dict[tuple, list[ParsedRow]] = {}
            for product_code, variant, _vid, mat, bcd, bvid, qty, uom in cur.fetchall():
                k = (product_code, variant or "default")
                rows_by_key.setdefault(k, [])
                if mat:  # left join may have no rows
                    rows_by_key[k].append({
                        "material_code": mat,
                        "bom_code": bcd or "",
                        "bom_variant_id": bvid or "default",
                        "qty_per_unit": float(qty or 0),
                        "uom": uom,
                    })

    def lookup(material_code: str, bom_code: str, bom_variant_id: str):
        # Strict variant equality (per /rev finding C3): only fall back
        # to "any variant for this code" when caller passes "" (i.e.
        # explicitly didn't specify a variant). Caller passing 'default'
        # MUST match a 'default' variant exactly.
        if bom_variant_id == "":
            for k, r in rows_by_key.items():
                if k[0] == material_code:
                    return r
            return None
        key = (material_code, bom_variant_id)
        return rows_by_key.get(key)

    return lookup


# ─── Flatten materialization ──────────────────────────────────────────────

def create_flattened_version_set(
    *, client_id: str, source_upload_id: str | None,
    result: FlattenResult,
    decision_id_map: dict[int, str] | None = None,
    actor: str = "agency_staff",
    intent: str = "asserted_technical",
    source_channel: str = "agency_upload",
    publish_filter=None,    # callable(FlattenedVersion) -> bool
) -> dict[str, str]:
    """Materialize a FlattenResult ATOMICALLY in a single transaction.

    Steps inside the transaction:
      1. Insert every FlattenedVersion (pass 1) plus its rows + audit row.
      2. Insert bom_unresolved_nodes per non_flattened version.
      3. Link confirmed decisions to materialized version_ids.
      4. Backfill lineage.btp_versions_used[*].version_id (pass 2).

    Per /rev finding C1: all writes go through ONE psycopg connection
    + cursor so on any failure the entire materialization rolls back.
    Pending row stays (managed by caller); staff can re-confirm safely.

    Returns mapping `{flattened_version.key.as_tuple()_str: version_id}`.
    `publish_filter` lets the upload route exclude variants that staff
    didn't confirm (e.g. dual-source where they chose only one strategy).
    """
    if publish_filter is None:
        publish_filter = lambda v: True

    decision_id_map = decision_id_map or {}
    decisions_by_target: dict[tuple, list[str]] = {}
    for i, d in enumerate(result.decisions):
        if i not in decision_id_map:
            continue
        if d.target_key:
            sig = (d.target_key.as_tuple(), d.target_strategy)
            decisions_by_target.setdefault(sig, []).append(decision_id_map[i])

    materialized: dict[str, str] = {}
    materialized_by_product: dict[str, str] = {}

    with connect() as conn:
        with conn.cursor() as cur:
            # Pass 1: insert every version, rows, audit, unresolved
            # nodes, and link decisions — all inside one cursor.
            for v in result.versions:
                if not publish_filter(v):
                    continue
                version_rows = [{
                    "material_code": r.material_code,
                    "qty_per_unit": float(r.qty) if isinstance(r.qty, Decimal) else r.qty,
                    "uom": r.uom,
                    "bom_code": v.key.bom_code or None,
                    "bom_variant_id": v.key.bom_variant_id,
                    "node_path": r.node_path,
                    "classification_evidence": r.classification_evidence,
                    "classification_evidence_detail": r.classification_evidence_detail,
                    "conversion_evidence": r.conversion_evidence,
                    "original_qty": str(r.original_qty) if r.original_qty is not None else None,
                    "original_uom": r.original_uom,
                } for r in v.rows]
                version_id = create_version(
                    client_id=client_id,
                    product_code=v.key.product_code,
                    rows=version_rows,
                    actor=actor,
                    intent=intent,
                    parent_version_id=None,
                    context={"channel": source_channel,
                             "profile": "technical_flatten",
                             "flatten_method": FLATTEN_METHOD,
                             "flatten_method_version": FLATTEN_METHOD_VERSION},
                    source_upload_id=source_upload_id,
                    source_bom_kind=v.source_bom_kind,
                    flatten_status=v.flatten_status,
                    flatten_strategy=v.flatten_strategy,
                    source_channel=source_channel,
                    bom_code=v.key.bom_code or None,
                    bom_variant_id=v.key.bom_variant_id,
                    lineage=dict(v.lineage or {}),
                    flatten_method=FLATTEN_METHOD,
                    flatten_method_version=FLATTEN_METHOD_VERSION,
                    cursor=cur,
                )
                if not version_id:
                    continue
                key_str = f"{v.key.product_code}|{v.key.bom_code or ''}|{v.key.bom_variant_id}|{v.flatten_strategy}"
                materialized[key_str] = version_id
                materialized_by_product.setdefault(v.key.product_code, version_id)
                for u in (v.unresolved or []):
                    cur.execute(
                        """
                        insert into hub.bom_unresolved_nodes
                          (version_id, node_path, material_code, reason, evidence)
                        values (%s, %s, %s, %s, %s::jsonb)
                        on conflict (version_id, node_path) do nothing
                        """,
                        (version_id, u.node_path, u.material_code,
                         u.reason, json.dumps(u.evidence, default=str)),
                    )
                sig_strategy = (v.key.as_tuple(), v.flatten_strategy)
                sig_unbound = (v.key.as_tuple(), None)
                for sig in (sig_strategy, sig_unbound):
                    for did in decisions_by_target.get(sig, []):
                        cur.execute(
                            """
                            update hub.bom_flatten_decisions
                            set materialized_version_id = %s,
                                pending_id = null
                            where decision_id = %s
                            """,
                            (version_id, did),
                        )

            # Pass 2: backfill lineage.btp_versions_used[*].version_id.
            for v in result.versions:
                used = (v.lineage or {}).get("btp_versions_used") or []
                if not used:
                    continue
                key_str = f"{v.key.product_code}|{v.key.bom_code or ''}|{v.key.bom_variant_id}|{v.flatten_strategy}"
                version_id = materialized.get(key_str)
                if not version_id:
                    continue
                enriched = []
                for entry in used:
                    mat = entry.get("material_code")
                    vid = materialized_by_product.get(mat)
                    if vid:
                        enriched.append({**entry, "version_id": vid})
                    else:
                        enriched.append(entry)
                new_lineage = dict(v.lineage or {})
                new_lineage["btp_versions_used"] = enriched
                cur.execute(
                    "update hub.bom_versions set lineage = %s::jsonb where version_id = %s",
                    (json.dumps(new_lineage, ensure_ascii=False, default=str), version_id),
                )
        # `with conn` commits on success; rolls back on any exception.

    return materialized


def latest_flattened_versions(*, client_id: str, product_code: str) -> list[dict]:
    """Return the published, non-tombstoned flattened/not_applicable versions
    for a product. List length > 1 when dual-source variants are published —
    callers (api/_latest) decide whether to 200 (single), 409 (multiple), etc.

    Per spec §3A: 'latest' must be a query constrained by status and strategy.
    Excludes 'modified_for_case' to mirror the existing /latest semantics.
    """
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                with ranked as (
                    select version_id, version_no, flatten_strategy, source_bom_kind,
                           flatten_status, display_label, bom_variant_id, bom_code,
                           published_at,
                           row_number() over (
                               partition by coalesce(bom_variant_id,'default'),
                                            flatten_strategy
                               order by published_at desc nulls last, version_no desc
                           ) as rn
                    from hub.bom_versions
                    where client_id = %s and product_code = %s
                      and tombstoned_at is null
                      and status = 'published'
                      and intent in ('asserted_technical','staff_edit','derived')
                      and flatten_status in ('flattened','not_applicable')
                )
                select version_id, version_no, flatten_strategy, source_bom_kind,
                       flatten_status, display_label, bom_variant_id, bom_code
                from ranked where rn = 1
                order by published_at desc nulls last, version_no desc
                """,
                (client_id, product_code),
            )
            cols = [d[0] for d in cur.description]
            return [dict(zip(cols, r)) for r in cur.fetchall()]


def get_unresolved_for_version(version_id: str) -> list[dict]:
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                select node_path, material_code, reason, evidence
                from hub.bom_unresolved_nodes where version_id = %s
                order by node_path
                """,
                (version_id,),
            )
            cols = [d[0] for d in cur.description]
            return [dict(zip(cols, r)) for r in cur.fetchall()]


def get_decisions_for_version(version_id: str) -> list[dict]:
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                select decision_id, decision_type, chosen_action, alternatives,
                       evidence, status, staff_confirmation_required,
                       confirmed_by, confirmed_at
                from hub.bom_flatten_decisions
                where materialized_version_id = %s
                order by created_at
                """,
                (version_id,),
            )
            cols = [d[0] for d in cur.description]
            return [dict(zip(cols, r)) for r in cur.fetchall()]
