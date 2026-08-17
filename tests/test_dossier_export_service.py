"""Background dossier-export service — in-process job runner.

Brief: .ai/features/2026-06-07-background-dossier-export.md

The service runs the heavy zip build off the request thread, persists status +
result per case, injects the operator DH token into the worker, and marks a
saved export stale once the case content-revision token changes (reopen / edit /
re-close producing different dossier content).
"""
from __future__ import annotations

from concurrent.futures import Future

import pytest

from app import dossier_export_service as svc
from app.co_case_store import create_case_record
from app.data_hub_client import current_data_hub_token


class DeferredExecutor:
    """Captures submitted work; runs it only when the test calls run_all().

    Lets a test observe the `running` state before completion.
    """

    def __init__(self):
        self.jobs: list = []

    def submit(self, fn, *args, **kwargs):
        fut: Future = Future()
        self.jobs.append((fut, fn, args, kwargs))
        return fut

    def run_all(self):
        pending, self.jobs = self.jobs, []
        for fut, fn, args, kwargs in pending:
            try:
                fut.set_result(fn(*args, **kwargs))
            except Exception as exc:  # pragma: no cover - mirrored into future
                fut.set_exception(exc)


@pytest.fixture(autouse=True)
def _isolate(tmp_path, monkeypatch):
    monkeypatch.setenv("CO_CASE_STORE_ROOT", str(tmp_path / "co-case-store"))
    executor = DeferredExecutor()
    monkeypatch.setattr(svc, "_EXECUTOR", executor)
    svc._FUTURES.clear()
    return executor


def _client():
    return {"id": "growatt-vn", "name": "Growatt VN"}


def _make_case():
    client = _client()
    record = create_case_record(client, {"title": "T", "case_code": "CO-X", "invoice_no": "INV1"})
    return client, record


def _ok_builder(content=b"%PDFZIP-bytes", warnings=None):
    return lambda: (content, warnings or [])


def test_submit_marks_running_before_completion(_isolate):
    client, record = _make_case()
    view = svc.submit_dossier_export(
        client, record["case_id"],
        token="tok", current_revision="rev-1",
        filename="CO-X-dossier.zip", builder=_ok_builder(),
    )
    assert view["status"] == "running"
    assert view["can_download"] is False
    # Nothing written yet — job is still queued in the deferred executor.
    assert svc.dossier_export_result_path(client, record["case_id"]) is None


def test_completion_writes_zip_and_marks_done(_isolate):
    client, record = _make_case()
    svc.submit_dossier_export(
        client, record["case_id"],
        token="tok", current_revision="rev-1",
        filename="CO-X-dossier.zip", builder=_ok_builder(b"ZIPDATA"),
    )
    _isolate.run_all()
    view = svc.dossier_export_status(client, record["case_id"], current_revision="rev-1")
    assert view["status"] == "done"
    assert view["can_download"] is True
    result = svc.dossier_export_result_path(client, record["case_id"])
    assert result is not None
    path, filename = result
    assert path.read_bytes() == b"ZIPDATA"
    assert filename == "CO-X-dossier.zip"


def test_token_is_injected_into_job(_isolate):
    client, record = _make_case()
    seen: dict = {}
    svc.submit_dossier_export(
        client, record["case_id"],
        token="operator-jwt-123", current_revision="rev-1",
        filename="CO-X-dossier.zip",
        builder=lambda: (seen.setdefault("token", current_data_hub_token()) and b"" or b"Z", []),
    )
    _isolate.run_all()
    assert seen["token"] == "operator-jwt-123"
    # The worker's token must not leak back into the calling thread's context.
    assert current_data_hub_token() == ""


def test_builder_exception_marks_failed(_isolate):
    client, record = _make_case()

    def _boom():
        raise RuntimeError("DH render timed out")

    svc.submit_dossier_export(
        client, record["case_id"],
        token="tok", current_revision="rev-1",
        filename="CO-X-dossier.zip", builder=_boom,
    )
    _isolate.run_all()
    view = svc.dossier_export_status(client, record["case_id"], current_revision="rev-1")
    assert view["status"] == "failed"
    assert "timed out" in view["error"]
    assert view["can_download"] is False


def test_warnings_are_persisted(_isolate):
    client, record = _make_case()
    warns = [{"label": "TKN", "declaration_count": 194}]
    svc.submit_dossier_export(
        client, record["case_id"],
        token="tok", current_revision="rev-1",
        filename="CO-X-dossier.zip", builder=_ok_builder(warnings=warns),
    )
    _isolate.run_all()
    view = svc.dossier_export_status(client, record["case_id"], current_revision="rev-1")
    assert view["warnings"] == warns


