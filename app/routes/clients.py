"""Client (DNCX) management + workspace overview."""
from __future__ import annotations

import secrets

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from app import auth
from app.database import connect

router = APIRouter()

CODE_RESOLUTION_MODES = ["identity", "simple_mapping", "batch_aggregate_resolution"]
BOM_PROPOSAL_MODES = ["auto", "manual", "hybrid"]
BOM_APPROVER_TIERS = ["edit", "manager", "admin"]


def list_clients() -> list[dict]:
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                select c.client_id, c.name, c.tax_code, c.code_resolution_mode,
                       c.bom_proposal_mode, c.bom_proposal_qty_tolerance_pct,
                       c.status, c.notes, c.created_at,
                       (select count(*) from hub.materials m where m.client_id = c.client_id) as n_materials,
                       (select count(*) from hub.code_mappings cm where cm.client_id = c.client_id) as n_mappings,
                       (select count(*) from hub.bcct_rows b where b.client_id = c.client_id) as n_bcct,
                       (select count(*) from hub.bom_artifacts bv where bv.client_id = c.client_id and bv.tombstoned_at is null) as n_bom
                from hub.clients c
                order by c.created_at desc
                """
            )
            cols = [d[0] for d in cur.description]
            return [dict(zip(cols, r)) for r in cur.fetchall()]


def get_client(client_id: str) -> dict | None:
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                select client_id, name, tax_code, code_resolution_mode, bom_proposal_mode,
                       bom_proposal_qty_tolerance_pct, bom_approver_tier,
                       status, notes, created_at, updated_at
                from hub.clients where client_id = %s
                """,
                (client_id,),
            )
            row = cur.fetchone()
            if not row:
                return None
            cols = [d[0] for d in cur.description]
            return dict(zip(cols, row))


def stats_for_client(client_id: str) -> dict:
    """5 nav-badge counts in one round-trip. Each count is its own
    scalar subquery so the planner picks the best per-table index
    (each table has a `(client_id, ...)` index)."""
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                select
                  (select count(*) from hub.materials where client_id = %s),
                  (select count(*) from hub.code_mappings where client_id = %s),
                  (select count(*) from hub.bcct_rows where client_id = %s),
                  (select count(*) from hub.bom_artifacts
                     where client_id = %s and tombstoned_at is null),
                  (select count(*) from hub.bom_change_requests where client_id = %s)
                """,
                (client_id, client_id, client_id, client_id, client_id),
            )
            n_materials, n_mappings, n_bcct, n_bom, n_proposals = cur.fetchone()
    return {"materials": n_materials, "mappings": n_mappings,
            "bcct": n_bcct, "bom": n_bom, "proposals": n_proposals}


def upsert_client(*, client_id: str, name: str, tax_code: str | None,
                  code_resolution_mode: str, bom_proposal_mode: str,
                  bom_proposal_qty_tolerance_pct: float,
                  bom_approver_tier: str, status: str,
                  notes: str | None) -> None:
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                insert into hub.clients
                  (client_id, name, tax_code, code_resolution_mode, bom_proposal_mode,
                   bom_proposal_qty_tolerance_pct, bom_approver_tier, status, notes)
                values (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                on conflict (client_id) do update set
                  name = excluded.name,
                  tax_code = excluded.tax_code,
                  code_resolution_mode = excluded.code_resolution_mode,
                  bom_proposal_mode = excluded.bom_proposal_mode,
                  bom_proposal_qty_tolerance_pct = excluded.bom_proposal_qty_tolerance_pct,
                  bom_approver_tier = excluded.bom_approver_tier,
                  status = excluded.status,
                  notes = excluded.notes,
                  updated_at = now()
                """,
                (client_id, name, tax_code, code_resolution_mode, bom_proposal_mode,
                 bom_proposal_qty_tolerance_pct, bom_approver_tier, status, notes),
            )


def slug(name: str) -> str:
    base = "".join(c if c.isalnum() else "-" for c in name.lower()).strip("-")
    base = "-".join(filter(None, base.split("-")))
    suffix = secrets.token_hex(2)
    return f"{base[:24]}-{suffix}" if base else f"client-{suffix}"


