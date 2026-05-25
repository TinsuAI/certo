"""Bulk ZIP upload for per-declaration TKN/TKX form files.

Pipeline (matches `.ai/features/2026-05-25-bulk-declaration-zip-upload/brief.md`):

  validate_zip(bytes)            → reject oversized / bomb / traversal / corrupt
  extract_to_staging(bytes, root) → write supported members to staging dir
  parse_staged_files(path)        → classify ok / mismatch / parse_error
  annotate_dedup_status(files, …) → flip ok → duplicate when sha256 known
  commit_staged_files(path, …)    → idempotent insert via store
  cancel_staging / reap_expired_staging → housekeeping

The route layer composes these; nothing here knows about HTTP.
"""
from __future__ import annotations

import io
import re
import shutil
import time
import uuid
import zipfile
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Iterable

from app.database import connect
from app.parsers.declaration_files import (
    DeclarationFileError,
    DeclarationFileMismatchError,
    is_supported_filename,
    parse_declaration_file,
    parse_filename,
)
from app.storage import save_upload, sha256_bytes
from app.stores.customs_declaration_files import insert_declaration_file


# ─── Caps (locked in brief D6) ─────────────────────────────────────────

MAX_ZIP_BYTES = 256 * 1024 * 1024            # 256 MB compressed upload
MAX_EXTRACTED_BYTES = 2 * 1024 * 1024 * 1024  # 2 GB total uncompressed
MAX_MEMBER_BYTES = 10 * 1024 * 1024           # 10 MB per single file
MAX_MEMBERS = 5000                            # supported per-decl members

STAGING_ROOT = Path("/tmp/data-hub-staging")
STAGING_TTL_SECONDS = 3600  # 1h — see brief Open Questions

_STAGING_PREFIX = "zip-"
_STAGING_ID_RE = re.compile(
    r"^zip-[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
)


# ─── Exceptions ────────────────────────────────────────────────────────


class ZipUploadError(Exception):
    """Base for any rejection in the bulk-upload pipeline."""


class ZipCorruptError(ZipUploadError):
    """Bytes are not a parseable ZIP archive."""


class ZipTooLargeError(ZipUploadError):
    """Uploaded ZIP > MAX_ZIP_BYTES."""


class ZipTooManyMembersError(ZipUploadError):
    """ZIP contains more supported members than MAX_MEMBERS."""


class ZipMemberTooLargeError(ZipUploadError):
    """One member's declared uncompressed size > MAX_MEMBER_BYTES."""


class ZipBombError(ZipUploadError):
    """Sum of declared uncompressed sizes > MAX_EXTRACTED_BYTES."""


class ZipPathTraversalError(ZipUploadError):
    """A member's name contains `..` or an absolute path."""


# ─── Result data classes ───────────────────────────────────────────────


@dataclass(frozen=True)
class ExtractResult:
    staging_id: str
    staging_path: Path
    total_in_zip: int          # every member in the archive
    ignored_non_pattern: int   # filtered out (README, .DS_Store, …)
    extracted: int             # written to staging


@dataclass(frozen=True)
class StagedFile:
    name: str                  # basename in staging dir
    size_bytes: int
    sha256: str
    declaration_no: str | None
    file_kind: str | None      # 'xls' | 'pdf' | None
    status: str                # 'ok' | 'duplicate' | 'mismatch' | 'parse_error'
    reason: str | None         # error msg for non-ok rows


@dataclass(frozen=True)
class CommitResult:
    inserted: int
    deduped: int
    mismatch_skipped: int
    parse_error_skipped: int
    store_errors: int
    errors: list[tuple[str, str]]  # (filename, error msg)


# ─── validate_zip ──────────────────────────────────────────────────────


def _is_traversal_name(name: str) -> bool:
    """True if a ZIP member name escapes the destination."""
    if not name or name.endswith("/"):  # directory entries — caller filters
        return False
    if name.startswith("/") or name.startswith("\\"):
        return True
    # Reject any component equal to `..`. (Windows uses `\\` too.)
    parts = re.split(r"[\\/]", name)
    return any(p == ".." for p in parts)


