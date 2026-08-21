"""Shared LLM-fallback helpers for BOM/BQD/Catalog upload routes.

Pattern: rigid parse fails → cache lookup → on miss, call LLM → return
the proposed mapping. The caller re-parses with `mapping_override` and
goes through the Phase 2 preview-confirm flow. After preview confirm,
the mapping is persisted via `cache_confirmed_mapping`.

BCCT has its own slightly older two-stage UI (column-mapping page +
diff-preview page) and doesn't use these helpers; will be unified in a
later refactor.
"""
from __future__ import annotations

import json
import logging

from app import llm
from app.database import connect
from app.parsers._excel import (
    compute_file_signature, header_row, load_xlsx,
)


def headers_per_sheet(blob: bytes) -> list[list[str]]:
    """Return [[header_str, ...], ...] for each sheet that has a recognizable
    header row. Used as input to `compute_file_signature`."""
    try:
        wb = load_xlsx(blob)
    except Exception:  # noqa: BLE001 — best-effort
        return []
    out: list[list[str]] = []
    for ws in wb.worksheets:
        hdr = header_row(ws, max_scan=20)
        if not hdr:
            continue
        _, headers = hdr
        out.append([h for h in headers if h])
    return out


def sample_rows_first_sheet(blob: bytes, n: int = 5) -> tuple[list[str], list[list]]:
    """Return (headers, first n data rows) of the first plausible sheet. Used
    as input to the LLM proposal call."""
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
            if len(rows) >= n:
                break
        return [h for h in headers if h], rows
    return [], []


def lookup_cached_mapping(
    *, client_id: str, module: str, file_signature: str,
) -> dict | None:
    """Read-only cache lookup. Returns mapping dict if a CONFIRMED entry
    exists for this (client, module, signature). `use_count` is bumped
    separately by `record_mapping_use` only after the cached mapping
    parses successfully — prevents overcounting on cached-but-stale
    mappings that fail."""
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                select mapping from hub.parser_mappings
                where client_id = %s and module = %s and file_signature = %s
                  and confirmed_at is not null
                """,
                (client_id, module, file_signature),
            )
            row = cur.fetchone()
            return row[0] if row else None


def record_mapping_use(
    *, client_id: str, module: str, file_signature: str,
) -> None:
    """Bump usage counter — call only after cache hit parsed successfully."""
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                update hub.parser_mappings
                  set use_count = use_count + 1, last_used_at = now()
                where client_id = %s and module = %s and file_signature = %s
                """,
                (client_id, module, file_signature),
            )


def request_llm_mapping(
    *, client_id: str, module: str, blob: bytes, rigid_error: str,
) -> tuple[dict[str, str], list[str], list[list], str]:
    """Ask LLM to propose a header→logical_field mapping for this workbook.

    Returns (mapping, headers, sample_rows, file_signature). Raises
    HTTPException-like RuntimeError on configuration / call failure (the
    caller wraps this into a user-facing 400).

    Why we don't catch+wrap into HTTPException here: keeping the helper
    framework-agnostic so it can be unit-tested; routes turn the raised
    exception class into the right HTTP response.
    """
    cfg = llm.LLMConfig.load()
    if not cfg.is_enabled():
        raise llm.LLMUnavailable(
            f"File không khớp parser tự động ({rigid_error}). "
            f"Bật LLM Smart Parser ở /admin/settings/technical hoặc upload "
            f"file đúng format {module.upper()}."
        )

    sheets = headers_per_sheet(blob)
    if not sheets:
        raise llm.LLMProposalError(
            f"File không có sheet nhận được header (rỗng?): {rigid_error}"
        )

    file_signature = compute_file_signature(
        client_id=client_id, module=module, headers_per_sheet=sheets,
    )
    headers, sample_rows = sample_rows_first_sheet(blob)
    try:
        proposed = llm.propose_header_mapping(
            client_id=client_id, module=module,
            headers=headers, sample_rows=sample_rows, cfg=cfg,
        )
    except (llm.LLMUnavailable, llm.LLMProposalError):
        # Re-raise with full context preserved server-side.
        logging.getLogger(__name__).exception("LLM proposal failed")
        raise
    return proposed, headers, sample_rows, file_signature


def cache_confirmed_mapping(
    *, client_id: str, module: str, file_signature: str,
    mapping: dict[str, str], headers: list[str],
    confirmed_by_user_id: str | None,
    proposed_by: str = "llm",
) -> None:
    """Insert/replace a parser_mappings row marked confirmed. Called from
    the preview-confirm endpoint after staff verifies the LLM mapping
    produced sensible-looking sample rows."""
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                insert into hub.parser_mappings
                  (client_id, module, file_signature, mapping, sample_headers,
                   proposed_by, confirmed_by, confirmed_at)
                values (%s, %s, %s, %s::jsonb, %s::jsonb, %s, %s, now())
                on conflict (client_id, module, file_signature) do update set
                  mapping = excluded.mapping,
                  sample_headers = excluded.sample_headers,
                  proposed_by = excluded.proposed_by,
                  confirmed_by = excluded.confirmed_by,
                  confirmed_at = excluded.confirmed_at
                """,
                (client_id, module, file_signature,
                 json.dumps(mapping, ensure_ascii=False, default=str),
                 json.dumps(headers, ensure_ascii=False, default=str),
                 proposed_by, confirmed_by_user_id),
            )
