"""Identity adapter — yields no goods-name candidates.

Used for clients without a goods-name embedded BOM code convention.
The resolver still considers structured_field + reviewed_line_mapping +
code_mappings stages on its own.
"""
from __future__ import annotations


class IdentityBcctAdapter:
    name = "identity"
    parser_version = "2026-05-07"

    def parse_candidates(self, row: dict) -> list[dict]:
        return []