def validate_zip(
    zip_bytes: bytes,
    *,
    _max_zip_bytes: int = MAX_ZIP_BYTES,
    _max_extracted_bytes: int = MAX_EXTRACTED_BYTES,
    _max_member_bytes: int = MAX_MEMBER_BYTES,
    _max_members: int = MAX_MEMBERS,
) -> None:
    """Run every cap + safety check before touching the filesystem.

    The `_max_*` keyword args are private overrides for tests so we can
    trigger bomb / count rejections without holding 2GB of payload in RAM.
    """
    if len(zip_bytes) > _max_zip_bytes:
        raise ZipTooLargeError(
            f"ZIP is {len(zip_bytes)} bytes, max {_max_zip_bytes}",
        )
    try:
        zf = zipfile.ZipFile(io.BytesIO(zip_bytes))
    except zipfile.BadZipFile as exc:
        raise ZipCorruptError(f"not a valid ZIP archive: {exc}") from exc

    with zf:
        infos = [zi for zi in zf.infolist() if not zi.is_dir()]
        # Traversal check first — defence-in-depth even for non-supported
        # members (zip parser may include arbitrary names we'd skip later).
        for zi in infos:
            if _is_traversal_name(zi.filename):
                raise ZipPathTraversalError(
                    f"member name escapes destination: {zi.filename!r}",
                )

        # Per-member size cap applies to every file (don't let a bomb hide
        # behind a name we'd ignore at extract time).
        for zi in infos:
            if zi.file_size > _max_member_bytes:
                raise ZipMemberTooLargeError(
                    f"{zi.filename!r}: {zi.file_size} bytes "
                    f"> {_max_member_bytes}",
                )

        total = sum(zi.file_size for zi in infos)
        if total > _max_extracted_bytes:
            raise ZipBombError(
                f"total uncompressed {total} bytes "
                f"> {_max_extracted_bytes}",
            )

        # Member-count cap applies to supported per-decl files only —
        # garbage like .DS_Store shouldn't push the user over the limit.
        n_supported = sum(
            1 for zi in infos if is_supported_filename(zi.filename)
        )
        if n_supported > _max_members:
            raise ZipTooManyMembersError(
                f"{n_supported} per-declaration files in ZIP, "
                f"max {_max_members}",
            )


# ─── extract_to_staging ────────────────────────────────────────────────


def _new_staging_id() -> str:
    return f"{_STAGING_PREFIX}{uuid.uuid4()}"


def extract_to_staging(
    zip_bytes: bytes,
    *,
    staging_root: Path = STAGING_ROOT,
) -> ExtractResult:
    """Validate + extract supported members into a fresh staging dir.

    Members that don't match the per-declaration filename pattern are
    skipped (counted in `ignored_non_pattern`). Directory components in
    member names are stripped: every file lands directly under the
    staging dir's root.
    """
    validate_zip(zip_bytes)

    staging_root.mkdir(parents=True, exist_ok=True)
    staging_id = _new_staging_id()
    staging_path = staging_root / staging_id
    staging_path.mkdir()

    try:
        with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
            infos = [zi for zi in zf.infolist() if not zi.is_dir()]
            total = len(infos)
            ignored = 0
            extracted = 0
            for zi in infos:
                basename = Path(zi.filename).name
                if not is_supported_filename(basename):
                    ignored += 1
                    continue
                dest = staging_path / basename
                with zf.open(zi) as src, dest.open("wb") as out:
                    shutil.copyfileobj(src, out)
                extracted += 1
    except Exception:
        # Make sure half-extracted state doesn't survive failure.
        shutil.rmtree(staging_path, ignore_errors=True)
        raise

    return ExtractResult(
        staging_id=staging_id,
        staging_path=staging_path,
        total_in_zip=total,
        ignored_non_pattern=ignored,
        extracted=extracted,
    )


# ─── parse + dedup ─────────────────────────────────────────────────────


def parse_staged_files(
    staging_path: Path,
    *,
    validate_content: bool = True,
) -> list[StagedFile]:
    """Read every file in the staging dir and classify it.

    Status outcomes:
      - `ok`           parse + content cross-validate succeed
      - `mismatch`     filename decl_no ≠ XLS content decl_no
      - `parse_error`  file unreadable / no decl_no / filename pattern bad
    `duplicate` is set later by `annotate_dedup_status`.
    """
    out: list[StagedFile] = []
    for fp in sorted(staging_path.iterdir()):
        if not fp.is_file():
            continue
        content = fp.read_bytes()
        sha = sha256_bytes(content)
        size = len(content)
        try:
            info = parse_declaration_file(
                fp.name, content, validate_content=validate_content,
            )
        except DeclarationFileError as exc:
            # Mismatch (filename vs content) and other parse failures
            # both skip ingest at commit, but the preview UI groups them
            # separately. Use the exception subclass so the split survives
            # any rewording of the parser's error message.
            status = (
                "mismatch"
                if isinstance(exc, DeclarationFileMismatchError)
                else "parse_error"
            )
            # When we can still recover the filename's decl_no, surface
            # it — operator can spot the wrong filename.
            try:
                decl_no, kind = parse_filename(fp.name)
            except DeclarationFileError:
                decl_no, kind = None, None
            out.append(StagedFile(
                name=fp.name, size_bytes=size, sha256=sha,
                declaration_no=decl_no, file_kind=kind,
                status=status, reason=str(exc),
            ))
            continue
        out.append(StagedFile(
            name=fp.name, size_bytes=size, sha256=sha,
            declaration_no=info.declaration_no, file_kind=info.file_kind,
            status="ok", reason=None,
        ))
    return out


