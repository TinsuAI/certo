"""Shared upload-mapping-preview-confirm flow used by all 4 modules.

Replaces the older per-module copy-paste of: cache lookup → rigid parse
→ LLM proposal → preview → confirm. Adds a new mandatory step on cache
miss: an interactive **mapping page** where staff confirms (or edits)
the column→logical-field map and chooses the header row before parse
runs. Skipped rows surface in preview with inline-edit affordances.

Module-agnostic. Each upload route configures a `ModuleConfig` and
delegates the upload / mapping / parse / preview / confirm / reject
steps to the helpers in this module. Module-specific UI lives in the
per-module Jinja template, which extends `clients/_upload_preview.html`
and fills the `{% block module_summary %}` (and BCCT-only
`{% block diff_view %}`) slots.

Note on existing flow: this module reuses `_llm_fallback.py` helpers
underneath (cache lookup, LLM proposal). Slice 5 will retire
`_llm_fallback.py` once all 4 modules have migrated.
"""
from __future__ import annotations

import json
import logging
import secrets
from dataclasses import dataclass, field
from typing import Any, Callable, Iterable

from fastapi import HTTPException

from app import llm
from app.database import connect
from app.parsers._excel import (
    compute_file_signature,
    header_row,
    load_xlsx,
)
from app.stores.column_aliases import resolved_aliases
from app.routes._llm_fallback import (
    cache_confirmed_mapping,
    headers_per_sheet,
    lookup_cached_mapping,
    record_mapping_use,
)

logger = logging.getLogger(__name__)

PREVIEW_SAMPLE_ROWS = 20
RAW_SHEET_PREVIEW_ROWS = 10
MAPPING_HEADER_SCAN = 15  # how many rows to show in header-row picker


# ── Module configuration ──────────────────────────────────────────────────

@dataclass
class ModuleConfig:
    """Per-module knobs that the shared flow needs.

    Each route file constructs one of these and hands it to the helpers
    below. Knobs are kept small + well-named — adding a 5th module later
    must not require new dataclass fields, only filling these in.
    """

    # Routing
    name: str                       # 'catalog' | 'bqd' | 'bom' | 'bcct'
    upload_pending_module: str      # value stored in upload_pending.module CHECK
    save_upload_module: str         # value passed to save_upload(module=…)
    fallback_filename: str          # used when client uploads with no filename
    list_route: Callable[[str], str]  # fn(client_id) -> "/clients/{c}/<m>"
    preview_template: str           # 'clients/catalog_preview.html'

    # Parser + ingest
    parser_fn: Callable[..., tuple[list[dict], list[dict]]]
    parser_error: type[Exception]
    summarize_fn: Callable[[list[dict]], dict]
    ingest_fn: Callable[..., int]   # signature: (cur, *, client_id, rows, upload_id, **extra)

    # Mapping form
    logical_fields: tuple[str, ...]
    min_identifier_fields: frozenset[str] = frozenset()
    # `min_identifier_fields`: at-least-one-of these logical fields must be
    # mapped (catalog uses this — customs_code OR internal_code).
    required_mapped_fields: frozenset[str] = frozenset()
    # `required_mapped_fields`: ALL of these logical fields must be mapped
    # at form time (BQD uses this — internal_code AND customs_code).
    extra_required_fields_default: tuple[str, ...] = ()

    # Optional knobs
    fallback_default_filename: str = ""
    extra_pending_kwargs_fn: Callable[[Any], dict] | None = None
    # ↑ Optional fn(form_data) -> {} to merge into upload_pending.diff_summary
    #   when stashing. e.g. catalog uses it to capture provenance_kind.

    def list_url(self, client_id: str) -> str:
        return self.list_route(client_id)


# ── Step 1: upload submit (POST /upload) ──────────────────────────────────

