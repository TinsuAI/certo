"""App release version resolver.

Precedence: build-baked env (CO_VERSION/CO_GIT_SHA/CO_BUILD_TIME) →
dev fallback (pyproject version + best-effort git sha) → "unknown".

`source` tells the UI which path won so it can show a "(dev)" hint.

Naming: CO_-prefixed env + ``app_version`` in templates, never bare
``version`` — keeps this app/release version distinct from record
versioning (BOM artifacts, source/declaration config versions).
"""
from __future__ import annotations

import functools
import os
import subprocess
import tomllib
from pathlib import Path

_PYPROJECT = Path(__file__).resolve().parent.parent / "pyproject.toml"


@functools.lru_cache(maxsize=1)
def _read_pyproject_version() -> str | None:
    try:
        data = tomllib.loads(_PYPROJECT.read_text(encoding="utf-8"))
        return data.get("project", {}).get("version") or None
    except (OSError, tomllib.TOMLDecodeError):
        return None


@functools.lru_cache(maxsize=1)
def _dev_git_sha() -> str | None:
    try:
        out = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=_PYPROJECT.parent,
            capture_output=True,
            text=True,
            timeout=2,
        )
        sha = out.stdout.strip()
        return sha or None
    except (OSError, subprocess.SubprocessError):
        return None


def version_info() -> dict[str, str]:
    baked = os.environ.get("CO_VERSION")
    if baked:
        return {
            "version": baked,
            "git_sha": os.environ.get("CO_GIT_SHA", "unknown"),
            "build_time": os.environ.get("CO_BUILD_TIME", "unknown"),
            "source": "build",
        }
    pyproj = _read_pyproject_version()
    if pyproj:
        return {
            "version": pyproj,
            "git_sha": _dev_git_sha() or "unknown",
            "build_time": "dev",
            "source": "dev",
        }
    return {
        "version": "unknown",
        "git_sha": _dev_git_sha() or "unknown",
        "build_time": "unknown",
        "source": "unknown",
    }
