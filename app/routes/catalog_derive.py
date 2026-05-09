"""Catalog-derive tool — pull codes from BCCT/BOM into the materials catalog.

Brief: `.ai/features/2026-05-08-catalog-multi-source/brief.md` (rev 4).

Workflow:
  1. Staff defines a `catalog_derive_configs` rule (regex + non-regex
     filters + default category).
  2. Preview endpoint runs the regex over BCCT goods_name (or BOM edges),
     anti-joins `materials`, returns codes-not-yet-in-catalog with
     observation stats.
  3. Bulk-apply inserts the previewed codes into `materials` with
     `source='bcct_observed'` (or `bom_observed`) + `status` from rule.

Endpoints:
  GET  /clients/{client_id}/catalog/derive
       → page (UI sketch in brief).
  POST /clients/{client_id}/catalog/derive/configs
       → create new config.
  PATCH /clients/{client_id}/catalog/derive/configs/{config_id}
       → update existing config.
  POST /clients/{client_id}/catalog/derive/configs/{config_id}/preview
       → return matching codes (paginated, anti-joined).
  POST /clients/{client_id}/catalog/derive/configs/{config_id}/apply
       → bulk-insert previewed codes into materials.
"""
from __future__ import annotations

import re
from datetime import date

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from app import auth
from app.database import connect
from app.parsers.client_parser_rules import (
    InvalidPatternError, compile_pattern,
)
from app.routes.clients import get_client


router = APIRouter()


# Pre-built templates for catalog-derive rules. Staff pick from these instead
# of writing regex by hand. Each entry is (key, label, description, pattern,
# source_table, source_field, default_category, sample_input).
TEMPLATES: list[dict] = [
    {
        "key": "agency_nvl_paren",
        "label": "Mã NVL agency trong ngoặc — (NNN.xxx)",
        "description": "Pattern Growatt-style: code 3-số.suffix trong parens cuối goods_name. "
                       "Ví dụ: 'IC#&Mạch IC... (007.0050100)' → extract 007.0050100.",
        "pattern": r"\((\d{3}\.[\w\-]+)\)",
        "source_table": "bcct_rows",
        "source_field": "goods_name",
        "default_category": "nvl",
        "sample_input": "IC#&Mạch tích hợp IC, dùng truyền tín hiệu (007.0050100)",
    },
    {
        "key": "agency_tp_paren",
        "label": "Mã TP agency trong ngoặc — (AANN.xxx)",
        "description": "Pattern Growatt-style: 2+ chữ cái + 2 số.suffix. "
                       "Ví dụ: 'BIENTAN.20#&Inverter (PV01.0117500)' → extract PV01.0117500.",
        "pattern": r"\(([A-Z]{2,}\d{2}\.[\w\-]+)\)",
        "source_table": "bcct_rows",
        "source_field": "goods_name",
        "default_category": "tp",
        "sample_input": "BIENTAN.20#&Bộ biến tần điện mặt trời (PV01.0117500)",
    },
    {
        "key": "agency_pcba_paren",
        "label": "Mã PCBA agency trong ngoặc — (Annn.xxx)",
        "description": "Pattern Growatt-style: 1 chữ + 3 số.suffix. "
                       "Ví dụ: 'PCB#&Bản mạch (B700.0242002)' → extract B700.0242002.",
        "pattern": r"\(([A-Z]\d{3}\.[\w\-]+)\)",
        "source_table": "bcct_rows",
        "source_field": "goods_name",
        "default_category": "btp_nm",
        "sample_input": "PCB#&Bản mạch điện tử (B700.0242002)",
    },
    {
        "key": "agency_alpha_suffix_paren",
        "label": "Mã alpha-suffix agency trong ngoặc — (NNL.xxx)",
        "description": "Pattern Growatt-style: 2 số + 1 chữ.suffix. "
                       "Ví dụ: '(00G.0101600)' → extract 00G.0101600.",
        "pattern": r"\((\d{2}[A-Z]\.[\w\-]+)\)",
        "source_table": "bcct_rows",
        "source_field": "goods_name",
        "default_category": "nvl",
        "sample_input": "Sản phẩm test (00G.0101600)",
    },
    {
        "key": "bom_node_codes",
        "label": "Mã BTP/NVL từ BOM (parent_code/child_code)",
        "description": "Pull mã trong BOM edges chưa có trong catalog. Pattern bắt-tất-cả "
                       "default — staff điều chỉnh theo nhu cầu.",
        "pattern": r"^(.+)$",
        "source_table": "bom_edges",
        "source_field": "parent_code",
        "default_category": "btp_sx",
        "sample_input": "PV01.0117500",
    },
    {
        "key": "custom",
        "label": "(Custom — tự viết regex)",
        "description": "Staff viết regex riêng. Phải có ≥1 capture group `(...)`. "
                       "Test trước khi save bằng panel ở bước 2.",
        "pattern": "",
        "source_table": "bcct_rows",
        "source_field": "goods_name",
        "default_category": "",
        "sample_input": "",
    },
]