def upload_initial_dispatch(
    *,
    client_id: str,
    blob: bytes,
    upload_id: str,
    cfg: ModuleConfig,
    extra_pending: dict[str, Any] | None = None,
) -> tuple[str | None, str | None, str]:
    """Decide whether to skip the mapping page (cache hit) or render it.

    Returns `(redirect_url, _unused, mode)` where:
      - redirect_url: where to 303 the client.
      - mode: 'cache_hit_preview' (parsed straight to preview) | 'mapping_page'.

    Cache-hit fast path: if a confirmed mapping exists for this
    (client, module, file_signature) AND parses successfully, we stash
    pending immediately and skip the mapping UI. On parse failure
    (column dropped from new file), fall through to mapping page.
    """
    extra = dict(extra_pending or {})

    # Compute signature + look up cached mapping (best-effort).
    file_signature: str | None = None
    cached_mapping: dict | None = None
    try:
        sheets = headers_per_sheet(blob)
        if sheets:
            file_signature = compute_file_signature(
                client_id=client_id, module=cfg.name, headers_per_sheet=sheets,
            )
            cached_mapping = lookup_cached_mapping(
                client_id=client_id, module=cfg.name, file_signature=file_signature,
            )
    except Exception:  # noqa: BLE001 — best-effort
        logger.exception("cache lookup failed; falling through to mapping page")

    if cached_mapping is not None:
        try:
            rows, skipped = cfg.parser_fn(blob, mapping_override=cached_mapping)
        except cfg.parser_error as e:
            logger.info("cached mapping failed re-parse; routing to mapping page: %s", e)
        else:
            record_mapping_use(
                client_id=client_id, module=cfg.name, file_signature=file_signature,
            )
            pending_id = _stash_pending(
                client_id=client_id, upload_id=upload_id,
                module=cfg.upload_pending_module,
                parsed=rows, skipped=skipped,
                used_mapping=cached_mapping,
                file_signature=file_signature,
                proposed_by="cached",
                extra=extra,
            )
            _mark_pending_preview(upload_id, len(rows))
            return f"{cfg.list_url(client_id)}/preview/{pending_id}", None, "cache_hit_preview"

    # Cache miss / cached failed → mapping page.
    _stash_unmapped(
        upload_id=upload_id, file_signature=file_signature, extra=extra,
    )
    return f"{cfg.list_url(client_id)}/upload/mapping/{upload_id}", None, "mapping_page"


# ── Step 2: mapping page GET ─────────────────────────────────────────────

def render_mapping_page_context(
    *,
    client_id: str,
    upload_id: str,
    cfg: ModuleConfig,
) -> dict:
    """Build the template context for the mapping page.

    Loads the upload blob from disk, surfaces:
      - first 10 rows of the first plausible sheet (raw, pre-parse)
      - candidate header rows (rows 1-15 with non-empty cell counts)
      - default header row pick (current heuristic)
      - rigid auto-match per column (no LLM call here; LLM is opt-in via
        a button on the page → POST /mapping/llm_suggest)
      - the cached `unmapped` extras (e.g., file_signature) so the POST
        handler can reach them after staff submits

    Does NOT call the LLM. The mapping page shows a button "Apply LLM
    suggestion" which POSTs to a separate endpoint.
    """
    blob, file_signature, extra = _load_unmapped(upload_id, module=cfg.upload_pending_module)
    return _build_mapping_context(
        client_id=client_id, upload_id=upload_id, cfg=cfg,
        blob=blob, file_signature=file_signature, extra=extra,
        rigid_only=True,
    )


