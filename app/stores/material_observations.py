"""Compute observation signals for a single material across BCCT.

WORKAROUND for hub.v_material_roles view: that view JOINs only by
`bcct_rows.customs_code`, missing NB codes that live in `goods_name`
parens for clients with parser_rules (Growatt-shape). Backlog item
"Catalog matching column ≠ classifier matching column" tracks the
proper fix (rebuild view as materialized view with re2-aware
resolution).

This module gives request-time accurate signals for the catalog detail
page. It uses the per-client `client_parser_rules` config — generic,
not Growatt-specific. Clients without rules fall back to customs_code
only (Johnson-shape) and behave identically to the view.
"""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass

from app.database import connect
from app.parsers.client_parser_rules import (
    extract_all_matches_from_compiled, load_rules,
)


@dataclass
class Observations:
    has_imports: bool = False
    has_exports: bool = False
    observed_count: int = 0
    observed_first_at: dt.date | None = None
    observed_last_at: dt.date | None = None
    observed_directions: list[str] | None = None

    def __post_init__(self):
        if self.observed_directions is None:
            self.observed_directions = []


def compute_observations(client_id: str, material_code: str) -> Observations:
    """Aggregate BCCT evidence for a material via customs_code OR
    parser-rule paren extract from goods_name.

    Returns observation counts (distinct declarations) + direction breakdown.
    Works for all client shapes — for clients without parser_rules, the
    paren branch yields no matches and behavior collapses to v_material_roles.
    """
    rules = load_rules(client_id=client_id, output_field="internal_code")

    with connect() as conn, conn.cursor() as cur:
        if rules:
            cur.execute(
                """
                select customs_code, goods_name, direction,
                       registration_date, declaration_no
                from hub.bcct_rows
                where client_id = %s
                  and (customs_code = %s or goods_name like %s)
                """,
                (client_id, material_code, f"%({material_code})%"),
            )
        else:
            cur.execute(
                """
                select customs_code, goods_name, direction,
                       registration_date, declaration_no
                from hub.bcct_rows
                where client_id = %s and customs_code = %s
                """,
                (client_id, material_code),
            )
        rows = cur.fetchall()

    decl_set: set[str] = set()
    directions: set[str] = set()
    first_at: dt.date | None = None
    last_at: dt.date | None = None
    has_imports = has_exports = False

    for cc, gn, dr, regdate, decl in rows:
        if cc == material_code:
            matched = True
        elif rules and gn:
            matched = any(
                m.get("product_code") == material_code
                for m in extract_all_matches_from_compiled(
                    rules, row={"customs_code": cc, "goods_name": gn},
                )
            )
        else:
            matched = False
        if not matched:
            continue
        if dr == "import":
            has_imports = True
            directions.add("import")
        elif dr == "export":
            has_exports = True
            directions.add("export")
        if decl:
            decl_set.add(decl)
        if regdate:
            if first_at is None or regdate < first_at:
                first_at = regdate
            if last_at is None or regdate > last_at:
                last_at = regdate

    return Observations(
        has_imports=has_imports,
        has_exports=has_exports,
        observed_count=len(decl_set),
        observed_first_at=first_at,
        observed_last_at=last_at,
        observed_directions=sorted(directions),
    )