@router.get("/clients", response_class=HTMLResponse)
async def list_view(request: Request):
    user = auth.require_user(request)
    items = list_clients()
    allowed = auth.visible_clients(user)
    if allowed is not None:
        allowed_set = set(allowed)
        items = [it for it in items if it["client_id"] in allowed_set]
    return request.app.state.templates.TemplateResponse(
        request, "clients/list.html",
        {"items": items, "active_root": "clients",
         "can_create_client": auth.can_create_client(user)},
    )


@router.get("/clients/new", response_class=HTMLResponse)
async def new_view(request: Request):
    user = auth.require_user(request)
    if not auth.can_create_client(user):
        raise HTTPException(403, "forbidden")
    return request.app.state.templates.TemplateResponse(
        request, "clients/edit.html",
        {"client": None, "modes": CODE_RESOLUTION_MODES,
         "bom_modes": BOM_PROPOSAL_MODES, "approver_tiers": BOM_APPROVER_TIERS,
         "active_root": "clients"},
    )


@router.post("/clients/new")
async def new_submit(
    request: Request,
    name: str = Form(...), tax_code: str = Form(""),
    code_resolution_mode: str = Form("simple_mapping"),
    bom_proposal_mode: str = Form("auto"),
    bom_proposal_qty_tolerance_pct: float = Form(5.0),
    bom_approver_tier: str = Form("edit"),
    notes: str = Form(""),
):
    user = auth.require_user(request)
    if not auth.can_create_client(user):
        raise HTTPException(403, "forbidden")
    if code_resolution_mode not in CODE_RESOLUTION_MODES:
        raise HTTPException(400, "Invalid code_resolution_mode")
    if bom_proposal_mode not in BOM_PROPOSAL_MODES:
        raise HTTPException(400, "Invalid bom_proposal_mode")
    if bom_approver_tier not in BOM_APPROVER_TIERS:
        raise HTTPException(400, "Invalid bom_approver_tier")
    client_id = slug(name)
    upsert_client(
        client_id=client_id, name=name.strip(), tax_code=tax_code.strip() or None,
        code_resolution_mode=code_resolution_mode, bom_proposal_mode=bom_proposal_mode,
        bom_proposal_qty_tolerance_pct=bom_proposal_qty_tolerance_pct,
        bom_approver_tier=bom_approver_tier,
        status="active", notes=notes.strip() or None,
    )
    return RedirectResponse(url=f"/clients/{client_id}", status_code=303)


@router.get("/clients/{client_id}", response_class=HTMLResponse)
async def workspace_view(request: Request, client_id: str):
    user = auth.require_user(request)
    auth.require_can_view_client(user, client_id)
    client = get_client(client_id)
    if not client:
        raise HTTPException(404, "Client not found")
    stats = stats_for_client(client_id)
    return request.app.state.templates.TemplateResponse(
        request, "clients/workspace.html",
        {"client": client, "stats": stats,
         "active_root": "clients", "active_tab": "overview",
         "can_edit": auth.can_edit_client(user, client_id),
         "can_edit_config": auth.can_edit_client_config(user, client_id)},
    )


@router.get("/clients/{client_id}/edit", response_class=HTMLResponse)
async def edit_view(request: Request, client_id: str):
    user = auth.require_user(request)
    if not auth.can_edit_client_config(user, client_id):
        raise HTTPException(403, "forbidden")
    client = get_client(client_id)
    if not client:
        raise HTTPException(404, "Client not found")
    stats = stats_for_client(client_id)
    return request.app.state.templates.TemplateResponse(
        request, "clients/edit.html",
        {"client": client, "stats": stats,
         "modes": CODE_RESOLUTION_MODES,
         "bom_modes": BOM_PROPOSAL_MODES, "approver_tiers": BOM_APPROVER_TIERS,
         "active_root": "clients", "active_tab": "config",
         "can_edit_technical": auth.can_edit_client_technical(user, client_id)},
    )


