"""Shared pagination + sort + link-building helpers for list views.

Each list view declares its own sort whitelist (column-name → SQL
fragment) so the URL `?sort=` parameter can never inject arbitrary
SQL. The fallback is the default sort declared by the view.

Pagination is offset-based — straightforward UI semantics (prev /
next / first / last / page-jump). For the JSON API see
`app/routes/api.py:_page_args` (cursor-based).

Convention:

    p = parse_page_params(query_params=request.query_params)
    s = SortSpec.from_params(
        query_params=request.query_params,
        whitelist=BCCT_SORTS, default=("registration_date", "desc"),
    )
    rows = list_query(client_id, p.offset, p.page_size, s.sql_clause())
    total = count_query(client_id)
    ctx = {
        "page": p, "sort": s, "total": total,
        "next_url": build_link(base_path=req.url.path,
            current=req.query_params, override={"page": p.page + 1}),
        ...
    }
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping
from urllib.parse import urlencode


DEFAULT_PAGE_SIZE = 50
MAX_PAGE_SIZE = 200
PAGE_SIZE_CHOICES: tuple[int, ...] = (25, 50, 100, 200)


def _to_int(value, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


@dataclass(frozen=True)
class PageParams:
    page: int
    page_size: int

    @property
    def offset(self) -> int:
        return (self.page - 1) * self.page_size

    def has_prev(self) -> bool:
        return self.page > 1

    def has_next(self, *, total: int) -> bool:
        return self.page < self.total_pages(total)

    def total_pages(self, total: int) -> int:
        if total <= 0:
            return 0
        return (total + self.page_size - 1) // self.page_size


def parse_page_params(*, query_params: Mapping[str, str]) -> PageParams:
    page = max(1, _to_int(query_params.get("page"), 1))
    raw_size = _to_int(query_params.get("page_size"), DEFAULT_PAGE_SIZE)
    if raw_size <= 0:
        page_size = DEFAULT_PAGE_SIZE
    else:
        page_size = min(raw_size, MAX_PAGE_SIZE)
    return PageParams(page=page, page_size=page_size)


@dataclass(frozen=True)
class SortSpec:
    """Resolved sort: column name (whitelist key), direction, and the
    SQL fragment to splice into ORDER BY. The fragment is only ever
    composed from whitelist values + literal asc/desc/'nulls last' —
    never from raw user input."""
    column: str
    direction: str
    _column_sql: str  # whitelisted SQL fragment for the column

    @classmethod
    def from_params(cls, *, query_params: Mapping[str, str],
                    whitelist: Mapping[str, str],
                    default: tuple[str, str]) -> "SortSpec":
        raw_col = query_params.get("sort")
        if raw_col and raw_col in whitelist:
            col = raw_col
            direction = (query_params.get("dir") or "asc").lower()
            if direction not in {"asc", "desc"}:
                direction = "asc"
        else:
            # Unknown / missing sort column → use both default column
            # AND default direction. User-supplied dir is ignored when
            # the column is invalid — the default pair is canonical.
            col, direction = default
        return cls(column=col, direction=direction, _column_sql=whitelist[col])

    def sql_clause(self, *, tiebreakers: tuple[str, ...] = ()) -> str:
        """Render `<col> [asc|desc nulls last][, tiebreaker1, ...]`.

        `nulls last` is appended to desc only — for asc, NULLs sort
        first by default which is conventional. Tiebreakers are
        whitelisted SQL fragments supplied by the caller; they're
        appended after the primary key without a direction suffix
        (caller chose them).
        """
        primary = f"{self._column_sql} {self.direction}"
        if self.direction == "desc":
            primary += " nulls last"
        if tiebreakers:
            return primary + ", " + ", ".join(tiebreakers)
        return primary


def build_link(*, base_path: str, current: Mapping[str, str],
               override: Mapping[str, object]) -> str:
    """Build a URL preserving `current` query params, applying
    `override` (None values drop the param). Used to render
    pagination + sort + page-size links without losing the active
    `q=` / chip-row filter / etc."""
    merged: dict[str, str] = {}
    for k, v in current.items():
        if v is None or v == "":
            continue
        merged[k] = str(v)
    for k, v in override.items():
        if v is None:
            merged.pop(k, None)
        else:
            merged[k] = str(v)
    if not merged:
        return base_path
    return f"{base_path}?{urlencode(merged)}"


# ── Helpers for view contexts ───────────────────────────────────────────


def pagination_context(*, request, page_params: PageParams,
                       total: int) -> dict:
    """Build the dict the `_pagination.html` partial expects."""
    base = request.url.path
    current = dict(request.query_params)
    total_pages = page_params.total_pages(total)
    return {
        "page": page_params,
        "total": total,
        "total_pages": total_pages,
        "page_size_choices": PAGE_SIZE_CHOICES,
        "first_url": build_link(base_path=base, current=current,
                                override={"page": 1}),
        "prev_url": build_link(base_path=base, current=current,
                               override={"page": max(1, page_params.page - 1)}),
        "next_url": build_link(base_path=base, current=current,
                               override={"page": page_params.page + 1}),
        "last_url": build_link(base_path=base, current=current,
                               override={"page": max(1, total_pages)}),
        # Page-size links — preserve everything else, force page=1
        "page_size_urls": {
            size: build_link(base_path=base, current=current,
                             override={"page_size": size, "page": 1})
            for size in PAGE_SIZE_CHOICES
        },
    }


def sort_link(*, request, column: str, current_sort: SortSpec) -> str:
    """Build the URL for clicking a sortable column header. If the
    column is currently active, flip its direction; otherwise apply
    the column with its natural default direction (desc for date-ish
    columns is conventional but the caller can pass a different
    default by encoding it into the link). Reset to page 1 — sort
    invalidates pagination."""
    base = request.url.path
    current = dict(request.query_params)
    if current_sort.column == column:
        new_dir = "asc" if current_sort.direction == "desc" else "desc"
    else:
        new_dir = "asc"
    return build_link(
        base_path=base, current=current,
        override={"sort": column, "dir": new_dir, "page": 1},
    )
