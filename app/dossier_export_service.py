"""In-process background runner for the C/O dossier .zip export.

Brief: `.ai/features/2026-06-07-background-dossier-export.md`.

The synchronous export route used to build the whole zip (a 25MB / 5668-page
import dossier ran ~45s) inside the request. This service runs the build off the
request thread and persists status + result per case so the review page can poll
and download when ready.

Design notes:
- **Token injection.** DH calls need the operator JWT from the
  `CURRENT_DATA_HUB_TOKEN` contextvar, which is request-scoped and gone by the
  time the worker runs. We snapshot the context with `copy_context()` at submit
  (mirrors `bom_service`) and also re-set the token explicitly inside the job, so
  the worker can reach Data Hub.
- **Staleness.** A saved zip is keyed to an opaque content-revision token the
  caller supplies (a hash of the dossier-relevant case fields — see
  `dossier_content_revision`). When the current token differs from the one the
  zip was built from, the export is stale → regenerate. The service treats the
  token as opaque, so the key strategy lives with the dossier, not here.
- **State home.** Per-case entries live in the client state under
  `state["dossier_exports"]`, exactly like `origin_calculation_lock` — side-state
  that does NOT bump the case revision.
- **Single worker** (`--workers 1` deploy), one heavy job at a time.
"""
from __future__ import annotations

from concurrent.futures import Future, ThreadPoolExecutor
from contextvars import copy_context
from pathlib import Path
from typing import Callable

from app.co_case_store import case_lock, case_root, load_state, now_iso, safe_filename, save_state
from app.data_hub_client import set_current_data_hub_token

_EXECUTOR = ThreadPoolExecutor(max_workers=1, thread_name_prefix="dossier-export")
_FUTURES: dict[tuple[str, str], Future] = {}

Builder = Callable[[], tuple[bytes, list[dict]]]


def submit_dossier_export(
    client: dict,
    case_id: str,
    *,
    token: str,
    current_revision: str,
    filename: str,
    builder: Builder,
) -> dict:
    """Queue (or re-attach to) a dossier export job for `case_id`.

    Idempotent: a fresh `running` entry returns as-is rather than launching a
    second build. Returns the status view (see `_view`)."""
    client_id = client["id"]
    with case_lock(client_id):
        state = load_state(client_id)
        exports = state.setdefault("dossier_exports", {})
        existing = exports.get(case_id) or {}
        if _is_running(client_id, case_id, existing):
            return _view(existing, current_revision)
        exports[case_id] = {
            "status": "running",
            "built_from_revision": current_revision,
            "filename": filename,
            "started_at": now_iso(),
            "warnings": [],
        }
        save_state(client_id, state)

    ctx = copy_context()
    future = _EXECUTOR.submit(ctx.run, _run_export_job, client, case_id, token, filename, builder)
    _FUTURES[(client_id, case_id)] = future
    return dossier_export_status(client, case_id, current_revision=current_revision)


def dossier_export_status(client: dict, case_id: str, *, current_revision: str) -> dict:
    state = load_state(client["id"])
    entry = (state.get("dossier_exports") or {}).get(case_id) or {}
    return _view(entry, current_revision)


def dossier_export_result_path(client: dict, case_id: str) -> tuple[Path, str] | None:
    state = load_state(client["id"])
    entry = (state.get("dossier_exports") or {}).get(case_id) or {}
    rel = entry.get("result_path")
    if entry.get("status") != "done" or not rel:
        return None
    path = case_root(client["id"]) / rel
    if not path.exists():
        return None
    return path, entry.get("filename") or path.name


def _run_export_job(client: dict, case_id: str, token: str, filename: str, builder: Builder) -> None:
    if token:
        set_current_data_hub_token(token)
    try:
        content, warnings = builder()
        rel_path = _write_result(client["id"], case_id, filename, content)
        _finish(client, case_id, "done", result_path=str(rel_path), warnings=warnings or [])
    except Exception as exc:  # noqa: BLE001 — surface the failure, never crash the worker
        _finish(client, case_id, "failed", error=str(exc) or exc.__class__.__name__)


def _write_result(client_id: str, case_id: str, filename: str, content: bytes) -> Path:
    root = case_root(client_id) / "dossier-exports" / case_id
    root.mkdir(parents=True, exist_ok=True)
    abs_path = root / safe_filename(filename)
    abs_path.write_bytes(content)
    return abs_path.relative_to(case_root(client_id))


def _finish(client: dict, case_id: str, status: str, *, result_path: str = "", warnings: list | None = None, error: str = "") -> None:
    with case_lock(client["id"]):
        state = load_state(client["id"])
        exports = state.setdefault("dossier_exports", {})
        entry = exports.get(case_id) or {}
        entry["status"] = status
        entry["finished_at"] = now_iso()
        if result_path:
            entry["result_path"] = result_path
        if warnings is not None:
            entry["warnings"] = warnings
        if error:
            entry["error"] = error
        exports[case_id] = entry
        save_state(client["id"], state)
    # Job finished — drop its future so the per-process registry doesn't grow
    # unbounded across exports.
    _FUTURES.pop((client["id"], case_id), None)


def _is_running(client_id: str, case_id: str, entry: dict) -> bool:
    """Is a job for this case genuinely in flight (so a re-submit should
    re-attach rather than launch a duplicate)?

    Signal: a live Future in THIS process. The deploy runs a single worker, so a
    `running` entry with no live future means the worker died on a restart/deploy
    — orphaned and immediately re-runnable, no timeout to wait out."""
    if entry.get("status") != "running":
        return False
    future = _FUTURES.get((client_id, case_id))
    return future is not None and not future.done()


def _view(entry: dict, current_revision: str) -> dict:
    status = entry.get("status") or "idle"
    built_from = entry.get("built_from_revision")
    stale = bool(status == "done" and current_revision and built_from != current_revision)
    return {
        "status": status,
        "stale": stale,
        "can_download": status == "done" and not stale,
        "filename": entry.get("filename", ""),
        "warnings": entry.get("warnings", []),
        "error": entry.get("error", ""),
        "started_at": entry.get("started_at", ""),
        "finished_at": entry.get("finished_at", ""),
    }