@router.post("/clients/{client_id}/edit")
async def edit_submit(
    request: Request, client_id: str,
    name: str = Form(...), tax_code: str = Form(""),
    code_resolution_mode: str = Form(""),
    bom_proposal_mode: str = Form("auto"),
    bom_proposal_qty_tolerance_pct: float = Form(5.0),
    bom_approver_tier: str = Form("edit"),
    notes: str = Form(""), status: str = Form("active"),
):
    user = auth.require_user(request)
    if not auth.can_edit_client_config(user, client_id):
        raise HTTPException(403, "forbidden")
    existing = get_client(client_id)
    if not existing:
        raise HTTPException(404, "Client not found")
    if auth.can_edit_client_technical(user, client_id) and code_resolution_mode:
        if code_resolution_mode not in CODE_RESOLUTION_MODES:
            raise HTTPException(400, "Invalid code_resolution_mode")
        new_mode = code_resolution_mode
    else:
        new_mode = existing["code_resolution_mode"]
    if bom_proposal_mode not in BOM_PROPOSAL_MODES:
        raise HTTPException(400, "Invalid bom_proposal_mode")
    if bom_approver_tier not in BOM_APPROVER_TIERS:
        raise HTTPException(400, "Invalid bom_approver_tier")
    upsert_client(
        client_id=client_id, name=name.strip(), tax_code=tax_code.strip() or None,
        code_resolution_mode=new_mode,
        bom_proposal_mode=bom_proposal_mode,
        bom_proposal_qty_tolerance_pct=bom_proposal_qty_tolerance_pct,
        bom_approver_tier=bom_approver_tier,
        status=status, notes=notes.strip() or None,
    )
    return RedirectResponse(url=f"/clients/{client_id}", status_code=303)


# ─────────────────────────────────────────────────────────────────────
# Per-client parser rules — UI page (dev only)
# Backed by hub.client_parser_rules; the same data the JSON CRUD endpoints
# under /v1/hub/clients/{id}/parser-rules manage.
# ─────────────────────────────────────────────────────────────────────


@router.get("/clients/{client_id}/parser-rules", response_class=HTMLResponse)
async def parser_rules_view(request: Request, client_id: str,
                            error: str = "", flash: str = ""):
    user = auth.require_user(request)
    if not auth.can_edit_client_technical(user, client_id):
        raise HTTPException(403, "forbidden")
    client = get_client(client_id)
    if not client:
        raise HTTPException(404, "Client not found")
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "select rule_id, output_field, priority, pattern, source_field, "
            "  match_group, match_action, no_match_action, enabled, notes "
            "from hub.client_parser_rules where client_id=%s "
            "order by output_field, enabled desc, priority asc",
            (client_id,),
        )
        cols = [d[0] for d in cur.description]
        rules = [dict(zip(cols, r)) for r in cur.fetchall()]
    return request.app.state.templates.TemplateResponse(
        request, "clients/parser_rules.html",
        {"client": client, "stats": stats_for_client(client_id),
         "rules": rules, "error": error, "flash": flash,
         "active_root": "clients", "active_tab": "parser_rules"},
    )


@router.post("/clients/{client_id}/parser-rules/create")
async def parser_rules_create(request: Request, client_id: str,
                              output_field: str = Form(...),
                              priority: int = Form(...),
                              pattern: str = Form(...),
                              source_field: str = Form("goods_name"),
                              match_action: str = Form("capture"),
                              no_match_action: str = Form("next_rule"),
                              match_group: int = Form(1),
                              notes: str = Form("")):
    user = auth.require_user(request)
    if not auth.can_edit_client_technical(user, client_id):
        raise HTTPException(403, "forbidden")
    from app.parsers.client_parser_rules import (
        InvalidPatternError, clear_rules_cache, compile_pattern,
    )
    try:
        compile_pattern(pattern)
    except InvalidPatternError as e:
        return RedirectResponse(
            url=f"/clients/{client_id}/parser-rules?error={str(e)}",
            status_code=303,
        )
    with connect(user_id=user.user_id) as conn, conn.cursor() as cur:
        try:
            cur.execute(
                "insert into hub.client_parser_rules "
                "(client_id, output_field, priority, pattern, source_field, "
                " match_group, match_action, no_match_action, notes, created_by) "
                "values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
                (client_id, output_field, priority, pattern, source_field,
                 match_group, match_action, no_match_action,
                 notes.strip() or None, user.user_id),
            )
        except Exception as e:
            return RedirectResponse(
                url=f"/clients/{client_id}/parser-rules?error={type(e).__name__}: {str(e)[:120]}",
                status_code=303,
            )
    clear_rules_cache()
    return RedirectResponse(
        url=f"/clients/{client_id}/parser-rules?flash=Rule+created",
        status_code=303,
    )


