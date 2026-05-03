from __future__ import annotations

from collections.abc import Mapping, Sequence
from math import ceil
from urllib.parse import urlencode


DEFAULT_PAGE_SIZE = 50
PAGE_SIZES = (25, 50, 100)


def build_table_view(
    rows: Sequence[Mapping],
    columns: Sequence[Mapping],
    query: Mapping | None = None,
    filters: Sequence[Mapping] | None = None,
    summary_fields: Sequence[Mapping] | None = None,
    default_sort: str | None = None,
    default_per_page: int = DEFAULT_PAGE_SIZE,
    param_prefix: str = "",
) -> dict:
    query_values = normalize_query(query or {})
    field_names = table_field_names(param_prefix)
    column_defs = [normalize_column(column) for column in columns]
    filter_defs = [normalize_filter(filter_def, rows, param_prefix) for filter_def in filters or []]
    q = query_values.get(field_names["q"], "").strip()

    filtered_rows = [dict(row) for row in rows]
    if q:
        searchable_fields = [
            column["key"]
            for column in column_defs
            if column.get("searchable", True)
        ]
        filtered_rows = [
            row for row in filtered_rows
            if row_matches_search(row, searchable_fields, q)
        ]

    for filter_def in filter_defs:
        value = query_values.get(filter_def["query_name"], "").strip()
        filter_def["value"] = value
        if value:
            field = filter_def["field"]
            filtered_rows = [
                row for row in filtered_rows
                if normalize_value(row.get(field)) == normalize_value(value)
            ]

    sort_key = query_values.get(field_names["sort"]) or default_sort or (column_defs[0]["key"] if column_defs else "")
    sortable_keys = {column["key"] for column in column_defs if column.get("sortable", True)}
    if sort_key not in sortable_keys:
        sort_key = default_sort if default_sort in sortable_keys else (column_defs[0]["key"] if column_defs else "")
    direction = "desc" if query_values.get(field_names["dir"]) == "desc" else "asc"
    if sort_key:
        filtered_rows.sort(
            key=lambda row: natural_sort_value(row.get(sort_key)),
            reverse=direction == "desc",
        )

    per_page = min(max(1, parse_int(query_values.get(field_names["per_page"]), default_per_page)), 500)
    page_count = max(1, ceil(len(filtered_rows) / per_page))
    page = min(max(1, parse_int(query_values.get(field_names["page"]), 1)), page_count)
    start = (page - 1) * per_page
    end = start + per_page

    prepared_query = {
        key: value
        for key, value in query_values.items()
        if key != field_names["page"]
    }
    owned_names = table_owned_query_names(filter_defs, field_names)
    reset_query = {
        key: value
        for key, value in query_values.items()
        if key not in owned_names
    }
    for column in column_defs:
        column["sort_active"] = column["key"] == sort_key
        column["sort_dir"] = direction if column["sort_active"] else ""
        column["sort_query"] = page_query(
            prepared_query,
            **{
                field_names["sort"]: column["key"],
                field_names["dir"]: "desc" if column["sort_active"] and direction == "asc" else "asc",
                field_names["page"]: 1,
            },
        )

    return {
        "rows": filtered_rows[start:end],
        "columns": column_defs,
        "filters": filter_defs,
        "summary_chips": build_summary_chips(filtered_rows, summary_fields or []),
        "query": query_values,
        "field_names": field_names,
        "passthrough_params": reset_query,
        "param_prefix": param_prefix,
        "q": q,
        "sort": sort_key,
        "dir": direction,
        "page": page,
        "per_page": per_page,
        "page_sizes": PAGE_SIZES,
        "total_pages": page_count,
        "total_count": len(rows),
        "filtered_count": len(filtered_rows),
        "start_index": start + 1 if filtered_rows else 0,
        "end_index": min(end, len(filtered_rows)),
        "has_previous": page > 1,
        "has_next": page < page_count,
        "previous_query": page_query(prepared_query, **{field_names["page"]: page - 1}),
        "next_query": page_query(prepared_query, **{field_names["page"]: page + 1}),
        "first_query": page_query(prepared_query, **{field_names["page"]: 1}),
        "last_query": page_query(prepared_query, **{field_names["page"]: page_count}),
        "reset_query": page_query(reset_query),
    }