def test_export_is_stale_when_revision_changes(_isolate):
    client, record = _make_case()
    svc.submit_dossier_export(
        client, record["case_id"],
        token="tok", current_revision="rev-1",
        filename="CO-X-dossier.zip", builder=_ok_builder(),
    )
    _isolate.run_all()
    # Same revision -> still valid.
    fresh = svc.dossier_export_status(client, record["case_id"], current_revision="rev-1")
    assert fresh["stale"] is False and fresh["can_download"] is True
    # Case content changed (reopen + edit bảng kê) -> new revision -> stale.
    view = svc.dossier_export_status(client, record["case_id"], current_revision="rev-2")
    assert view["status"] == "done"
    assert view["stale"] is True
    assert view["can_download"] is False


def test_resubmit_while_running_is_idempotent(_isolate):
    client, record = _make_case()
    builder = _ok_builder()
    svc.submit_dossier_export(
        client, record["case_id"], token="tok",
        current_revision="rev-1", filename="CO-X-dossier.zip", builder=builder,
    )
    svc.submit_dossier_export(
        client, record["case_id"], token="tok",
        current_revision="rev-1", filename="CO-X-dossier.zip", builder=builder,
    )
    # Second submit must re-attach to the in-flight job, not enqueue a 2nd one.
    assert len(_isolate.jobs) == 1


def test_orphaned_running_job_can_be_resubmitted(_isolate):
    """A `running` entry left behind by a process restart (no live future in
    this process) must be re-runnable immediately, not block forever."""
    client, record = _make_case()
    svc.submit_dossier_export(
        client, record["case_id"], token="tok",
        current_revision="rev-1", filename="CO-X-dossier.zip", builder=_ok_builder(),
    )
    # Simulate the restart: the persisted `running` entry survives, but the
    # in-process future registry is gone and the queued job never ran.
    _isolate.jobs.clear()
    svc._FUTURES.clear()
    svc.submit_dossier_export(
        client, record["case_id"], token="tok",
        current_revision="rev-1", filename="CO-X-dossier.zip", builder=_ok_builder(),
    )
    assert len(_isolate.jobs) == 1


def test_orphaned_running_job_reports_failed_so_the_page_offers_a_retry(_isolate, monkeypatch):
    """The review page renders a spinner for `running` and a button for anything
    else. An orphan (worker died mid-job) must therefore NOT keep reading
    `running`, or the operator is left with a spinner and no way out
    (VNG26030107, 2026-08-17)."""
    client, record = _make_case()
    svc.submit_dossier_export(
        client, record["case_id"], token="tok",
        current_revision="rev-1", filename="CO-X-dossier.zip", builder=_ok_builder(),
    )
    _isolate.jobs.clear()
    svc._FUTURES.clear()
    # Inside the grace window the job is still assumed alive (the future is
    # registered just after the state is saved).
    assert svc.dossier_export_status(client, record["case_id"], current_revision="rev-1")["status"] == "running"

    monkeypatch.setattr(svc, "ORPHAN_GRACE_SECONDS", 0)
    view = svc.dossier_export_status(client, record["case_id"], current_revision="rev-1")
    assert view["status"] == "failed"
    assert svc.ORPHAN_ERROR in view["error"]
    assert view["can_download"] is False


def test_live_running_job_is_never_reported_orphaned(_isolate, monkeypatch):
    client, record = _make_case()
    monkeypatch.setattr(svc, "ORPHAN_GRACE_SECONDS", 0)
    svc.submit_dossier_export(
        client, record["case_id"], token="tok",
        current_revision="rev-1", filename="CO-X-dossier.zip", builder=_ok_builder(),
    )
    assert svc.dossier_export_status(client, record["case_id"], current_revision="rev-1")["status"] == "running"


def test_view_reports_elapsed_time(_isolate):
    """The panel promised "~1 phút" while a 157-TKN dossier took 5m42s. It now
    shows how long the build has actually been running."""
    client, record = _make_case()
    svc.submit_dossier_export(
        client, record["case_id"], token="tok",
        current_revision="rev-1", filename="CO-X-dossier.zip", builder=_ok_builder(),
    )
    running = svc.dossier_export_status(client, record["case_id"], current_revision="rev-1")
    assert running["elapsed_seconds"] is not None and running["elapsed_seconds"] >= 0
    assert "giây" in running["elapsed_label"]
    assert svc._elapsed_label(342) == "5 phút 42 giây"
    assert svc._elapsed_label(45) == "45 giây"
    assert svc._elapsed_label(None) == ""