def render_mapping_page_with_llm_suggestion(
    *,
    client_id: str,
    upload_id: str,
    cfg: ModuleConfig,
) -> dict:
    """Same as render_mapping_page_context but pre-fills with LLM proposal.

    Called from POST /mapping/llm_suggest. On LLM unavailable / proposal
    error, the context still renders with a flash error so staff can
    fall back to manual.
    """
    blob, file_signature, extra = _load_unmapped(upload_id, module=cfg.upload_pending_module)
    ctx = _build_mapping_context(
        client_id=client_id, upload_id=upload_id, cfg=cfg,
        blob=blob, file_signature=file_signature, extra=extra,
        rigid_only=True,
    )

    sample_headers, sample_rows = _sample_for_llm(blob)
    if not sample_headers:
        ctx["llm_error"] = "Không đọc được header để gọi LLM."
        return ctx

    try:
        proposed = llm.propose_header_mapping(
            client_id=client_id, module=cfg.name,
            headers=sample_headers, sample_rows=sample_rows,
        )
    except llm.LLMUnavailable as e:
        ctx["llm_error"] = f"LLM tắt hoặc hết quota: {e}"
        return ctx
    except llm.LLMProposalError as e:
        ctx["llm_error"] = f"LLM trả lời lỗi: {e}"
        return ctx

    # Fill ONLY the columns the rigid layer couldn't resolve — never
    # override a confident rigid match (LLM is for genuinely unknown
    # headers). LLM abstentions (omitted headers) stay unmapped → the
    # form flags them "cần chọn".
    _merge_llm_into_unresolved(ctx["column_map"], proposed)
    ctx["llm_applied"] = True
    return ctx


def _merge_llm_into_unresolved(column_map: list[dict], proposed: dict) -> None:
    """Mutate `column_map`, setting `proposed` from the LLM result only for
    columns the rigid match left empty. Rigid matches are authoritative."""
    proposed_lower = {str(k).strip().lower(): v for k, v in proposed.items()}
    for col in column_map:
        if col.get("proposed"):
            continue  # rigid already resolved this header — keep it
        norm = (col.get("header") or "").strip().lower()
        if norm in proposed_lower:
            col["proposed"] = proposed_lower[norm]


# ── Step 3: parse with overrides + stash (POST /mapping/parse) ───────────

def parse_with_overrides_and_stash(
    *,
    client_id: str,
    upload_id: str,
    user_id: str | None,
    column_map: dict[str, str],
    header_row_override: int | None,
    extra_required_fields: list[str] | None,
    proposed_by: str,
    cfg: ModuleConfig,
    extra_pending: dict[str, Any] | None = None,
) -> str:
    """Parse with the staff-confirmed mapping, stash pending, return pending_id.

    Validates the identifier rule before parsing — if the mapping doesn't
    map at least one of `cfg.min_identifier_fields`, raises HTTPException
    so the route surfaces "must map at least one of customs_code/internal_code"
    back to the form.
    """
    blob, file_signature, prev_extra = _load_unmapped(
        upload_id, module=cfg.upload_pending_module,
    )

    # Identifier rules (defence in depth — UI form should already enforce).
    mapped_logical = {v for v in column_map.values() if v and v != "ignore"}
    if cfg.min_identifier_fields:
        if not (mapped_logical & cfg.min_identifier_fields):
            raise HTTPException(
                400,
                "Cần map ít nhất một cột là " +
                " hoặc ".join(sorted(cfg.min_identifier_fields)),
            )
    if cfg.required_mapped_fields:
        missing = cfg.required_mapped_fields - mapped_logical
        if missing:
            raise HTTPException(
                400,
                "Thiếu mapping cho các trường bắt buộc: " +
                ", ".join(sorted(missing)),
            )

    try:
        rows, skipped = cfg.parser_fn(
            blob,
            mapping_override=column_map,
            header_row_override=header_row_override,
            extra_required_fields=extra_required_fields or list(cfg.extra_required_fields_default),
        )
    except cfg.parser_error as e:
        raise HTTPException(400, f"Parse error: {e}") from e

    extra = dict(prev_extra or {})
    extra.update(extra_pending or {})
    pending_id = _stash_pending(
        client_id=client_id, upload_id=upload_id,
        module=cfg.upload_pending_module,
        parsed=rows, skipped=skipped,
        used_mapping=column_map,
        file_signature=file_signature,
        proposed_by=proposed_by,
        extra=extra,
        header_row_override=header_row_override,
        extra_required_fields=extra_required_fields,
    )
    _mark_pending_preview(upload_id, len(rows))
    return pending_id


