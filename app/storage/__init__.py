"""File storage abstraction. LocalFS day 1; S3-compat phase 2."""
from __future__ import annotations

import hashlib
import os
import secrets
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol


def sha256_bytes(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


@dataclass(frozen=True)
class StoredFile:
    backend: str
    path: str
    size_bytes: int
    content_sha256: str


class FileBackend(Protocol):
    name: str

    def put(self, blob: bytes, *, key: str) -> StoredFile: ...

    def get(self, key: str) -> bytes: ...

    def delete(self, key: str) -> None: ...


class LocalFSBackend:
    name = "localfs"

    def __init__(self, root: Path):
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)

    def _full(self, key: str) -> Path:
        return self.root / key

    def put(self, blob: bytes, *, key: str) -> StoredFile:
        target = self._full(key)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(blob)
        return StoredFile(
            backend=self.name, path=key,
            size_bytes=len(blob), content_sha256=sha256_bytes(blob),
        )

    def get(self, key: str) -> bytes:
        return self._full(key).read_bytes()

    def delete(self, key: str) -> None:
        target = self._full(key)
        if target.exists():
            target.unlink()


_BACKEND: FileBackend | None = None


def get_backend() -> FileBackend:
    global _BACKEND
    if _BACKEND is None:
        root = Path(os.environ.get("DATA_HUB_FILES_ROOT", "data/files")).resolve()
        _BACKEND = LocalFSBackend(root)
    return _BACKEND


def save_upload(blob: bytes, *, filename: str, module: str, client_id: str | None) -> StoredFile:
    """Persist an uploaded file under a sanitized key. Returns StoredFile."""
    safe = "".join(c if c.isalnum() or c in ".-_" else "_" for c in filename)[:120] or "upload"
    sub = client_id or "_global"
    key = f"{module}/{sub}/{secrets.token_hex(8)}_{safe}"
    return get_backend().put(blob, key=key)