# Plain-language label mapping (used in template).
LABELS = {
    "source_table.bcct_rows": "Tờ khai BCCT",
    "source_table.bom_edges": "Định mức BOM (cây cha-con)",
    "source_field.goods_name": "Cột Tên hàng",
    "source_field.parent_code": "Mã cha (BOM)",
    "source_field.child_code": "Mã con (BOM)",
    "source_field.customs_code": "Cột Mã trên tờ khai",
    "default_status.under_review": "Chờ duyệt (staff promote sau)",
    "default_status.active": "Active (auto-promote)",
}


# ── Page handler ─────────────────────────────────────────────────────────

@router.get(
    "/clients/{client_id}/catalog/derive",
    response_class=HTMLResponse,
)
async def derive_page(request: Request, client_id: str):
    user = auth.require_user(request)
    auth.require_can_view_client(user, client_id)
    client = get_client(client_id)
    if not client:
        raise HTTPException(404, "Client not found")
    configs = _list_configs(client_id)
    return request.app.state.templates.TemplateResponse(
        request, "clients/catalog_derive.html",
        {"client": client, "configs": configs,
         "active_root": "clients", "active_tab": "catalog"},
    )


# ── Config CRUD ──────────────────────────────────────────────────────────

@router.post("/clients/{client_id}/catalog/derive/configs")
async def create_config(request: Request, client_id: str,
                        name: str = Form(...),
                        pattern: str = Form(...),
                        source_table: str = Form("bcct_rows"),
                        source_field: str = Form("goods_name"),
                        match_group: int = Form(1),
                        direction_filter: str = Form(""),
                        min_observed_count: int = Form(1),
                        date_from: str = Form(""),
                        date_to: str = Form(""),
                        default_category: str = Form(""),
                        default_status: str = Form("under_review")):
    user = auth.require_user(request)
    auth.require_can_edit_client(user, client_id)
    _validate_inputs(pattern, source_table, default_status, default_category)
    df = _parse_directions(direction_filter)
    df_date = _parse_date(date_from)
    dt_date = _parse_date(date_to)
    cat = default_category or None
    with connect(user_id=user.user_id) as conn, conn.cursor() as cur:
        cur.execute(
            """
            insert into hub.catalog_derive_configs
              (client_id, name, source_table, pattern, source_field,
               match_group, direction_filter, min_observed_count,
               date_from, date_to, default_status, default_category,
               created_by, updated_by)
            values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            returning config_id
            """,
            (client_id, name.strip(), source_table, pattern, source_field,
             match_group, df, min_observed_count, df_date, dt_date,
             default_status, cat, user.email, user.email),
        )
    return RedirectResponse(
        url=f"/clients/{client_id}/catalog/derive", status_code=303,
    )


@router.post("/clients/{client_id}/catalog/derive/configs/{config_id}/disable")
async def disable_config(request: Request, client_id: str, config_id: int):
    user = auth.require_user(request)
    auth.require_can_edit_client(user, client_id)
    with connect(user_id=user.user_id) as conn, conn.cursor() as cur:
        cur.execute(
            "update hub.catalog_derive_configs set enabled = false, "
            "updated_at = now(), updated_by = %s "
            "where client_id = %s and config_id = %s",
            (user.email, client_id, config_id),
        )
    return RedirectResponse(
        url=f"/clients/{client_id}/catalog/derive", status_code=303,
    )


# ── Preview + apply ──────────────────────────────────────────────────────

@router.post("/clients/{client_id}/catalog/derive/configs/{config_id}/preview")
async def preview_config(request: Request, client_id: str, config_id: int,
                         limit: int = Form(50)):
    user = auth.require_user(request)
    auth.require_can_view_client(user, client_id)
    config = _get_config(client_id, config_id)
    if not config:
        raise HTTPException(404, "config not found")
    rows = _run_preview(client_id, config, limit=min(max(limit, 1), 500))
    return {"ok": True, "rows": rows, "row_count": len(rows)}