# ── Step 4: preview GET ───────────────────────────────────────────────────

def render_preview_context(
    *,
    client_id: str,
    pending_id: str,
    cfg: ModuleConfig,
) -> dict:
    """Build the template context for the preview page (shared chrome).

    Per-module summary lives in the route's wrapper template, which
    `{% extends "clients/_upload_preview.html" %}` and fills
    `{% block module_summary %}`.
    """
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                select parsed_rows, diff_summary, expires_at, created_at
                from hub.upload_pending
                where pending_id = %s and client_id = %s and module = %s
                """,
                (pending_id, client_id, cfg.upload_pending_module),
            )
            row = cur.fetchone()
    if not row:
        raise HTTPException(404, "Pending upload not found or expired")
    parsed_rows, diff_summary, expires_at, created_at = row
    diff_summary = diff_summary or {}
    skipped = diff_summary.get("skipped_rows", []) or []
    summary = cfg.summarize_fn(parsed_rows)
    return {
        "pending_id": pending_id,
        "summary": summary,
        "sample_rows": parsed_rows[:PREVIEW_SAMPLE_ROWS],
        "skipped_rows": skipped,
        "skipped_count": len(skipped),
        "diff_summary": diff_summary,
        "expires_at": expires_at,
        "created_at": created_at,
        # Convenience for the inline-edit UI in skipped rows section:
        "required_fields": list(diff_summary.get(
            "extra_required_fields", cfg.extra_required_fields_default,
        )) + list(cfg.min_identifier_fields),
    }


# ── Step 5: confirm POST ──────────────────────────────────────────────────

def confirm_pending(
    *,
    client_id: str,
    pending_id: str,
    user_id: str | None,
    cfg: ModuleConfig,
    included_skipped: list[dict] | None = None,
    ingest_extra: dict[str, Any] | None = None,
) -> int:
    """Apply ingest. Optionally promote staff-edited skipped rows.

    `included_skipped` is the list of skipped rows that staff toggled
    "include" for, with any inline-edit values merged in. The shared
    flow does the merge at the route layer (where Form() data is parsed)
    and passes the final list here; this function trusts that `included_skipped`
    rows have been validated against required fields by the form handler.

    Returns the count of rows ingested (rows + included_skipped).
    """
    with connect(user_id=user_id) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                delete from hub.upload_pending
                where pending_id = %s and client_id = %s and module = %s
                  and expires_at > now()
                returning parsed_rows, diff_summary, upload_id
                """,
                (pending_id, client_id, cfg.upload_pending_module),
            )
            row = cur.fetchone()
            if not row:
                raise HTTPException(404, "Pending upload not found or expired")
            parsed_rows, diff_summary, upload_id = row
            diff_summary = diff_summary or {}
            all_rows = list(parsed_rows or [])
            if included_skipped:
                all_rows.extend(included_skipped)

            n = cfg.ingest_fn(
                cur, client_id=client_id, rows=all_rows,
                upload_id=upload_id, **(ingest_extra or {}),
            )
            cur.execute(
                "update hub.file_uploads set parse_status='done', parsed_at=now() where upload_id=%s",
                (upload_id,),
            )

    # Persist confirmed mapping AFTER ingest succeeded — staff has now
    # validated the rows look correct.
    used_mapping = diff_summary.get("used_mapping")
    file_signature = diff_summary.get("file_signature")
    proposed_by = diff_summary.get("proposed_by")
    if used_mapping and file_signature and proposed_by in ("manual", "llm", "cached"):
        # 'cached' means we already had it; updating last_used_at is enough.
        # 'manual' / 'llm' are first-time confirmations.
        cache_proposed_by = "llm" if proposed_by == "llm" else "manual"
        cache_confirmed_mapping(
            client_id=client_id, module=cfg.name,
            file_signature=file_signature, mapping=used_mapping,
            headers=list(used_mapping.keys()),
            confirmed_by_user_id=user_id, proposed_by=cache_proposed_by,
        )
    return n


