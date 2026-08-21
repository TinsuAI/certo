"""Runtime-derived BCCT row attributes.

Brief: .ai/features/2026-05-08-configurable-bcct-parsing/brief.md

Replaces hardcoded `bcct_rows.internal_code` cache (mig 005) +
`growatt_parse_internal_code` regex with runtime computation:
  - Identity-mode clients: short-circuit to `customs_code`.
  - All other clients: evaluate `client_parser_rules` table for
    `output_field='internal_code'`. (Phase 3 wires the DB-loading
    layer; this stub returns None until rules load.)
"""
from __future__ import annotations


def compute_internal_code(row: dict, *, client: dict) -> str | None:
    """Derive `internal_code` for a BCCT row at runtime.

    `client` is a dict with at least `code_resolution_mode` and
    `client_id`. For identity-mode clients, internal == customs.
    Other clients evaluate `hub.client_parser_rules` for
    output_field='internal_code'.
    """
    if client.get("code_resolution_mode") == "identity":
        return row.get("customs_code") or None
    from app.parsers.client_parser_rules import (
        evaluate_compiled_rules,
        load_rules,
    )
    rules = load_rules(client_id=client["client_id"], output_field="internal_code")
    return evaluate_compiled_rules(rules, row=row)
