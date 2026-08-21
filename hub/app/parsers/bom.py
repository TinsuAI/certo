"""BOM Excel parsers — thin facade over `app/parsers/bom_adapters/`.

Returns a dict[product_code, list[row_dict]]. Real parsing logic lives
in the per-format adapter modules; this file preserves the historical
public surface (`parse_bom_workbook`, `BomParseError`, `COMMON_ALIASES`)
so existing call sites + tests continue to work.

To add a new BOM workbook shape:
  1. Drop `app/parsers/bom_adapters/<your_format>.py`.
  2. Implement `class <YourFormat>Adapter` with `name`, `label_key`,
     `description_key`, `supports_mapping_override`, `parse(...)`.
  3. Import + `register(...)` in `app/parsers/bom_adapters/__init__.py`.
No route or template changes needed — the registry is consulted dynamically.
"""
from __future__ import annotations

from hub.app.parsers.bom_adapters import BomParseError, parse_with
from hub.app.parsers.bom_adapters._common import COMMON_ALIASES

__all__ = ["parse_bom_workbook", "BomParseError", "COMMON_ALIASES"]


def parse_bom_workbook(
    blob: bytes,
    *,
    profile: str = "manual_flat",
    mapping_override: dict[str, str] | None = None,
) -> dict[str, list[dict]]:
    """Parse a BOM workbook via the named adapter.

    `profile` accepts both new neutral names (`manual_flat`,
    `sheet_per_product`, `sap_exploded_levels`) and legacy aliases
    (`growatt_multi_workbook`, `johnson_sap_exploded`).
    """
    return parse_with(blob, name=profile, mapping_override=mapping_override)
