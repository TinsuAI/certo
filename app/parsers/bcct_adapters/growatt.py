"""Growatt BCCT adapter.

Goods name shape (verified against 666 export rows in dev DB):

    BIENTAN.17#&Thiết bị biến tần model MIN 4200TL-X2(Pro.E), ... (PV01.0117500)#&VN
    SD00.0010600#&Pin Lithium-ion ... Hàng mới 100%#&VN
    BIENTAN.34#&Thiết bị biến tần model SYN 200-XH-US-11A, ... (PV06.0005500)#&VN

The BOM product code, when embedded, appears as a parenthesized token
matching shape `[A-Z]{2,}\\d{2}\\.\\w+`. Model names like `(Pro)`,
`(Pro.E)`, `(MIN ...)` do not match this shape and are excluded.

Multi-paren rows yield multiple candidates; the resolver validates each
against `bom_artifacts.product_code`.
"""
from __future__ import annotations

import re

# Shape constraint: 2+ uppercase letters, two digits, dot, alnum suffix.
# Matches PV01.0117500, SA00.0001402, PV06.0005500, SD00.0010600.
# Excludes model-only parens like (Pro), (Pro.E), (MIN ...) — they lack
# the required \d{2}\. structure. Resolver further disambiguates by
# requiring the matched code to exist in bom_artifacts.product_code.
_PAREN_CODE = re.compile(r"\(([A-Z]{2,}\d{2}\.[A-Za-z0-9._\-]+)\)")


class GrowattBcctAdapter:
    name = "growatt_bcct"
    parser_version = "2026-05-07"

    def parse_candidates(self, row: dict) -> list[dict]:
        goods_name = (row.get("goods_name") or "").strip()
        if not goods_name:
            return []
        out: list[dict] = []
        seen: set[str] = set()
        for m in _PAREN_CODE.finditer(goods_name):
            code = m.group(1)
            if code in seen:
                continue
            seen.add(code)
            out.append({
                "product_code": code,
                "source_field": "goods_name",
                "matched_text": code,
                "match_rule": "parenthesized_product_code_exists_in_bom_products",
            })
        return out
