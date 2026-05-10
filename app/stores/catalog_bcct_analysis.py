"""Per-material BCCT analysis: source row count + inconsistency drift.

Used by the catalog material detail page (Feature 3 brief). Computes
on-read against `hub.bcct_rows` — no derived storage (memory rule
`feedback_no_derived_in_source`).

Severity tiers mirror the UoM ingest-time drift gate:
- `critical` for `unit` (UoM mismatch breaks BOM math).
- `warn` for `hs_code` (variants per declaration are legitimate but
  worth surfacing).
- `info` for `goods_name`, `origin`, `unit_price_range`.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from app.database import connect


@dataclass(frozen=True)
class FieldDrift:
    field: str
    label: str
    severity: str          # 'critical' | 'warn' | 'info'
    distinct_count: int    # 0 or 1 = no drift
    values: list[tuple[str | None, int]]  # [(value, occurrences), ...] desc
    common_prefix_len: int = 0     # longest shared prefix across distinct vals
    common_suffix_len: int = 0     # longest shared suffix


@dataclass(frozen=True)
class Representative:
    """The most-frequent BCCT row used as the canonical sample for a
    material_code in the catalog detail page."""
    declaration_no: str
    registration_date: date | None
    direction: str
    line_no: str
    transaction_key: str
    goods_name: str | None
    unit: str | None
    hs_code: str | None
    origin: str | None
    unit_price: float | None
    occurrence_count: int


@dataclass(frozen=True)
class CatalogBcctAnalysis:
    material_code: str
    bcct_row_count: int
    declaration_count: int
    direction_breakdown: dict[str, int]      # {'import': N, 'export': M}
    representative: Representative | None
    drifts: list[FieldDrift]

    @property
    def has_critical(self) -> bool:
        return any(d.severity == "critical" for d in self.drifts)

    @property
    def has_drift(self) -> bool:
        return bool(self.drifts)


_FIELDS = [
    ("unit", "Đơn vị tính", "critical"),
    ("hs_code", "Mã HS", "warn"),
    ("goods_name", "Tên hàng", "info"),
    ("origin", "Xuất xứ", "info"),
]


def _common_affixes(values: list[str]) -> tuple[int, int]:
    """Longest common prefix + suffix length across all (non-null) values.
    Used to surface where divergence starts in display — values sharing a
    long prefix look identical when truncated, defeating the drift panel's
    purpose."""
    strs = [v for v in values if v]
    if len(strs) < 2:
        return 0, 0
    a = strs[0]
    p = len(a)
    for s in strs[1:]:
        cap = min(p, len(s))
        i = 0
        while i < cap and a[i] == s[i]:
            i += 1
        p = i
        if p == 0:
            break
    s = len(a)
    for t in strs[1:]:
        cap = min(s, len(t))
        i = 0
        while i < cap and a[len(a) - 1 - i] == t[len(t) - 1 - i]:
            i += 1
        s = i
        if s == 0:
            break
    # Don't let prefix+suffix overlap into negative divergence on shortest val.
    shortest = min(len(s2) for s2 in strs)
    if p + s > shortest:
        s = max(0, shortest - p)
    return p, s


def analyze_material_bcct(
    *, client_id: str, material_code: str,
) -> CatalogBcctAnalysis:
    """Aggregate BCCT rows for one material_code; identify drift."""
    with connect() as conn, conn.cursor() as cur:
        # 1) total + per-direction counts
        cur.execute(
            """
            select direction, count(*),
                   count(distinct declaration_no)
              from hub.bcct_rows
             where client_id=%s and customs_code=%s
             group by direction
            """,
            (client_id, material_code),
        )
        breakdown: dict[str, int] = {}
        decl_counts: dict[str, int] = {}
        for direction, n, d in cur.fetchall():
            breakdown[direction] = n
            decl_counts[direction] = d
        total_rows = sum(breakdown.values())
        total_decls = sum(decl_counts.values())

        # 2) representative — most frequent (unit, hs_code, goods_name)
        # tuple, tiebreak by recency, then prefer import direction.
        cur.execute(
            """
            with grouped as (
              select unit, hs_code, goods_name, origin,
                     direction,
                     count(*) as occurrences,
                     max(registration_date) as latest_date,
                     -- pick a representative row from this cluster
                     (array_agg(declaration_no
                                order by registration_date desc nulls last,
                                         line_no desc))[1] as declaration_no,
                     (array_agg(line_no
                                order by registration_date desc nulls last,
                                         line_no desc))[1] as line_no,
                     (array_agg(transaction_key
                                order by registration_date desc nulls last,
                                         line_no desc))[1] as transaction_key,
                     (array_agg(unit_price
                                order by registration_date desc nulls last,
                                         line_no desc))[1] as unit_price
                from hub.bcct_rows
               where client_id=%s and customs_code=%s
               group by unit, hs_code, goods_name, origin, direction
            )
            select * from grouped
            order by occurrences desc,
                     latest_date desc nulls last,
                     case direction when 'import' then 0 else 1 end
            limit 1
            """,
            (client_id, material_code),
        )
        rep_row = cur.fetchone()
        rep: Representative | None = None
        if rep_row:
            (unit, hs_code, goods_name, origin, direction, occurrences,
             latest_date, declaration_no, line_no, transaction_key,
             unit_price) = rep_row
            rep = Representative(
                declaration_no=declaration_no, registration_date=latest_date,
                direction=direction, line_no=line_no,
                transaction_key=transaction_key,
                goods_name=goods_name, unit=unit, hs_code=hs_code,
                origin=origin,
                unit_price=float(unit_price) if unit_price is not None else None,
                occurrence_count=int(occurrences),
            )

        # 3) per-field distinct value counts
        drifts: list[FieldDrift] = []
        for field, label, severity in _FIELDS:
            cur.execute(
                f"""
                select {field}, count(*)
                  from hub.bcct_rows
                 where client_id=%s and customs_code=%s
                 group by {field}
                 order by count(*) desc, {field}
                """,
                (client_id, material_code),
            )
            values = [(v, int(c)) for v, c in cur.fetchall()]
            distinct = len(values)
            if distinct >= 2:
                p_len, s_len = _common_affixes([v for v, _ in values])
                drifts.append(FieldDrift(
                    field=field, label=label, severity=severity,
                    distinct_count=distinct, values=values,
                    common_prefix_len=p_len, common_suffix_len=s_len,
                ))

    return CatalogBcctAnalysis(
        material_code=material_code,
        bcct_row_count=total_rows,
        declaration_count=total_decls,
        direction_breakdown=breakdown,
        representative=rep,
        drifts=drifts,
    )
