"""Background job routes — start a job + view its status.

Long-running ops (re-embed catalog, refresh substitute candidates) are
spawned as detached subprocesses wrapped by `scripts/_job_runner.py`,
which writes status into `hub.background_jobs`. The web UI doesn't
poll the OS — it polls the DB row.
"""
from __future__ import annotations

import os
import subprocess
from pathlib import Path

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from hub.app import auth, embedding, jobs
from hub.app.routes.clients import get_client


router = APIRouter()


_REPO_ROOT = Path(__file__).resolve().parents[2]
_LOG_DIR = Path("/tmp/data_hub_jobs")


_JOB_RECIPES: dict[str, dict] = {
    "embedding_refresh": {
        "label_template": "Cập nhật phân tích AI ({client_id})",
        "force_label_template":
            "Phân tích AI lại từ đầu ({client_id})",
        "script": "embed_materials.py",
        "extra_args": ["--commit"],
        "force_arg": "--force",
    },
    "embedding_refresh_force": {
        "label_template": "Phân tích AI lại từ đầu ({client_id})",
        "script": "embed_materials.py",
        "extra_args": ["--commit", "--force"],
    },
    "substitute_refresh": {
        "label_template": "Tìm lại nhóm vật tư tương tự ({client_id})",
        "script": "refresh_substitutes.py",
        "extra_args": [],
    },
    "declaration_pdf_render": {
        "label_template": "Render PDF tờ khai còn thiếu ({client_id})",
        "script": "backfill_declaration_pdfs.py",
        "extra_args": [],
    },
    "material_group_backfill": {
        "label_template": "Cập nhật loại trừ theo bản đồ Material Group ({client_id})",
        "script": "backfill_johnson_material_group.py",
        "extra_args": ["--exclusions-only", "--apply"],
    },
}


def _spawn_job(
    *, client_id: str, kind: str, force: bool, started_by: str | None,
) -> int:
    """Insert job row + spawn detached wrapper. Returns job_id."""
    if kind == "embedding_refresh" and force:
        recipe_key = "embedding_refresh_force"
        canonical_kind = "embedding_refresh"
    else:
        recipe_key = kind
        canonical_kind = kind
    recipe = _JOB_RECIPES.get(recipe_key)
    if not recipe:
        raise HTTPException(400, f"Unknown job kind: {kind}")

    label = recipe["label_template"].format(client_id=client_id)
    _LOG_DIR.mkdir(parents=True, exist_ok=True)

    job_id = jobs.create_job(
        client_id=client_id, kind=canonical_kind, label=label,
        started_by=started_by,
    )
    log_path = _LOG_DIR / f"job_{job_id}.log"
    # Update the row with the now-known log_path.
    from hub.app.database import connect
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "update hub.background_jobs set log_path=%s where id=%s",
            (str(log_path), job_id),
        )

    inner_cmd = (
        ["uv", "run", "python", f"scripts/{recipe['script']}",
         "--client", client_id]
        + list(recipe["extra_args"])
    )
    runner_cmd = [
        "uv", "run", "python", "-m", "scripts._job_runner",
        str(job_id), str(log_path), "--",
    ] + inner_cmd

    subprocess.Popen(
        runner_cmd, cwd=os.fspath(_REPO_ROOT),
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    return job_id


# ── start ──────────────────────────────────────────────────────────


@router.post("/clients/{client_id}/jobs/start")
async def start_job(
    request: Request, client_id: str,
    kind: str = Form(...),
    force: str = Form(""),
):
    user = auth.require_user(request)
    auth.require_can_edit_client(user, client_id)
    client = get_client(client_id)
    if not client:
        raise HTTPException(404, "Client not found")

    # For embedding_refresh, require live API key.
    if kind == "embedding_refresh":
        cfg = embedding.get_global_config()
        if not cfg.is_live:
            return RedirectResponse(
                url=f"/clients/{client_id}/catalog?error="
                    "Chưa cấu hình API key cho phân tích AI.",
                status_code=303,
            )

    is_force = force.lower() in ("1", "true", "on", "yes")
    if jobs.has_active(client_id, kind):
        active = jobs.latest(client_id, kind)
        return RedirectResponse(
            url=f"/jobs/{active.id}", status_code=303,
        )

    job_id = _spawn_job(
        client_id=client_id, kind=kind, force=is_force,
        started_by=user.user_id,
    )
    return RedirectResponse(url=f"/jobs/{job_id}", status_code=303)


# ── job detail (auto-refresh) ──────────────────────────────────────


@router.get("/jobs/{job_id}", response_class=HTMLResponse)
async def job_detail(request: Request, job_id: int):
    user = auth.require_user(request)
    job = jobs.get_job(job_id)
    if job is None:
        raise HTTPException(404, "Việc không tồn tại")
    if job.client_id:
        auth.require_can_view_client(user, job.client_id)
        client = get_client(job.client_id)
    else:
        client = None

    log_tail = ""
    if job.log_path:
        from pathlib import Path
        p = Path(job.log_path)
        if p.exists():
            try:
                with open(p, "r", encoding="utf-8", errors="replace") as f:
                    lines = f.readlines()
                log_tail = "".join(lines[-80:])
            except OSError as exc:
                log_tail = f"(không đọc được log: {exc})"

    return request.app.state.templates.TemplateResponse(
        request, "jobs/detail.html",
        {
            "job": job,
            "client": client,
            "log_tail": log_tail,
            "active_root": "clients" if client else "admin",
            "active_tab": "catalog" if client else None,
        },
    )


@router.get("/clients/{client_id}/jobs", response_class=HTMLResponse)
async def jobs_list(request: Request, client_id: str):
    user = auth.require_user(request)
    auth.require_can_view_client(user, client_id)
    client = get_client(client_id)
    if not client:
        raise HTTPException(404, "Client not found")
    rows = jobs.list_for_client(client_id, limit=50)
    return request.app.state.templates.TemplateResponse(
        request, "jobs/list.html",
        {
            "client": client,
            "jobs": rows,
            "active_root": "clients",
            "active_tab": "catalog",
        },
    )
