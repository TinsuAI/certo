"""Render + merge customs declaration files into one print-standard PDF.

The stored per-declaration `.xls` is NOT a raw data export — it is the
official ECUS/VNACCS print form ("tờ khai hàng hóa nhập/xuất khẩu")
laid out as a spreadsheet (sheet `TKN`/`TKX` carries the `<IMP>`/`<EXP>`
watermark, the page `X/N` marker, and the government grid). Printing
that sheet IS the "PDF chuẩn" the operator merges by hand today, so the
faithful renderer is LibreOffice headless converting the stored `.xls`
to PDF — it reproduces the exact layout (verified against the official
"… GHEP.pdf" sample). See `.ai/features/2026-06-06-declarations-merged-pdf/`.

Strategy (per 2026-06-06 decision): pre-render each declaration's PDF
and cache it content-addressed by the source `.xls` sha256; the merge
endpoint then just concatenates cached PDFs in order. A cache miss
(file uploaded before backfill, or a prior render failure) renders
on-the-fly at request time so correctness never depends on a warm
cache. Bump `RENDER_VERSION` when the renderer output changes — it is
part of the cache key, so old entries are transparently superseded.
"""
from __future__ import annotations

import logging
import os
import subprocess
import tempfile
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path

from app.storage import FileBackend, sha256_bytes
from app.stores.customs_declaration_files import DeclarationFile

logger = logging.getLogger("app.declarations_pdf")

# Bump when soffice version / convert flags change the rendered output
# so cached PDFs are invalidated (it is part of the cache key).
RENDER_VERSION = "soffice-1"

_SOFFICE_BIN = os.environ.get("DATA_HUB_SOFFICE_BIN", "soffice")
_SOFFICE_TIMEOUT = int(os.environ.get("DATA_HUB_SOFFICE_TIMEOUT", "180"))

_NO_FILES_MSG = "Không có tờ khai có file đính kèm để xuất bản PDF."


class RenderError(RuntimeError):
    """LibreOffice failed to produce a PDF for a source document."""


# ── soffice conversion ──────────────────────────────────────────────


def _convert_batch(sources: list[tuple[bytes, str]]) -> list[bytes | None]:
    """Convert each (blob, ext) source to PDF in ONE soffice invocation.

    Returns a list aligned with `sources`; an entry is None when that
    document failed to convert. Raises RenderError only when soffice
    could not run at all (binary missing / timeout / zero output).

    A unique `-env:UserInstallation` profile per call makes concurrent
    invocations safe (no shared profile lock) and keeps the call
    hermetic — nothing is written outside the temp dir.
    """
    if not sources:
        return []
    with tempfile.TemporaryDirectory(prefix="dh_render_") as td:
        tmp = Path(td)
        srcdir = tmp / "src"
        outdir = tmp / "out"
        srcdir.mkdir()
        outdir.mkdir()
        src_paths: list[Path] = []
        for i, (blob, ext) in enumerate(sources):
            p = srcdir / f"{i}.{ext}"
            p.write_bytes(blob)
            src_paths.append(p)
        profile_uri = (tmp / "profile").as_uri()
        cmd = [
            _SOFFICE_BIN, "--headless", "--nologo", "--nofirststartwizard",
            "--norestore", "--nolockcheck",
            f"-env:UserInstallation={profile_uri}",
            "--convert-to", "pdf", "--outdir", str(outdir),
            *[str(p) for p in src_paths],
        ]
        try:
            proc = subprocess.run(
                cmd, capture_output=True, timeout=_SOFFICE_TIMEOUT,
            )
        except FileNotFoundError as exc:
            raise RenderError(
                f"soffice binary not found: {_SOFFICE_BIN!r}"
            ) from exc
        except subprocess.TimeoutExpired as exc:
            raise RenderError("soffice conversion timed out") from exc

        out: list[bytes | None] = []
        for i in range(len(sources)):
            pdf_path = outdir / f"{i}.pdf"
            out.append(pdf_path.read_bytes() if pdf_path.exists() else None)
        if all(r is None for r in out):
            raise RenderError(
                f"soffice produced no output (rc={proc.returncode}): "
                f"{proc.stderr[:300]!r}"
            )
        return out


def render_xls_to_pdf(blob: bytes) -> bytes:
    """Render a single declaration `.xls` to the print-standard PDF.

    Raises RenderError on failure (caller decides skip vs propagate)."""
    result = _convert_batch([(blob, "xls")])[0]
    if result is None:
        raise RenderError("soffice produced no PDF for the .xls source")
    return result


def render_many_xls_to_pdf(blobs: list[bytes]) -> list[bytes | None]:
    """Batch-render `.xls` blobs in one soffice call (amortizes cold
    start). Aligned list; None where a particular blob failed."""
    return _convert_batch([(b, "xls") for b in blobs])


_INFO_PAGE_CACHE: dict[str, bytes] = {}


def info_page_pdf(message: str = _NO_FILES_MSG) -> bytes:
    """A single well-formed A4 page carrying `message` — used for the
    zero-match / all-missing response so CO never gets an empty or
    corrupt PDF. Cached in-process (message is effectively constant)."""
    cached = _INFO_PAGE_CACHE.get(message)
    if cached is not None:
        return cached
    pdf = _convert_batch([(_info_xlsx(message), "xlsx")])[0]
    if pdf is None:
        raise RenderError("soffice produced no PDF for the info page")
    _INFO_PAGE_CACHE[message] = pdf
    return pdf