@router.get("/clients/{client_id}/parser-rules/{rule_id}/edit",
            response_class=HTMLResponse)
async def parser_rules_edit_view(request: Request, client_id: str, rule_id: int,
                                 error: str = ""):
    user = auth.require_user(request)
    if not auth.can_edit_client_technical(user, client_id):
        raise HTTPException(403, "forbidden")
    client = get_client(client_id)
    if not client:
        raise HTTPException(404, "Client not found")
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "select rule_id, output_field, priority, pattern, source_field, "
            "  match_group, match_action, no_match_action, enabled, notes "
            "from hub.client_parser_rules where client_id=%s and rule_id=%s",
            (client_id, rule_id),
        )
        row = cur.fetchone()
        if not row:
            raise HTTPException(404, "Rule not found")
        cols = [d[0] for d in cur.description]
        rule = dict(zip(cols, row))
    return request.app.state.templates.TemplateResponse(
        request, "clients/parser_rule_edit.html",
        {"client": client, "stats": stats_for_client(client_id),
         "rule": rule, "error": error,
         "active_root": "clients", "active_tab": "parser_rules"},
    )


@router.post("/clients/{client_id}/parser-rules/{rule_id}/edit")
async def parser_rules_edit_post(request: Request, client_id: str, rule_id: int,
                                 priority: int = Form(...),
                                 pattern: str = Form(...),
                                 source_field: str = Form("goods_name"),
                                 match_action: str = Form("capture"),
                                 no_match_action: str = Form("next_rule"),
                                 match_group: int = Form(1),
                                 notes: str = Form("")):
    user = auth.require_user(request)
    if not auth.can_edit_client_technical(user, client_id):
        raise HTTPException(403, "forbidden")
    from app.parsers.client_parser_rules import (
        InvalidPatternError, clear_rules_cache, compile_pattern,
    )
    try:
        compile_pattern(pattern)
    except InvalidPatternError as e:
        return RedirectResponse(
            url=f"/clients/{client_id}/parser-rules/{rule_id}/edit?error={str(e)}",
            status_code=303,
        )
    with connect(user_id=user.user_id) as conn, conn.cursor() as cur:
        cur.execute(
            "update hub.client_parser_rules "
            "set priority=%s, pattern=%s, source_field=%s, "
            "    match_group=%s, match_action=%s, no_match_action=%s, "
            "    notes=%s "
            "where client_id=%s and rule_id=%s",
            (priority, pattern, source_field, match_group,
             match_action, no_match_action, notes.strip() or None,
             client_id, rule_id),
        )
    clear_rules_cache()
    return RedirectResponse(
        url=f"/clients/{client_id}/parser-rules?flash=Rule+{rule_id}+updated",
        status_code=303,
    )


@router.post("/clients/{client_id}/parser-rules/{rule_id}/disable")
async def parser_rules_disable(request: Request, client_id: str, rule_id: int):
    user = auth.require_user(request)
    if not auth.can_edit_client_technical(user, client_id):
        raise HTTPException(403, "forbidden")
    from app.parsers.client_parser_rules import clear_rules_cache
    with connect(user_id=user.user_id) as conn, conn.cursor() as cur:
        cur.execute(
            "update hub.client_parser_rules set enabled=false "
            "where client_id=%s and rule_id=%s",
            (client_id, rule_id),
        )
    clear_rules_cache()
    return RedirectResponse(
        url=f"/clients/{client_id}/parser-rules?flash=Rule+disabled",
        status_code=303,
    )


