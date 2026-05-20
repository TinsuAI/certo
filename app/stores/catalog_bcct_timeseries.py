"""Per-material BCCT field time-series.

Run-length-encoded (RLE) timelines for the 4 stable categorical BCCT
columns (`unit`, `hs_code`, `origin`, `declaration_type`) plus
per-quarter numeric stats for `unit_price` and `quantity`.

Computed on read against `hub.bcct_rows` — no derived storage (memory
`feedback_no_derived_in_source`). One SQL query per material; RLE +
quarter bucketing done in Python.

Brief: `.ai/features/2026-05-20-catalog-detail-time-series/brief.md`.
"""
from __future__ import annotations

import statistics
from dataclasses import dataclass
from datetime import date

from app.database import connect


# Categorical fields tracked, in display order. Severity mirrors the
# snapshot drift panel in `catalog_bcct_analysis.py`.
_FIELDS: tuple[tuple[str, str, str], ...] = (
    ("unit", "Đơn vị tính", "critical"),
    ("hs_code", "Mã HS", "warn"),
    ("origin", "Xuất xứ", "info"),
    ("declaration_type", "Loại tờ khai", "info"),
)


@dataclass(frozen=True)
class Run:
    """One run-length-encoded segment of the timeline for one field.

    `value`: the field value (`None` for null / empty).
    `start_date`/`end_date`: first / last `registration_date` of any
        declaration in this run.
    `n_declarations`: number of distinct (declaration_no, direction)
        tuples in the run.
    `n_lines`: total BCCT lines covered.
    `direction_breakdown`: `{'import': N, 'export': M}` for chip display.
    """
    value: str | None
    start_date: date
    end_date: date
    n_declarations: int
    n_lines: int
    direction_breakdown: dict[str, int]


@dataclass(frozen=True)
class FieldTimeline:
    field: str
    label: str
    severity: str
    runs: list[Run]

    @property
    def n_distinct_values(self) -> int:
        return len({r.value for r in self.runs})

    @property
    def has_drift(self) -> bool:
        return self.n_distinct_values >= 2


@dataclass(frozen=True)
class QuarterStat:
    """Aggregate stats for one calendar quarter (e.g. '2026-Q2')."""
    quarter: str
    n_declarations: int
    n_lines: int
    qty_total: float | None
    qty_mean: float | None
    price_min: float | None
    price_median: float | None
    price_max: float | None
    currency: str | None
    # True when median price differs ≥2× from the previous quarter's
    # median (i.e. ratio outside [0.5, 2.0]). Computed post-bucket.
    price_jump_from_prev: bool


@dataclass(frozen=True)
class MaterialTimeline:
    material_code: str
    n_declarations: int
    timelines: list[FieldTimeline]
    quarterly: list[QuarterStat]

    @property
    def has_any_drift(self) -> bool:
        return any(t.has_drift for t in self.timelines)


def _fetch_per_declaration(client_id: str, material_code: str) -> list[dict]:
    """One row per (declaration_no, direction, registration_date) with
    the modal field value across that declaration's lines + price /
    qty aggregates. Multi-line declarations collapse with `mode()
    within group`."""
    sql = """
        select declaration_no, direction, registration_date,
               declaration_type,
               mode() within group (order by unit) as unit,
               mode() within group (order by hs_code) as hs_code,
               mode() within group (order by origin) as origin,
               mode() within group (order by currency_nt) as currency,
               count(*) as n_lines,
               avg(unit_price)::float8 as avg_unit_price,
               min(unit_price)::float8 as min_unit_price,
               max(unit_price)::float8 as max_unit_price,
               sum(quantity)::float8 as total_qty
          from hub.bcct_rows
         where client_id = %s
           and customs_code = %s
           and registration_date is not null
         group by declaration_no, direction, registration_date,
                  declaration_type
         order by registration_date, declaration_no, direction
    """
    with connect() as conn, conn.cursor() as cur:
        cur.execute(sql, (client_id, material_code))
        cols = [d[0] for d in cur.description]
        return [dict(zip(cols, r)) for r in cur.fetchall()]


def _normalize_value(v):
    """Treat empty string the same as null. The snapshot panel uses
    the same convention via its `∅` display."""
    if v is None:
        return None
    if isinstance(v, str) and v.strip() == "":
        return None
    return v


