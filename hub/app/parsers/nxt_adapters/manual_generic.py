"""manual_generic — last-resort flexible NXT parser.

Handles any reasonably-headed NXT file by alias auto-match, and honours an
LLM/staff-confirmed `mapping_override` (header text → logical field) for layouts
whose headers aren't in the alias list yet. Abstains in detect() so the
high-precision adapters (ezsoft_3tsoft, system_template) win first; this is the
fallback that absorbs unknown formats with zero new code.

reported_role is inferred from the sheet name (NVL/TP/BTP) when present, else
left null — provenance only, never authoritative.
"""
from __future__ import annotations

from hub.app.parsers._excel import (
    cell_num, cell_str, header_row, index_headers, normalize_header, load_xlsx,
)
from hub.app.parsers.nxt_adapters._common import ALIASES, NUMERIC_FIELDS, OUT_BUCKETS

_SHEET_ROLES = {"NVL": "nvl", "TP": "tp", "BTP": "btp"}


def cols_from_override(headers: list[str], override: dict[str, str]) -> dict[str, int]:
    """Map logical field → column index from a {header_text: field} override."""
    norm = [normalize_header(h) for h in headers]
    out: dict[str, int] = {}
    for header_text, field in override.items():
        if field in out:
            continue  # two headers mapped to one field → first column wins
        target = normalize_header(header_text)
        for i, h in enumerate(norm):
            if h and h == target and i not in out.values():
                out[field] = i
                break
    return out


class ManualGenericNxtAdapter:
    name = "manual_generic"
    label_key = "nxt.adapter.manual_generic.label"
    description_key = "nxt.adapter.manual_generic.desc"
    supports_mapping_override = True

    def detect(self, blob: bytes) -> float | None:
        # Generic — no unambiguous structural marker. Abstain so the registry
        # keeps it as the last fallback.
        return None

    def parse(self, blob: bytes, *,
              mapping_override: dict[str, str] | None = None) -> list[dict]:
        from hub.app.parsers.nxt_adapters import NxtParseError
        try:
            wb = load_xlsx(blob)
        except Exception as e:
            raise NxtParseError(f"Cannot open workbook: {e}") from e

        lines: list[dict] = []
        for ws in wb.worksheets:
            hdr = header_row(ws, aliases=ALIASES)
            if not hdr:
                continue
            header_idx, headers = hdr
            cols = (cols_from_override(headers, mapping_override)
                    if mapping_override else index_headers(headers, ALIASES))
            has_code = "internal_code" in cols or "customs_code" in cols
            has_qty = any(f in cols for f in
                          ("opening", "closing_reported", "inbound_total",
                           "outbound_total", *OUT_BUCKETS))
            if not (has_code and has_qty):
                continue
            role = _SHEET_ROLES.get(ws.title.strip().upper())
            for raw in _iter_data_rows(ws, header_idx):
                line = _row_to_line(raw, cols, role)
                if line is not None:
                    lines.append(line)

        if not lines:
            raise NxtParseError("No NXT rows recognized by manual_generic.")
        return lines


def _iter_data_rows(ws, header_row_idx: int):
    for row in ws.iter_rows(min_row=header_row_idx + 1, values_only=True):
        if all(c is None or (isinstance(c, str) and not c.strip()) for c in row):
            continue
        yield row


def _row_to_line(raw, cols: dict[str, int], role: str | None) -> dict | None:
    internal = cell_str(raw, cols.get("internal_code"))
    customs = cell_str(raw, cols.get("customs_code"))
    if not internal and not customs:
        return None
    line = {
        "internal_code": internal,
        "customs_code": customs,
        "name": cell_str(raw, cols.get("name")),
        "uom": cell_str(raw, cols.get("uom")),
        "reported_role": role,
        "note": cell_str(raw, cols.get("note")),
    }
    for f in NUMERIC_FIELDS:
        line[f] = cell_num(raw, cols.get(f))
    # If only the 4 buckets are present, derive the canonical total.
    if line.get("outbound_total") is None:
        buckets = [line.get(f) for f in OUT_BUCKETS]
        if any(b is not None for b in buckets):
            line["outbound_total"] = sum(b or 0.0 for b in buckets)
    return line