@router.post("/clients/{client_id}/catalog/derive/configs/{config_id}/apply")
async def apply_config(request: Request, client_id: str, config_id: int):
    user = auth.require_user(request)
    auth.require_can_edit_client(user, client_id)
    config = _get_config(client_id, config_id)
    if not config:
        raise HTTPException(404, "config not found")
    inserted = _run_apply(client_id, config, actor=user.email)
    return RedirectResponse(
        url=f"/clients/{client_id}/catalog?status={config['default_status']}"
            f"&derived={inserted}",
        status_code=303,
    )


# ── Internals ────────────────────────────────────────────────────────────

_VALID_SOURCE_TABLES = {"bcct_rows", "bom_edges"}
_VALID_STATUSES = {"under_review", "active"}
_VALID_CATEGORIES = {"nvl", "tp", "btp_sx", "btp_nm", "ccdc"}


def _validate_inputs(pattern: str, source_table: str,
                     default_status: str, default_category: str) -> None:
    if source_table not in _VALID_SOURCE_TABLES:
        raise HTTPException(400, f"invalid source_table: {source_table!r}")
    if default_status not in _VALID_STATUSES:
        raise HTTPException(400, f"invalid default_status: {default_status!r}")
    if default_category and default_category not in _VALID_CATEGORIES:
        raise HTTPException(400, f"invalid default_category: {default_category!r}")
    try:
        compile_pattern(pattern)  # ReDoS safety + length check
    except InvalidPatternError as e:
        raise HTTPException(400, f"invalid regex pattern: {e}") from e
    # Sanity: pattern must contain at least one capture group when
    # match_group >= 1 (caller will extract group 1 by default).
    if "(" not in pattern:
        raise HTTPException(400, "pattern must contain at least one capture group")


def _parse_directions(s: str) -> list[str] | None:
    if not s.strip():
        return None
    parts = [p.strip() for p in s.split(",") if p.strip()]
    valid = {"import", "export"}
    bad = [p for p in parts if p not in valid]
    if bad:
        raise HTTPException(400, f"invalid direction(s): {bad!r}")
    return parts or None


def _parse_date(s: str) -> date | None:
    if not s or not s.strip():
        return None
    try:
        return date.fromisoformat(s.strip())
    except ValueError as e:
        raise HTTPException(400, f"invalid date: {s!r}") from e


def _list_configs(client_id: str) -> list[dict]:
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            """
            select config_id, name, source_table, pattern, source_field,
                   match_group, direction_filter, min_observed_count,
                   date_from, date_to, default_status, default_category,
                   enabled, created_at, created_by, updated_at, updated_by
            from hub.catalog_derive_configs
            where client_id = %s
            order by created_at desc
            """,
            (client_id,),
        )
        cols = [d[0] for d in cur.description]
        return [dict(zip(cols, r)) for r in cur.fetchall()]


def _get_config(client_id: str, config_id: int) -> dict | None:
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "select config_id, name, source_table, pattern, source_field, "
            "match_group, direction_filter, min_observed_count, "
            "date_from, date_to, default_status, default_category, enabled "
            "from hub.catalog_derive_configs "
            "where client_id = %s and config_id = %s",
            (client_id, config_id),
        )
        row = cur.fetchone()
        if not row:
            return None
        cols = [d[0] for d in cur.description]
        return dict(zip(cols, row))


def _run_preview(client_id: str, config: dict, *, limit: int) -> list[dict]:
    """Run the regex over the source table, aggregate observation stats,
    anti-join `materials`, return the top `limit` codes by observed_count
    desc.

    Pattern compile happens at preview time too (in case rule was created
    pre-validation or pattern was edited externally).
    """
    compiled = compile_pattern(config["pattern"])
    if config["source_table"] == "bcct_rows":
        return _preview_bcct(client_id, config, compiled, limit)
    elif config["source_table"] == "bom_edges":
        return _preview_bom(client_id, config, compiled, limit)
    raise HTTPException(500, f"unhandled source_table: {config['source_table']!r}")