def annotate_dedup_status(
    files: Iterable[StagedFile],
    *,
    client_id: str,
    direction: str,
) -> list[StagedFile]:
    """Flip `ok` rows to `duplicate` when (client, decl_no, direction,
    sha256) already exists in `hub.customs_declaration_files`."""
    files = list(files)
    candidates = [
        (f.declaration_no, f.sha256) for f in files
        if f.status == "ok" and f.declaration_no
    ]
    if not candidates:
        return files
    decl_nos = list({d for d, _ in candidates})
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            """
            select declaration_no, sha256
              from hub.customs_declaration_files
             where client_id = %s
               and direction = %s
               and declaration_no = any(%s)
            """,
            (client_id, direction, decl_nos),
        )
        existing = {(d, s) for d, s in cur.fetchall()}
    return [
        replace(f, status="duplicate")
        if f.status == "ok" and (f.declaration_no, f.sha256) in existing
        else f
        for f in files
    ]


# ─── commit ────────────────────────────────────────────────────────────


def commit_staged_files(
    staging_path: Path,
    *,
    client_id: str,
    direction: str,
    uploaded_by: str,
    validate_content: bool = True,
) -> CommitResult:
    """Re-parse staged files and insert any with status `ok` or
    `duplicate` (the latter no-ops via the store's idempotent insert).
    Mismatch + parse_error rows are skipped and counted.
    """
    files = parse_staged_files(
        staging_path, validate_content=validate_content,
    )
    inserted = 0
    deduped = 0
    mismatch = 0
    parse_err = 0
    store_err = 0
    errors: list[tuple[str, str]] = []
    for f in files:
        if f.status == "mismatch":
            mismatch += 1
            continue
        if f.status == "parse_error":
            parse_err += 1
            continue
        # ok → save + insert; DB unique constraint catches duplicates as deduped.
        fp = staging_path / f.name
        try:
            content = fp.read_bytes()
            stored = save_upload(
                content,
                filename=f.name, module="customs_declarations",
                client_id=client_id,
            )
            _, created = insert_declaration_file(
                client_id=client_id,
                declaration_no=f.declaration_no,
                direction=direction,
                file_kind=f.file_kind or "xls",
                backend_key=stored.path,
                original_filename=f.name,
                sha256=f.sha256,
                size_bytes=stored.size_bytes,
                uploaded_by=uploaded_by,
            )
            if created:
                inserted += 1
            else:
                deduped += 1
        except Exception as exc:
            store_err += 1
            errors.append((f.name, f"{type(exc).__name__}: {exc}"))
    return CommitResult(
        inserted=inserted, deduped=deduped,
        mismatch_skipped=mismatch, parse_error_skipped=parse_err,
        store_errors=store_err, errors=errors,
    )


# ─── staging hygiene ───────────────────────────────────────────────────


def get_staging_path(
    staging_id: str,
    *,
    staging_root: Path = STAGING_ROOT,
) -> Path | None:
    """Resolve a staging_id to its dir, or None if invalid / missing.

    Validates the ID against a strict `zip-<uuid>` shape — defence against
    `..` or absolute paths smuggled through URL params.
    """
    if not _STAGING_ID_RE.match(staging_id):
        return None
    path = staging_root / staging_id
    if not path.exists() or not path.is_dir():
        return None
    return path


def cancel_staging(
    staging_id: str,
    *,
    staging_root: Path = STAGING_ROOT,
) -> bool:
    """Remove the staging dir for `staging_id`. Returns True if removed."""
    path = get_staging_path(staging_id, staging_root=staging_root)
    if path is None:
        return False
    shutil.rmtree(path, ignore_errors=True)
    return True


def reap_expired_staging(
    *,
    staging_root: Path = STAGING_ROOT,
    ttl_seconds: int = STAGING_TTL_SECONDS,
) -> int:
    """Remove every staging dir older than `ttl_seconds`.

    Only directories matching the `zip-<uuid>` shape are considered —
    loose files or unrelated subdirs in the root are left untouched.
    """
    if not staging_root.exists():
        return 0
    cutoff = time.time() - ttl_seconds
    removed = 0
    for child in staging_root.iterdir():
        if not child.is_dir():
            continue
        if not _STAGING_ID_RE.match(child.name):
            continue
        try:
            mtime = child.stat().st_mtime
        except OSError:
            continue
        if mtime < cutoff:
            shutil.rmtree(child, ignore_errors=True)
            removed += 1
    return removed