def reject_pending(
    *,
    client_id: str,
    pending_id: str,
    user_id: str | None,
    cfg: ModuleConfig,
) -> None:
    """Discard a pending upload. Marks file_uploads as 'rejected'."""
    with connect(user_id=user_id) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                delete from hub.upload_pending
                where pending_id = %s and client_id = %s and module = %s
                returning upload_id
                """,
                (pending_id, client_id, cfg.upload_pending_module),
            )
            row = cur.fetchone()
            if not row:
                raise HTTPException(404, "Pending upload not found or expired")
            (upload_id,) = row
            cur.execute(
                "update hub.file_uploads set parse_status='rejected', parsed_at=now() where upload_id=%s",
                (upload_id,),
            )


# ── Internals ─────────────────────────────────────────────────────────────

def _sample_for_llm(blob: bytes) -> tuple[list[str], list[list]]:
    """Return (headers, first 5 data rows) of the first plausible sheet."""
    try:
        wb = load_xlsx(blob)
    except Exception:  # noqa: BLE001
        return [], []
    for ws in wb.worksheets:
        hdr = header_row(ws, max_scan=20)
        if not hdr:
            continue
        header_idx, headers = hdr
        rows: list[list] = []
        for raw in ws.iter_rows(min_row=header_idx + 1, values_only=True):
            if all(c is None or (isinstance(c, str) and not c.strip()) for c in raw):
                continue
            rows.append(list(raw))
            if len(rows) >= 5:
                break
        return [h for h in headers if h], rows
    return [], []


def _build_mapping_context(
    *,
    client_id: str,
    upload_id: str,
    cfg: ModuleConfig,
    blob: bytes,
    file_signature: str | None,
    extra: dict[str, Any],
    rigid_only: bool,
) -> dict:
    """Common context builder for mapping page (with or without LLM)."""
    try:
        wb = load_xlsx(blob)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(400, f"Cannot open workbook: {e}") from e

    # Pick the first sheet with any non-empty header row.
    sheet_title = ""
    raw_rows: list[list[str]] = []
    candidate_header_rows: list[tuple[int, int]] = []  # (row_no, non_empty_count)
    default_header_row_no = 1
    headers: list[str] = []

    for ws in wb.worksheets:
        sheet_title = ws.title
        # Read up to MAPPING_HEADER_SCAN rows for the picker.
        scan: list[list[str]] = []
        for raw in ws.iter_rows(
            min_row=1, max_row=MAPPING_HEADER_SCAN, values_only=True,
        ):
            scan.append(["" if c is None else str(c).strip() for c in raw])
        if not scan:
            continue
        for r_idx, cells in enumerate(scan, start=1):
            n = sum(1 for c in cells if c)
            if n >= 2:
                candidate_header_rows.append((r_idx, n))
        # Default = current header_row() heuristic
        hdr = header_row(ws, aliases=getattr(cfg.parser_fn, "aliases", None))
        if hdr:
            default_header_row_no, headers = hdr
        elif candidate_header_rows:
            default_header_row_no = candidate_header_rows[0][0]
            headers = scan[default_header_row_no - 1]
        # Read up to RAW_SHEET_PREVIEW_ROWS data rows for the preview table.
        for raw in ws.iter_rows(
            min_row=1, max_row=default_header_row_no + RAW_SHEET_PREVIEW_ROWS,
            values_only=True,
        ):
            raw_rows.append(["" if c is None else str(c) for c in raw])
        break

    if not headers:
        raise HTTPException(
            400,
            "File không có sheet nào có header. Vui lòng kiểm tra lại.",
        )

    # Rigid auto-match for each header. Code ALIASES + this client's
    # enabled column-alias overrides (Phase 3), so local header variants
    # pre-fill without a code change.
    aliases_by_module = resolved_aliases(client_id, cfg.name)

    column_map: list[dict] = []
    for i, h in enumerate(headers):
        proposed = _rigid_match_header(h, aliases_by_module)
        column_map.append({
            "index": i,
            "header": h,
            "proposed": proposed,
        })

    return {
        "upload_id": upload_id,
        "module": cfg.name,
        "module_label": cfg.name.upper(),
        "sheet_title": sheet_title,
        "raw_rows": raw_rows,
        "candidate_header_rows": candidate_header_rows,
        "default_header_row_no": default_header_row_no,
        "column_map": column_map,
        "logical_fields": list(cfg.logical_fields),
        "min_identifier_fields": sorted(cfg.min_identifier_fields),
        "extra_required_fields_default": list(cfg.extra_required_fields_default),
        "file_signature": file_signature,
        "extra": extra,
        "post_url": f"{cfg.list_url(client_id)}/upload/mapping/{upload_id}/parse",
        "llm_suggest_url": f"{cfg.list_url(client_id)}/upload/mapping/{upload_id}/llm_suggest",
        "list_url": cfg.list_url(client_id),
        "client_id": client_id,
    }


def _module_aliases(module: str) -> dict[str, list[str]]:
    """Lazy import of the per-module ALIASES dict for rigid auto-match."""
    if module == "catalog":
        from app.parsers.materials import ALIASES
        return ALIASES
    if module == "bqd":
        from app.parsers.code_mappings import ALIASES
        return ALIASES
    if module == "bom":
        # manual_flat aliases live in the adapter module
        try:
            from app.parsers.bom_adapters.manual_flat import ALIASES  # type: ignore
            return ALIASES
        except Exception:  # noqa: BLE001
            return {}
    if module == "bcct":
        from app.parsers.bcct import ALIASES
        return ALIASES
    return {}


def _rigid_match_header(header: str, aliases: dict[str, list[str]]) -> str:
    """Return the logical field that this header text rigidly matches,
    or "" if no match. Same normalization rule as `index_headers`."""
    if not header:
        return ""
    norm = header.strip().lower()
    for field, alts in aliases.items():
        for alt in alts:
            if (alt or "").strip().lower() == norm:
                return field
    return ""


def try_auto_map(blob: bytes, cfg: "ModuleConfig",
                 client_id: str | None = None) -> dict[str, str] | None:
    """Phase 1: confident rigid auto-map.

    Returns a header→logical_field mapping when the rigid ALIAS match
    resolves the module's required fields with NO ambiguity (no logical
    field claimed by 2+ headers), so the caller can skip the manual
    mapping page and go straight to the preview. Returns None when not
    confident — caller shows the mapping page. The preview's diff +
    anomaly net stay the safety check (decision: skip even on first-ever
    upload when confident). Module-agnostic — driven by `cfg`. When
    `client_id` is given, the client's column-alias overrides (Phase 3)
    are layered on top of the code ALIASES.
    """
    try:
        wb = load_xlsx(blob)
    except Exception:  # noqa: BLE001 — best-effort; caller falls back
        return None
    aliases = (
        resolved_aliases(client_id, cfg.name) if client_id
        else _module_aliases(cfg.name)
    )
    headers: list[str] | None = None
    for ws in wb.worksheets:
        hdr = header_row(ws, aliases=aliases)
        if hdr:
            _, headers = hdr
            break
    if not headers:
        return None
    mapping: dict[str, str] = {}
    field_counts: dict[str, int] = {}
    for h in headers:
        if not h:
            continue
        fld = _rigid_match_header(h, aliases)
        if fld:
            mapping[h] = fld
            field_counts[fld] = field_counts.get(fld, 0) + 1
    mapped = set(mapping.values())
    # All required fields must resolve.
    if cfg.required_mapped_fields - mapped:
        return None
    # At least one identifier when the module defines a min set.
    if cfg.min_identifier_fields and not (cfg.min_identifier_fields & mapped):
        return None
    # Ambiguity: a logical field claimed by 2+ headers needs a human.
    if any(c > 1 for c in field_counts.values()):
        return None
    return mapping


def _stash_unmapped(
    *,
    upload_id: str,
    file_signature: str | None,
    extra: dict[str, Any],
) -> None:
    """Mark the upload as awaiting mapping confirmation.

    Carries `file_signature` + per-module `extra` in `file_uploads.result`
    so the mapping page can pick them up on the GET. The blob itself
    stays in storage; we re-read it on demand via `_load_unmapped`.
    """
    payload: dict[str, Any] = {
        "mapping_state": {
            "file_signature": file_signature,
            "extra": extra or {},
        },
    }
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                update hub.file_uploads
                  set parse_status = 'mapping_pending',
                      result = result || %s::jsonb,
                      parsed_at = now()
                where upload_id = %s
                """,
                (json.dumps(payload, ensure_ascii=False, default=str), upload_id),
            )