def _preview_bcct(client_id: str, config: dict, compiled, limit: int) -> list[dict]:
    where, params = _bcct_where(client_id, config)
    sql = f"""
        select transaction_key, line_no, registration_date, declaration_no,
               direction, declaration_type, goods_name
        from hub.bcct_rows b
        where client_id = %s
          {where}
        order by registration_date desc nulls last
        limit 50000
    """
    extracted: dict[str, dict] = {}
    with connect() as conn, conn.cursor() as cur:
        cur.execute(sql, [client_id, *params])
        for tk, ln, regdate, decl, direction, decl_type, goods_name in cur.fetchall():
            text = goods_name or ""
            for m in compiled.finditer(text):
                try:
                    code = m.group(config["match_group"]).strip()
                except (IndexError, AttributeError):
                    continue
                if not code:
                    continue
                e = extracted.setdefault(code, {
                    "code": code,
                    "first_seen": regdate, "last_seen": regdate,
                    "decl_count": set(), "directions": set(),
                    "sample_goods_name": goods_name,
                })
                e["decl_count"].add(decl)
                if direction:
                    e["directions"].add(direction)
                if regdate:
                    if not e["first_seen"] or regdate < e["first_seen"]:
                        e["first_seen"] = regdate
                    if not e["last_seen"] or regdate > e["last_seen"]:
                        e["last_seen"] = regdate
    # Anti-join materials
    if not extracted:
        return []
    codes = list(extracted.keys())
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "select material_code from hub.materials "
            "where client_id = %s and material_code = any(%s)",
            (client_id, codes),
        )
        existing = {r[0] for r in cur.fetchall()}
    out = []
    for code, e in extracted.items():
        if code in existing:
            continue
        cnt = len(e["decl_count"])
        if cnt < config["min_observed_count"]:
            continue
        out.append({
            "code": code,
            "observed_count": cnt,
            "first_seen": (
                e["first_seen"].strftime("%Y-%m-%d") if e["first_seen"] else None
            ),
            "last_seen": (
                e["last_seen"].strftime("%Y-%m-%d") if e["last_seen"] else None
            ),
            "directions": sorted(e["directions"]),
            "sample_goods_name": (e["sample_goods_name"] or "")[:200],
        })
    out.sort(key=lambda r: -r["observed_count"])
    return out[:limit]


def _preview_bom(client_id: str, config: dict, compiled, limit: int) -> list[dict]:
    """For bom_edges source: extract codes from parent_code/child_code via
    regex (or surface raw codes if pattern is `^(.+)$`). Anti-join materials."""
    extracted: dict[str, dict] = {}
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            """
            select e.parent_code, e.child_code, a.created_at
            from hub.bom_edges e
            join hub.bom_artifacts a on a.artifact_id = e.artifact_id
            where a.client_id = %s and a.tombstoned_at is null
            """,
            (client_id,),
        )
        for parent, child, created_at in cur.fetchall():
            for src in (parent, child):
                if not src:
                    continue
                m = compiled.search(src)
                if not m:
                    continue
                try:
                    code = m.group(config["match_group"]).strip()
                except (IndexError, AttributeError):
                    continue
                if not code:
                    continue
                e = extracted.setdefault(code, {
                    "code": code, "decl_count": 0,
                    "first_seen": None, "last_seen": None,
                    "directions": set(),
                })
                e["decl_count"] += 1
    if not extracted:
        return []
    codes = list(extracted.keys())
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "select material_code from hub.materials "
            "where client_id = %s and material_code = any(%s)",
            (client_id, codes),
        )
        existing = {r[0] for r in cur.fetchall()}
    out = []
    for code, e in extracted.items():
        if code in existing:
            continue
        if e["decl_count"] < config["min_observed_count"]:
            continue
        out.append({
            "code": code,
            "observed_count": e["decl_count"],
            "first_seen": None, "last_seen": None,
            "directions": [], "sample_goods_name": "",
        })
    out.sort(key=lambda r: -r["observed_count"])
    return out[:limit]


def _bcct_where(client_id: str, config: dict) -> tuple[str, list]:
    clauses = []
    params: list = []
    if config["direction_filter"]:
        clauses.append("and direction = any(%s)")
        params.append(list(config["direction_filter"]))
    if config["date_from"]:
        clauses.append("and registration_date >= %s")
        params.append(config["date_from"])
    if config["date_to"]:
        clauses.append("and registration_date <= %s")
        params.append(config["date_to"])
    return " ".join(clauses), params


def _run_apply(client_id: str, config: dict, *, actor: str) -> int:
    """Insert previewed codes into materials. Uses source='bcct_observed' or
    'bom_observed' based on config. Idempotent: on conflict (existing
    material_code) does nothing."""
    rows = _run_preview(client_id, config, limit=10_000)
    if not rows:
        return 0
    source = ("bcct_observed" if config["source_table"] == "bcct_rows"
              else "bom_observed")
    cat = config["default_category"] or "nvl"
    with connect(user_id=actor) as conn, conn.cursor() as cur:
        for r in rows:
            cur.execute(
                """
                insert into hub.materials
                  (client_id, material_code, name, category, status, source)
                values (%s, %s, %s, %s, %s, %s)
                on conflict (client_id, material_code) do nothing
                """,
                (client_id, r["code"],
                 (r["sample_goods_name"] or r["code"])[:200],
                 cat, config["default_status"], source),
            )
    return len(rows)
