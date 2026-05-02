"""Display label derivation. Spec §3A — labels are denormalized cache,
NEVER used as DB keys. Every part must exist as a structured field."""
from __future__ import annotations


def build_display_label(
    *,
    product_code: str,
    bom_variant_id: str | None,
    version_no: int,
    source_bom_kind: str,
    flatten_status: str,
    flatten_strategy: str,
) -> str:
    """`{product_code} · {bom_variant_id} · v{version_no} · {source_bom_kind} · {flatten_status} · {flatten_strategy}`"""
    return (
        f"{product_code} · {bom_variant_id or 'default'} · v{version_no}"
        f" · {source_bom_kind} · {flatten_status} · {flatten_strategy}"
    )