def normalize_query(query: Mapping) -> dict[str, str]:
    return {
        str(key): str(value)
        for key, value in query.items()
        if value is not None and str(value) != ""
    }


def normalize_column(column: Mapping) -> dict:
    return {
        "key": str(column["key"]),
        "label": str(column.get("label") or column["key"]),
        "class": str(column.get("class", "")),
        "searchable": bool(column.get("searchable", True)),
        "sortable": bool(column.get("sortable", True)),
        "link_key": str(column.get("link_key", "")),
    }


def normalize_filter(filter_def: Mapping, rows: Sequence[Mapping], param_prefix: str = "") -> dict:
    name = str(filter_def["name"])
    field = str(filter_def.get("field") or name)
    options = filter_def.get("options")
    if options is None:
        values = sorted(
            {
                str(row.get(field))
                for row in rows
                if row.get(field) is not None and str(row.get(field, "")).strip()
            },
            key=natural_sort_value,
        )
        options = [{"value": value, "label": value} for value in values]
    return {
        "name": name,
        "query_name": f"{param_prefix}{name}" if param_prefix else name,
        "field": field,
        "label": str(filter_def.get("label") or name),
        "options": [normalize_filter_option(option) for option in options],
        "value": "",
    }


def table_field_names(param_prefix: str) -> dict[str, str]:
    return {
        "q": f"{param_prefix}q" if param_prefix else "q",
        "sort": f"{param_prefix}sort" if param_prefix else "sort",
        "dir": f"{param_prefix}dir" if param_prefix else "dir",
        "page": f"{param_prefix}page" if param_prefix else "page",
        "per_page": f"{param_prefix}per_page" if param_prefix else "per_page",
    }


def table_owned_query_names(filters: Sequence[Mapping], field_names: Mapping[str, str]) -> set[str]:
    return set(field_names.values()) | {str(filter_def["query_name"]) for filter_def in filters}


def normalize_filter_option(option) -> dict[str, str]:
    if isinstance(option, Mapping):
        value = option.get("value", "")
        label = option.get("label", value)
        return {"value": str(value), "label": str(label)}
    return {"value": str(option), "label": str(option)}


def row_matches_search(row: Mapping, fields: Sequence[str], term: str) -> bool:
    needle = normalize_value(term)
    return any(needle in normalize_value(row.get(field)) for field in fields)


def normalize_value(value) -> str:
    return str(value or "").casefold()


def natural_sort_value(value) -> tuple:
    text = str(value or "")
    try:
        return (0, float(text.replace(",", "")))
    except ValueError:
        return (1, text.casefold())


def parse_int(value, default: int) -> int:
    try:
        return int(str(value))
    except (TypeError, ValueError):
        return default


def build_summary_chips(rows: Sequence[Mapping], summary_fields: Sequence[Mapping]) -> list[dict]:
    chips = []
    for field_def in summary_fields:
        field = str(field_def["field"])
        label = str(field_def.get("label") or field)
        counts = {}
        for row in rows:
            value = str(row.get(field, "") or "")
            if value:
                counts[value] = counts.get(value, 0) + 1
        for value, count in sorted(counts.items(), key=lambda item: (-item[1], natural_sort_value(item[0]))):
            chips.append({"label": f"{label}: {value}", "count": count})
    return chips


def page_query(base_query: Mapping, **updates) -> str:
    query = {
        key: value
        for key, value in base_query.items()
        if value is not None and str(value) != ""
    }
    query.update({key: value for key, value in updates.items() if value is not None})
    return urlencode(query)