def _rle_field(rows: list[dict], field: str) -> list[Run]:
    """Walk rows in date order, collapse consecutive same-value runs
    into one Run each. Distinct null vs non-null splits the run."""
    if not rows:
        return []
    runs: list[Run] = []
    cur_value = _normalize_value(rows[0][field])
    cur_start = rows[0]["registration_date"]
    cur_end = rows[0]["registration_date"]
    cur_n_decls = 1
    cur_n_lines = rows[0]["n_lines"]
    cur_dirs: dict[str, int] = {rows[0]["direction"]: 1}

    def flush() -> None:
        runs.append(Run(
            value=cur_value,
            start_date=cur_start, end_date=cur_end,
            n_declarations=cur_n_decls, n_lines=cur_n_lines,
            direction_breakdown=dict(cur_dirs),
        ))

    for r in rows[1:]:
        v = _normalize_value(r[field])
        if v != cur_value:
            flush()
            cur_value = v
            cur_start = r["registration_date"]
            cur_end = r["registration_date"]
            cur_n_decls = 1
            cur_n_lines = r["n_lines"]
            cur_dirs = {r["direction"]: 1}
        else:
            cur_end = r["registration_date"]
            cur_n_decls += 1
            cur_n_lines += r["n_lines"]
            cur_dirs[r["direction"]] = cur_dirs.get(r["direction"], 0) + 1
    flush()
    return runs


def _quarter_key(d: date) -> str:
    return f"{d.year}-Q{(d.month - 1) // 3 + 1}"


def _bucket_quarterly(rows: list[dict]) -> list[QuarterStat]:
    """Group rows by calendar quarter, compute price + qty stats per
    bucket. Returns list in chronological order with `price_jump_from_prev`
    set on each bucket relative to the previous one."""
    if not rows:
        return []
    buckets: dict[str, list[dict]] = {}
    for r in rows:
        buckets.setdefault(_quarter_key(r["registration_date"]), []).append(r)

    raw: list[dict] = []
    for q in sorted(buckets):
        b = buckets[q]
        # `avg_unit_price` is the per-declaration mean. For the bucket
        # stat we treat each declaration's mean as one observation
        # (declarations weighted equally, not by line count — staff
        # cares about the typical declaration, not the line average).
        prices = [r["avg_unit_price"] for r in b
                  if r["avg_unit_price"] is not None]
        qtys = [r["total_qty"] for r in b
                if r["total_qty"] is not None]
        # Currency mode within bucket (different decls can mix currencies
        # for the same material — surface the dominant one). Iterate over
        # the sorted distinct set so ties resolve deterministically
        # (set iteration order is implementation-defined; tests must be
        # repeatable across Python runs).
        currencies = [r["currency"] for r in b if r["currency"]]
        currency_mode = (
            max(sorted(set(currencies)), key=currencies.count)
            if currencies else None
        )
        raw.append({
            "quarter": q,
            "n_declarations": len(b),
            "n_lines": sum(r["n_lines"] for r in b),
            "qty_total": sum(qtys) if qtys else None,
            "qty_mean": (sum(qtys) / len(qtys)) if qtys else None,
            "price_min": min(prices) if prices else None,
            "price_median": (
                statistics.median(prices) if prices else None
            ),
            "price_max": max(prices) if prices else None,
            "currency": currency_mode,
        })

    out: list[QuarterStat] = []
    prev_median: float | None = None
    for q in raw:
        median = q["price_median"]
        jump = False
        # `prev_median > 0` guards against:
        # (1) div-by-zero on a zero-priced previous quarter,
        # (2) negative medians (shouldn't happen for prices but defensive).
        # Consequence: if the previous quarter genuinely had median=0,
        # the next quarter never flags as a jump regardless of its own
        # median — accepted edge case (zero-priced declarations are
        # already anomalous and surface elsewhere).
        if median is not None and prev_median is not None and prev_median > 0:
            ratio = median / prev_median
            # Boundary semantic: ratios exactly 2.0× or 0.5× DO flag
            # (inclusive on both ends). The 2× threshold is the
            # conventional "anomaly" rule of thumb for price stability.
            if ratio >= 2.0 or ratio <= 0.5:
                jump = True
        out.append(QuarterStat(
            quarter=q["quarter"],
            n_declarations=q["n_declarations"],
            n_lines=q["n_lines"],
            qty_total=q["qty_total"],
            qty_mean=q["qty_mean"],
            price_min=q["price_min"],
            price_median=median,
            price_max=q["price_max"],
            currency=q["currency"],
            price_jump_from_prev=jump,
        ))
        if median is not None:
            prev_median = median
    return out


def analyze_material_timeline(
    *, client_id: str, material_code: str,
) -> MaterialTimeline:
    """Build the full time-series view for one material."""
    rows = _fetch_per_declaration(client_id, material_code)
    timelines = [
        FieldTimeline(
            field=field, label=label, severity=severity,
            runs=_rle_field(rows, field),
        )
        for field, label, severity in _FIELDS
    ]
    quarterly = _bucket_quarterly(rows)
    return MaterialTimeline(
        material_code=material_code,
        n_declarations=len(rows),
        timelines=timelines,
        quarterly=quarterly,
    )