def _evaluate_for_test_panel(rules_eval, source_value: str) -> tuple[str | None, list[dict]]:
    """Run a single source_value through compiled rules. Returns
    (final_output, trace) — same shape the JSON /test endpoint emits."""
    trace: list[dict] = []
    final: str | None = None
    final_set = False
    for r in rules_eval:
        m = r.compiled.search(source_value)
        entry = {
            "rule_id": r.rule_id, "priority": r.priority,
            "matched": bool(m), "match_action": r.match_action,
            "no_match_action": r.no_match_action,
            "captured": None, "matched_text": None,
        }
        if m:
            captured = m.group(r.match_group) if r.match_action == "capture" else None
            entry["captured"] = captured
            entry["matched_text"] = m.group(0)
            if not final_set:
                final = None if r.match_action == "reject" else captured
                final_set = True
        elif not final_set and r.no_match_action == "return_null":
            final = None
            final_set = True
        trace.append(entry)
    return final, trace


def _list_rules_for_template(client_id: str) -> list[dict]:
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "select rule_id, output_field, priority, pattern, source_field, "
            "  match_group, match_action, no_match_action, enabled, notes "
            "from hub.client_parser_rules where client_id=%s "
            "order by output_field, enabled desc, priority asc",
            (client_id,),
        )
        cols = [d[0] for d in cur.description]
        return [dict(zip(cols, r)) for r in cur.fetchall()]


@router.post("/clients/{client_id}/parser-rules/test", response_class=HTMLResponse)
async def parser_rules_test_view(request: Request, client_id: str,
                                 output_field: str = Form("internal_code"),
                                 sample_input: str = Form(""),
                                 mode: str = Form("single")):
    """Run sample_input (mode=single) OR last N BCCT rows (mode=recent)
    OR aggregate counts over last 1k rows (mode=coverage) through the
    client's rules. Read-only; never persists."""
    user = auth.require_user(request)
    if not auth.can_edit_client_technical(user, client_id):
        raise HTTPException(403, "forbidden")
    client = get_client(client_id)
    if not client:
        raise HTTPException(404, "Client not found")
    from app.parsers.client_parser_rules import load_rules
    rules_eval = load_rules(client_id=client_id, output_field=output_field)
    test_result: dict = {
        "mode": mode, "output_field": output_field,
        "sample_input": sample_input,
    }
    if mode == "recent":
        # Last 50 rows; show source_value + computed output per row.
        source = rules_eval[0].source_field if rules_eval else "goods_name"
        with connect() as conn, conn.cursor() as cur:
            cur.execute(
                f"select transaction_key, line_no, declaration_no, "
                f"       customs_code, {source} as source_value "
                f"from hub.bcct_rows where client_id = %s "
                f"order by indexed_at desc limit 50",
                (client_id,),
            )
            rows = cur.fetchall()
        recent = []
        for txkey, line, decl, customs, src_val in rows:
            out, _ = _evaluate_for_test_panel(rules_eval, src_val or "")
            recent.append({
                "transaction_key": txkey, "line_no": line,
                "declaration_no": decl, "customs_code": customs,
                "source_value": (src_val or "")[:120],
                "output": out,
            })
        test_result["recent"] = recent
        test_result["recent_source_field"] = source
    elif mode == "coverage":
        source = rules_eval[0].source_field if rules_eval else "goods_name"
        with connect() as conn, conn.cursor() as cur:
            cur.execute(
                f"select {source} from hub.bcct_rows where client_id = %s "
                f"order by indexed_at desc limit 1000",
                (client_id,),
            )
            sources = [r[0] or "" for r in cur.fetchall()]
        resolved = 0
        null_count = 0
        sample_resolved: list[str] = []
        for src in sources:
            out, _ = _evaluate_for_test_panel(rules_eval, src)
            if out is None:
                null_count += 1
            else:
                resolved += 1
                if len(sample_resolved) < 10:
                    sample_resolved.append(out)
        test_result["coverage"] = {
            "total": len(sources),
            "resolved": resolved,
            "null": null_count,
            "sample_resolved": sample_resolved,
            "source_field": source,
        }
    else:
        # mode=single (default)
        final, trace = _evaluate_for_test_panel(rules_eval, sample_input)
        test_result["final_output"] = final
        test_result["trace"] = trace
    return request.app.state.templates.TemplateResponse(
        request, "clients/parser_rules.html",
        {"client": client, "stats": stats_for_client(client_id),
         "rules": _list_rules_for_template(client_id),
         "test_result": test_result,
         "active_root": "clients", "active_tab": "parser_rules"},
    )
