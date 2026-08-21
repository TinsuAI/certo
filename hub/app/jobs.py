"""Background job tracking for long-running operations.

Used by buttons that kick off subprocesses (re-embed catalog, refresh
substitute candidates). The web route inserts a row, then spawns
`scripts/_job_runner.py <job_id> <cmd...>` which updates the row as
work progresses.

Status lifecycle: pending → running → done | error.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Iterable

from hub.app.database import connect


@dataclass(frozen=True)
class Job:
    id: int
    client_id: str | None
    kind: str
    label: str
    status: str          # 'pending' | 'running' | 'done' | 'error' | 'cancelled'
    started_at: datetime
    running_at: datetime | None
    finished_at: datetime | None
    pid: int | None
    log_path: str | None
    summary: str | None
    error_message: str | None
    started_by: str | None

    @property
    def is_terminal(self) -> bool:
        return self.status in ("done", "error", "cancelled")

    @property
    def is_active(self) -> bool:
        return self.status in ("pending", "running")


def _row_to_job(row: tuple, cols: list[str]) -> Job:
    d = dict(zip(cols, row))
    return Job(**d)


def create_job(
    *, client_id: str | None, kind: str, label: str,
    started_by: str | None = None, log_path: str | None = None,
) -> int:
    """Insert a pending row, return the new id."""
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            """
            insert into hub.background_jobs
              (client_id, kind, label, status, log_path, started_by)
            values (%s, %s, %s, 'pending', %s, %s)
            returning id
            """,
            (client_id, kind, label, log_path, started_by),
        )
        return cur.fetchone()[0]


def mark_running(job_id: int, *, pid: int | None = None) -> None:
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            """
            update hub.background_jobs
               set status='running', running_at=now(), pid=%s
             where id=%s
            """,
            (pid, job_id),
        )


def mark_done(job_id: int, *, summary: str | None = None) -> None:
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            """
            update hub.background_jobs
               set status='done', finished_at=now(), summary=%s
             where id=%s
            """,
            (summary, job_id),
        )


def mark_error(job_id: int, *, error: str) -> None:
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            """
            update hub.background_jobs
               set status='error', finished_at=now(), error_message=%s
             where id=%s
            """,
            (error, job_id),
        )


def get_job(job_id: int) -> Job | None:
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "select * from hub.background_jobs where id=%s", (job_id,),
        )
        row = cur.fetchone()
        if not row:
            return None
        cols = [d.name for d in cur.description]
        return _row_to_job(row, cols)


def list_for_client(client_id: str, *, limit: int = 30) -> list[Job]:
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            """
            select * from hub.background_jobs
             where client_id=%s
             order by started_at desc
             limit %s
            """,
            (client_id, limit),
        )
        cols = [d.name for d in cur.description]
        return [_row_to_job(r, cols) for r in cur.fetchall()]


def latest(client_id: str, kind: str) -> Job | None:
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            """
            select * from hub.background_jobs
             where client_id=%s and kind=%s
             order by started_at desc
             limit 1
            """,
            (client_id, kind),
        )
        row = cur.fetchone()
        if not row:
            return None
        cols = [d.name for d in cur.description]
        return _row_to_job(row, cols)


def has_active(client_id: str, kind: str) -> bool:
    """Is a job of this kind currently pending/running for this client?"""
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            """
            select 1 from hub.background_jobs
             where client_id=%s and kind=%s
               and status in ('pending', 'running')
             limit 1
            """,
            (client_id, kind),
        )
        return cur.fetchone() is not None
