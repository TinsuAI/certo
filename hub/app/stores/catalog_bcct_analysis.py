"""Per-material BCCT analysis: source row count + inconsistency drift.

Used by the catalog material detail page (Feature 3 brief). Computes
on-read against `hub.bcct_rows` — no derived storage (memory rule
`feedback_no_derived_in_source`).

Severity tiers mirror the UoM ingest-time drift gate:
- `critical` for `unit` (UoM mismatch breaks BOM math).
- `warn` for `hs_code` (variants per declaration are legitimate but
  worth surfacing).
- `info` for `goods_name`, `origin`, `unit_price_range`.

`goods_name` drift uses normalize-then-bucket so cosmetic variations
(whitespace, double-comma, code prefix, casing) collapse to one
bucket. Real semantic divergence still surfaces.
"""
from __future__ import annotations

import re
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
    convertible: bool = False      # A.4.4: unit values all convert to the
                                   # dominant one → drift downgraded to info


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


_GOODS_NAME_PREFIX_RE = re.compile(r"^[a-z0-9][\w.\-/]*#&\s*")
_PUNCT_RUN_RE = re.compile(r"[\s,.;:!?\-_/\\|()\[\]{}'\"`]+")


def _normalize_goods_name(value: str) -> str:
    """Fold cosmetic variants of one goods_name onto a canonical key.

    Real Johnson data shows variations like:
        "001679-00#&Chốt cố định dây bằng nhựa HC-101, kích thước: 20x20 mm,, hàng mới 100%"
        "001679-00#&Chốt cố định dây bằng nhựa, kích thước: 20x20 mm, hàng mới 100%"
        "001679-00#&Chốt cố định dây bằng nhựa HC-101, kích thước: 20x20 mm, hàng mới 100%"
    that differ only in punctuation runs / dropped tokens but describe
    the same product. They should bucket together so the catalog drift
    panel surfaces only semantic divergence.

    Normalization:
    - lowercase
    - strip leading `<code>#&` prefix (Johnson SAP-export convention)
    - collapse any run of whitespace + punctuation to a single space
    - trim
    """
    s = value.lower()
    s = _GOODS_NAME_PREFIX_RE.sub("", s)
    s = _PUNCT_RUN_RE.sub(" ", s).strip()
    return s


def _bucket_by_normalized(
    values: list[tuple[str | None, int]],
    normalize,
) -> list[tuple[str | None, int]]:
    """Regroup (value, count) pairs by `normalize(value)`.

    Representative per bucket = highest-count original; bucket count =
    sum across raw values. Input is already ordered desc by count, so
    first-seen original in each bucket is the most frequent.
    Returns (representative, total_count) pairs ordered desc by count.
    """
    buckets: dict[object, tuple[str | None, int]] = {}
    for raw, count in values:
        if raw is None:
            key: object = None
        else:
            key = normalize(raw)
        if key in buckets:
            rep, total = buckets[key]
            buckets[key] = (rep, total + count)
        else:
            buckets[key] = (raw, count)
    return sorted(buckets.values(), key=lambda x: (-x[1], x[0] or ""))


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


def _classify_unit_drift(
    client_id: str, material_code: str, units: list[str | None],
) -> tuple[str, bool]:
    """A.4.4: severity for `unit` drift. `units` is desc by frequency, so
    units[0] is the dominant declaration habit. Returns
    ('info', True) when every other unit converts to the dominant one,
    else ('critical', False)."""
    from app.stores.uom import classify_uom_relation
    dominant = units[0]
    for u in units[1:]:
        rel = classify_uom_relation(
            u, dominant, client_id=client_id, material_code=material_code,
        )
        if rel.relation == "incompatible":
            return "critical", False
    return "info", True


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
            if field == "goods_name":
                values = _bucket_by_normalized(values, _normalize_goods_name)
            distinct = len(values)
            if distinct >= 2:
                p_len, s_len = _common_affixes([v for v, _ in values])
                row_severity, convertible = severity, False
                if field == "unit":
                    # A.4.4: a UoM difference is only critical if the
                    # values can't convert. Classify each against the
                    # dominant (most-frequent) unit; all convertible →
                    # info ("đã quy đổi"), any incompatible → stay critical.
                    row_severity, convertible = _classify_unit_drift(
                        client_id, material_code, [v for v, _ in values],
                    )
                drifts.append(FieldDrift(
                    field=field, label=label, severity=row_severity,
                    distinct_count=distinct, values=values,
                    common_prefix_len=p_len, common_suffix_len=s_len,
                    convertible=convertible,
                ))

    return CatalogBcctAnalysis(
        material_code=material_code,
        bcct_row_count=total_rows,
        declaration_count=total_decls,
        direction_breakdown=breakdown,
        representative=rep,
        drifts=drifts,
    )