def _load_unmapped(
    upload_id: str, *, module: str,
) -> tuple[bytes, str | None, dict[str, Any]]:
    """Read back the mapping-pending file_upload + load the blob from disk."""
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                select stored_path, result, parse_status
                from hub.file_uploads where upload_id = %s
                """,
                (upload_id,),
            )
            row = cur.fetchone()
    if not row:
        raise HTTPException(404, "Upload not found")
    stored_path, result, parse_status = row
    if parse_status not in ("mapping_pending", "pending_preview"):
        raise HTTPException(409, f"Upload not in mapping state (status={parse_status})")

    info = (result or {}).get("mapping_state") or {}
    file_signature = info.get("file_signature")
    extra = info.get("extra") or {}

    from app.storage import get_backend
    blob = get_backend().get(stored_path)
    return blob, file_signature, extra


def _stash_pending(
    *,
    client_id: str,
    upload_id: str,
    module: str,
    parsed: list[dict],
    skipped: list[dict],
    used_mapping: dict[str, str] | None,
    file_signature: str | None,
    proposed_by: str,
    extra: dict[str, Any] | None = None,
    header_row_override: int | None = None,
    extra_required_fields: list[str] | None = None,
) -> str:
    pending_id = secrets.token_urlsafe(16)
    diff_summary: dict[str, Any] = {
        "used_mapping": used_mapping or {},
        "file_signature": file_signature,
        "proposed_by": proposed_by,
        "skipped_rows": skipped or [],
        "header_row_override": header_row_override,
        "extra_required_fields": extra_required_fields or [],
    }
    if extra:
        # Per-module extras (e.g., catalog provenance_kind) — merge.
        for k, v in extra.items():
            if k.startswith("_"):
                continue
            diff_summary[k] = v
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                insert into hub.upload_pending
                  (pending_id, client_id, module, upload_id,
                   parsed_rows, diff_summary, created_by)
                values (%s, %s, %s, %s, %s::jsonb, %s::jsonb, NULL)
                """,
                (pending_id, client_id, module, upload_id,
                 json.dumps(parsed, ensure_ascii=False, default=str),
                 json.dumps(diff_summary, ensure_ascii=False, default=str)),
            )
    return pending_id


def _mark_pending_preview(upload_id: str, row_count: int) -> None:
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                update hub.file_uploads
                  set parse_status = 'pending_preview',
                      row_count = %s,
                      parse_error = NULL,
                      parsed_at = now()
                where upload_id = %s
                """,
                (row_count, upload_id),
            )


__all__ = [
    "ModuleConfig",
    "upload_initial_dispatch",
    "render_mapping_page_context",
    "render_mapping_page_with_llm_suggestion",
    "parse_with_overrides_and_stash",
    "render_preview_context",
    "confirm_pending",
    "reject_pending",
    # Slice 3: BOM uses these directly (bypassing the all-in-one
    # parse_with_overrides_and_stash) because BOM's stash shape is
    # `{"products": ..., "flatten": ...}` not the flat rows array.
    "_load_unmapped",
    "_stash_unmapped",
]
