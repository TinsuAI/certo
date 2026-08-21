"""Wrapper that runs a subprocess + updates `hub.background_jobs`.

Spawned by web routes when staff clicks a long-running button (re-embed
catalog, refresh substitutes). Lifecycle:

    pending → running (mark_running, pid set) → done|error (with summary)

Captures stdout+stderr to a log file path passed by the caller. The
last few lines of the log become the job's summary on success or
error_message on failure.

Usage (called by app code, not by humans):
    python -m scripts._job_runner <job_id> <log_path> -- <cmd> <args...>
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, os.fspath(Path(__file__).resolve().parents[1]))

from hub.app import jobs


_TAIL_LINES = 20
_TIMEOUT_SECONDS = 60 * 60   # 1 hour cap; longer runs need a real worker


def _tail(path: Path, n: int = _TAIL_LINES) -> str:
    if not path.exists():
        return "(no log)"
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            return "".join(f.readlines()[-n:])
    except OSError as exc:
        return f"(log read failed: {exc})"


def main() -> int:
    if len(sys.argv) < 4 or sys.argv[3] != "--":
        print("usage: _job_runner <job_id> <log_path> -- <cmd> <args...>",
              file=sys.stderr)
        return 2
    job_id = int(sys.argv[1])
    log_path = Path(sys.argv[2])
    cmd = sys.argv[4:]

    log_path.parent.mkdir(parents=True, exist_ok=True)

    try:
        jobs.mark_running(job_id, pid=os.getpid())
    except Exception as exc:
        # If we can't update the DB, the job is orphaned but the work
        # may still be valuable. Print and proceed.
        print(f"WARN: mark_running failed: {exc}", file=sys.stderr)

    # Run the command, redirecting both streams to the log file.
    rc: int = -1
    try:
        with open(log_path, "ab") as logf:
            proc = subprocess.run(
                cmd, stdout=logf, stderr=subprocess.STDOUT,
                timeout=_TIMEOUT_SECONDS,
            )
            rc = proc.returncode
    except subprocess.TimeoutExpired:
        try:
            jobs.mark_error(
                job_id,
                error=f"Quá thời gian {_TIMEOUT_SECONDS}s — đã hủy.\n\n"
                      + _tail(log_path),
            )
        except Exception:
            pass
        return 124
    except Exception as exc:
        try:
            jobs.mark_error(
                job_id,
                error=f"{type(exc).__name__}: {exc}\n\n" + _tail(log_path),
            )
        except Exception:
            pass
        return 1

    tail = _tail(log_path)
    if rc == 0:
        try:
            jobs.mark_done(job_id, summary=tail)
        except Exception as exc:
            print(f"WARN: mark_done failed: {exc}", file=sys.stderr)
    else:
        try:
            jobs.mark_error(
                job_id, error=f"exit code {rc}\n\n{tail}",
            )
        except Exception as exc:
            print(f"WARN: mark_error failed: {exc}", file=sys.stderr)
    return rc


if __name__ == "__main__":
    sys.exit(main())
