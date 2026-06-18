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

import concurrent.futures
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

# Bounded parallel render of cache-misses. soffice is process-per-call and
# already hermetic (unique -env:UserInstallation), so concurrent calls are
# safe. Only parallelize when misses exceed _RENDER_MIN_CHUNK, else one
# cold-start-amortized batch is cheaper than many short ones.
_RENDER_POOL = max(1, int(os.environ.get("DATA_HUB_RENDER_POOL", "4")))
_RENDER_MIN_CHUNK = max(1, int(os.environ.get("DATA_HUB_RENDER_MIN_CHUNK", "8")))

# Compact profile identity — surfaced via X-Pdf-Quality so CO/ops can see
# which reduction produced a file. `quality=compact` is LOSSLESS object
# dedup + content-stream recompression (see the compact section below).
COMPACT_VERSION = "pypdf-dedup-1"

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


def _plan_chunk_count(n: int) -> int:
    """How many concurrent soffice batches to use for `n` blobs."""
    if n <= _RENDER_MIN_CHUNK or _RENDER_POOL <= 1:
        return 1
    return min(_RENDER_POOL, (n + _RENDER_MIN_CHUNK - 1) // _RENDER_MIN_CHUNK)


def render_many_xls_to_pdf(blobs: list[bytes]) -> list[bytes | None]:
    """Render `.xls` blobs to PDF, aligned list (None where a blob
    failed). Splits the work across a bounded pool of concurrent soffice
    processes; each chunk is still a single batched invocation so cold
    start is amortized within the chunk. A chunk whose soffice cannot run
    at all yields None for its blobs (logged) rather than failing the
    whole set — matching the single-batch behaviour."""
    if not blobs:
        return []
    n = len(blobs)
    nchunks = _plan_chunk_count(n)
    if nchunks <= 1:
        try:
            return _convert_batch([(b, "xls") for b in blobs])
        except RenderError as exc:
            logger.warning("declaration render batch failed: %s", exc)
            return [None] * n

    size = (n + nchunks - 1) // nchunks
    ranges = [(i, min(i + size, n)) for i in range(0, n, size)]
    results: list[bytes | None] = [None] * n

    def _work(rng: tuple[int, int]) -> tuple[tuple[int, int], list[bytes | None]]:
        lo, hi = rng
        try:
            out = _convert_batch([(blobs[i], "xls") for i in range(lo, hi)])
        except RenderError as exc:
            logger.warning("declaration render chunk [%d:%d] failed: %s",
                           lo, hi, exc)
            out = [None] * (hi - lo)
        return rng, out

    with concurrent.futures.ThreadPoolExecutor(max_workers=nchunks) as ex:
        for (lo, hi), out in ex.map(_work, ranges):
            for j, pdf in enumerate(out):
                results[lo + j] = pdf
    return results


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


@dataclass
class RenderStats:
    """Counts for the X-Render-CacheHits/Misses headers. A `hit` is an
    `.xls` served from the render cache; a `miss` is one we (re)rendered.
    `pdf` passthroughs and absent blobs count as neither."""
    cache_hits: int = 0
    cache_misses: int = 0


def ensure_pdf_for_file(f: DeclarationFile, backend: FileBackend) -> bytes | None:
    """Resolve one declaration file to PDF bytes, or None when it can't
    contribute pages (unsupported kind, missing blob, or render failed).

    `pdf` files pass through unchanged; `xls`/`xlsx` are rendered via
    soffice and cached by source sha256."""
    return ensure_pdfs([f], backend).get(f.id)


def ensure_pdfs(
    files: list[DeclarationFile], backend: FileBackend,
    stats: RenderStats | None = None,
) -> dict[int, bytes | None]:
    """Resolve many files to PDF bytes, rendering `.xls` cache misses in a
    bounded pool of concurrent soffice invocations. Returns
    {file_id: pdf|None}.

    None means the file contributes no pages (unsupported kind, source
    blob absent from storage, or soffice failed for it). When `stats` is
    given, cache hit/miss counts are accumulated into it."""
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
            if stats is not None:
                stats.cache_hits += 1
            continue
        to_render.append((f, src, sha))

    if to_render:
        if stats is not None:
            stats.cache_misses += len(to_render)
        rendered = render_many_xls_to_pdf([t[1] for t in to_render])
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


# ── compact (lossless size reduction) ───────────────────────────────
#
# The declarations are ECUS print forms rendered from `.xls` — pure vector
# (text + table grid), no embedded raster scans (verified on real Johnson
# data: 0 images, ~5.7 KB/page; the 20-50 MB merged dossiers are driven by
# page COUNT, not images). So image downsampling buys nothing here, and
# ghostscript `/ebook` actually *inflates* this content (~111%). The win
# that DOES exist is lossless: concatenating N separately-rendered
# declarations duplicates the embedded font programs (e.g. one font seen
# 443× across 25 declarations), so merging byte-identical objects +
# recompressing content streams trims ~9% with zero quality loss. That is
# what `quality=compact` does. (For Ecosys's ~2 MB cap the real lever is
# `max_part_bytes` split, not compact — compact alone cannot bridge 32 MB
# → 2 MB.)


def _apply_dedup(writer) -> None:
    """In-place lossless reduction on a PdfWriter: recompress page content
    streams and merge byte-identical indirect objects (shared fonts across
    concatenated declarations). No rasterization, no quality loss."""
    for page in writer.pages:
        try:
            page.compress_content_streams()
        except Exception as exc:  # one bad page must not abort the merge
            logger.debug("compress_content_streams skipped a page: %s", exc)
    try:
        writer.compress_identical_objects()
    except Exception as exc:
        logger.warning("compress_identical_objects failed: %s", exc)


def compact_pdf_bytes(pdf: bytes) -> bytes:
    """Lossless-compact a PDF in memory (per-declaration split unit).
    Returns the smaller of compacted vs input, always a valid PDF."""
    from pypdf import PdfReader, PdfWriter

    try:
        writer = PdfWriter()
        writer.append(PdfReader(BytesIO(pdf)))
        _apply_dedup(writer)
        buf = BytesIO()
        writer.write(buf)
        out = buf.getvalue()
    except Exception as exc:
        logger.warning("pdf compact failed (%s); keeping original", exc)
        return pdf
    return out if len(out) < len(pdf) else pdf


# ── merge ───────────────────────────────────────────────────────────


@dataclass
class MergeResult:
    path: Path              # temp file the caller streams then cleans up
    media_type: str         # application/pdf | application/zip
    requested: int
    included: int           # declarations contributing ≥1 page
    missing_nos: list[str]  # requested-order; declarations with no pages
    is_info_page: bool
    cache_hits: int
    cache_misses: int
    pdf_bytes: int          # single PDF size, or sum of part sizes (zip)
    parts: int              # 1 for a single PDF; N for a zip of parts
    oversize_nos: list[str]  # declarations that alone exceed max_part_bytes


def _concat_file_pdfs(blobs: list[bytes | None]) -> tuple[bytes, int]:
    """Concatenate already-rendered PDF blobs into one, skipping None /
    corrupt sources. Returns (pdf_bytes, page_count); (b"", 0) when none
    contributed a page. pypdf merges into a single header/xref, so the
    result is never larger than the sum of the inputs."""
    from pypdf import PdfReader, PdfWriter

    writer = PdfWriter()
    n = 0
    for b in blobs:
        if not b:
            continue
        try:
            reader = PdfReader(BytesIO(b))
            for page in reader.pages:
                writer.add_page(page)
            n += len(reader.pages)
        except Exception as exc:  # corrupt source PDF — skip, don't fail
            logger.warning("concat skipped a source pdf: %s", exc)
    if n == 0:
        return b"", 0
    buf = BytesIO()
    writer.write(buf)
    return buf.getvalue(), n


def _compact_many(pdfs: list[bytes]) -> list[bytes]:
    """Lossless-compact each PDF across a bounded pool (same size as the
    render pool). Aligned list; each entry is the smaller of compacted vs
    input (never larger, always a valid PDF)."""
    if not pdfs:
        return []
    if len(pdfs) == 1 or _RENDER_POOL <= 1:
        return [compact_pdf_bytes(p) for p in pdfs]
    workers = min(_RENDER_POOL, len(pdfs))
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as ex:
        return list(ex.map(compact_pdf_bytes, pdfs))


def _pack_parts(
    units: list[tuple[str, bytes]], cap: int,
) -> tuple[list[list[tuple[str, bytes]]], set[str]]:
    """Greedily pack per-declaration units into parts ≤ `cap`, splitting
    only on declaration boundaries, in input (declaration_no) order. A
    unit that alone exceeds `cap` gets its own part and is flagged
    oversize. Packing by Σ unit bytes is safe because `_concat_file_pdfs`
    never exceeds that sum."""
    parts: list[list[tuple[str, bytes]]] = []
    oversize: set[str] = set()
    current: list[tuple[str, bytes]] = []
    current_bytes = 0
    for decl, unit in units:
        size = len(unit)
        if size > cap:
            if current:
                parts.append(current)
                current, current_bytes = [], 0
            parts.append([(decl, unit)])
            oversize.add(decl)
            continue
        if current and current_bytes + size > cap:
            parts.append(current)
            current, current_bytes = [], 0
        current.append((decl, unit))
        current_bytes += size
    if current:
        parts.append(current)
    return parts, oversize


def _ordered_files(
    decl_order: list[str], files_by_decl: dict[str, list[DeclarationFile]],
) -> list[tuple[str, DeclarationFile]]:
    ordered: list[tuple[str, DeclarationFile]] = []
    for decl in decl_order:
        for f in sorted(
            files_by_decl.get(decl, []),
            key=lambda x: ((x.original_filename or ""), x.id),
        ):
            ordered.append((decl, f))
    return ordered


def build_merged_pdf(
    *,
    requested: list[str],
    decl_order: list[str],
    files_by_decl: dict[str, list[DeclarationFile]],
    backend: FileBackend,
    dest_dir: Path,
    quality: str = "print",
    max_part_bytes: int | None = None,
    part_stem: str = "declarations",
) -> MergeResult:
    """Merge every declaration's rendered pages in `decl_order` (within a
    declaration, files by `original_filename`). Declarations producing no
    pages are skipped and listed in `missing_nos`. Zero included → a
    single info-page PDF (never empty/corrupt).

    `quality="print"` (default) is lossless and, with `max_part_bytes`
    unset, produces a byte-for-byte identical PDF to the original
    contract. `quality="compact"` applies lossless object dedup +
    content-stream recompression (see `_apply_dedup`). `max_part_bytes`
    (when set) returns a `parts.zip` of declaration-boundary parts each ≤
    the cap (see `_pack_parts`)."""
    from pypdf import PdfReader, PdfWriter

    ordered = _ordered_files(decl_order, files_by_decl)
    stats = RenderStats()
    pdf_by_file = ensure_pdfs([f for _, f in ordered], backend, stats)

    def _result(**kw) -> MergeResult:
        kw.setdefault("requested", len(requested))
        kw.setdefault("cache_hits", stats.cache_hits)
        kw.setdefault("cache_misses", stats.cache_misses)
        kw.setdefault("oversize_nos", [])
        return MergeResult(**kw)

    # ── single-PDF path (max_part_bytes unset) ─────────────────────────
    if max_part_bytes is None:
        # Identical merge to the original contract: one writer, pages in
        # global order. print writes that merge byte-for-byte unchanged;
        # compact dedups it losslessly (guarded ≤ print).
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
            return _result(
                path=dest, media_type="application/pdf", included=0,
                missing_nos=missing_nos, is_info_page=True,
                pdf_bytes=dest.stat().st_size, parts=1,
            )

        buf = BytesIO()
        writer.write(buf)
        body = buf.getvalue()  # print bytes (identical to the original contract)
        if quality == "compact":
            body = compact_pdf_bytes(body)  # guarded: never larger than print
        dest.write_bytes(body)
        return _result(
            path=dest, media_type="application/pdf", included=len(included),
            missing_nos=missing_nos, is_info_page=False,
            pdf_bytes=len(body), parts=1,
        )

    # ── split-capable path (max_part_bytes set) ────────────────────────
    # Build one PDF per declaration (the atomic split unit), compacting each
    # in parallel when requested. The units serve BOTH the "fits in one
    # part" single-PDF case and the packed-zip case — so no throwaway
    # whole-document compaction is done.
    decl_units: list[tuple[str, bytes]] = []
    for decl in decl_order:
        files = sorted(
            files_by_decl.get(decl, []),
            key=lambda x: ((x.original_filename or ""), x.id),
        )
        unit, npages = _concat_file_pdfs([pdf_by_file.get(f.id) for f in files])
        if npages > 0:
            decl_units.append((decl, unit))

    included = [d for d, _ in decl_units]  # already in decl_order
    missing_nos = [d for d in requested if d not in set(included)]

    if not included:
        # Nothing to split → single info-page PDF (never an empty zip).
        dest = dest_dir / "merged.pdf"
        dest.write_bytes(info_page_pdf())
        return _result(
            path=dest, media_type="application/pdf", included=0,
            missing_nos=missing_nos, is_info_page=True,
            pdf_bytes=dest.stat().st_size, parts=1,
        )

    if quality == "compact":
        compacted = _compact_many([u for _, u in decl_units])
        decl_units = [(d, c) for (d, _u), c in zip(decl_units, compacted)]

    # Single PDF unless the merged result would exceed the cap.
    single_bytes, _ = _concat_file_pdfs([u for _, u in decl_units])
    if len(single_bytes) <= max_part_bytes:
        dest = dest_dir / "merged.pdf"
        dest.write_bytes(single_bytes)
        return _result(
            path=dest, media_type="application/pdf", included=len(included),
            missing_nos=missing_nos, is_info_page=False,
            pdf_bytes=len(single_bytes), parts=1,
        )

    parts, oversize = _pack_parts(decl_units, max_part_bytes)

    import zipfile

    zip_path = dest_dir / "parts.zip"
    total = 0
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for i, part in enumerate(parts, 1):
            part_bytes, _ = _concat_file_pdfs([b for _, b in part])
            zf.writestr(f"{part_stem}-part-{i:03d}.pdf", part_bytes)
            total += len(part_bytes)

    return _result(
        path=zip_path, media_type="application/zip", included=len(included),
        missing_nos=missing_nos, is_info_page=False, pdf_bytes=total,
        parts=len(parts),
        oversize_nos=[d for d in decl_order if d in oversize],
    )