def _info_xlsx(message: str) -> bytes:
    """A one-cell .xlsx carrying `message`, A4 portrait — reuses the
    proven xlsx→PDF soffice path for a Unicode-safe info page."""
    from openpyxl import Workbook

    wb = Workbook()
    ws = wb.active
    ws["B2"] = message
    ws.page_setup.orientation = "portrait"
    ws.page_setup.paperSize = 9  # A4
    buf = BytesIO()
    wb.save(buf)
    return buf.getvalue()


# ── content-addressed render cache ──────────────────────────────────


def _cache_key(sha256: str) -> str:
    return f"render_cache/declarations/{RENDER_VERSION}/{sha256}.pdf"


def get_cached_pdf(sha256: str, backend: FileBackend) -> bytes | None:
    try:
        return backend.get(_cache_key(sha256))
    except FileNotFoundError:
        return None


def put_cached_pdf(sha256: str, pdf: bytes, backend: FileBackend) -> None:
    backend.put(pdf, key=_cache_key(sha256))


def _is_pdf(f: DeclarationFile) -> bool:
    return f.file_kind == "pdf"


def _is_xls(f: DeclarationFile) -> bool:
    return f.file_kind in ("xls", "xlsx")


def ensure_pdf_for_file(f: DeclarationFile, backend: FileBackend) -> bytes | None:
    """Resolve one declaration file to PDF bytes, or None when it can't
    contribute pages (unsupported kind, missing blob, or render failed).

    `pdf` files pass through unchanged; `xls`/`xlsx` are rendered via
    soffice and cached by source sha256."""
    return ensure_pdfs([f], backend).get(f.id)


def ensure_pdfs(
    files: list[DeclarationFile], backend: FileBackend,
) -> dict[int, bytes | None]:
    """Resolve many files to PDF bytes, rendering all `.xls` cache
    misses in a SINGLE soffice invocation. Returns {file_id: pdf|None}.

    None means the file contributes no pages (unsupported kind, source
    blob absent from storage, or soffice failed for it)."""
    result: dict[int, bytes | None] = {}
    to_render: list[tuple[DeclarationFile, bytes, str]] = []
    for f in files:
        if not (_is_pdf(f) or _is_xls(f)):
            result[f.id] = None
            continue
        try:
            src = backend.get(f.backend_key)
        except FileNotFoundError:
            # Registered in metadata but blob absent — treat as missing.
            result[f.id] = None
            continue
        if _is_pdf(f):
            result[f.id] = src
            continue
        sha = f.sha256 or sha256_bytes(src)
        cached = get_cached_pdf(sha, backend)
        if cached is not None:
            result[f.id] = cached
            continue
        to_render.append((f, src, sha))

    if to_render:
        try:
            rendered = render_many_xls_to_pdf([t[1] for t in to_render])
        except RenderError as exc:
            logger.warning("declaration render batch failed: %s", exc)
            rendered = [None] * len(to_render)
        for (f, _src, sha), pdf in zip(to_render, rendered):
            if pdf is None:
                logger.warning(
                    "render failed for file id=%s (%s)",
                    f.id, f.original_filename,
                )
                result[f.id] = None
            else:
                put_cached_pdf(sha, pdf, backend)
                result[f.id] = pdf
    return result


# ── merge ───────────────────────────────────────────────────────────


@dataclass
class MergeResult:
    pdf_path: Path          # temp file the caller streams then cleans up
    requested: int
    included: int           # declarations contributing ≥1 page
    missing_nos: list[str]  # requested-order; declarations with no pages
    is_info_page: bool


def build_merged_pdf(
    *,
    requested: list[str],
    decl_order: list[str],
    files_by_decl: dict[str, list[DeclarationFile]],
    backend: FileBackend,
    dest_dir: Path,
) -> MergeResult:
    """Merge every declaration's rendered pages into one PDF at
    `dest_dir/merged.pdf`, in `decl_order`; within a declaration, files
    are ordered by `original_filename`. Declarations producing no pages
    are skipped from the body and listed in `missing_nos`.

    Zero included → a single info-page PDF (never empty/corrupt)."""
    from pypdf import PdfReader, PdfWriter

    ordered: list[tuple[str, DeclarationFile]] = []
    for decl in decl_order:
        for f in sorted(
            files_by_decl.get(decl, []),
            key=lambda x: ((x.original_filename or ""), x.id),
        ):
            ordered.append((decl, f))

    pdf_by_file = ensure_pdfs([f for _, f in ordered], backend)

    writer = PdfWriter()
    pages_by_decl: dict[str, int] = {}
    for decl, f in ordered:
        pdf = pdf_by_file.get(f.id)
        if not pdf:
            continue
        try:
            reader = PdfReader(BytesIO(pdf))
            for page in reader.pages:
                writer.add_page(page)
            pages_by_decl[decl] = pages_by_decl.get(decl, 0) + len(reader.pages)
        except Exception as exc:  # corrupt source PDF — skip, don't fail
            logger.warning("merge skipped file id=%s: %s", f.id, exc)

    included = [d for d in decl_order if pages_by_decl.get(d, 0) > 0]
    missing_nos = [d for d in requested if d not in set(included)]
    dest = dest_dir / "merged.pdf"

    if not included:
        dest.write_bytes(info_page_pdf())
        return MergeResult(dest, len(requested), 0, missing_nos, True)

    with open(dest, "wb") as fh:
        writer.write(fh)
    return MergeResult(dest, len(requested), len(included), missing_nos, False)
