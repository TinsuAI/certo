"""Tab freshness metadata: when was the module last uploaded vs how
recent is the data sitting in DB. Two distinct signals — surfaced as a
status bar at the top of each workspace tab so staff can spot 'we
haven't uploaded in a month' separately from 'no new declarations have
been processed in a month'.
"""
from __future__ import annotations

from datetime import datetime, date

from app.database import connect


_DATA_QUERIES: dict[str, str] = {
    # Most recent customs declaration in DB, NOT most recent ingest.
    "bcct": """
        select max(registration_date)
        from hub.bcct_rows where client_id = %s
    """,
    "catalog": """
        select max(updated_at) from hub.materials where client_id = %s
    """,
    "bqd": """
        select max(created_at) from hub.code_mappings where client_id = %s
    """,
    # Active versions only — tombstoned ones don't represent live state.
    "bom": """
        select max(created_at) from hub.bom_versions
        where client_id = %s and tombstoned_at is null
    """,
}


def tab_freshness(client_id: str, module: str) -> dict:
    """Return {last_upload_at, last_data_at} for a client+module.

    last_upload_at: timestamp of most recent successful upload of this
        module (None if no upload has succeeded).
    last_data_at: timestamp/date of most recent data row in DB
        (semantically: 'how stale is the underlying data, regardless of
        upload cadence?').

    Both keys are always present; values are None when the module has
    no rows yet. Caller renders '—' for None.

    Single round-trip: one SELECT with two scalar subqueries.
    """
    if module not in _DATA_QUERIES:
        raise ValueError(f"unknown module: {module}")

    sql = f"""
        select
          (select max(parsed_at) from hub.file_uploads
             where client_id = %s and module = %s
               and parse_status = 'done'),
          ({_DATA_QUERIES[module]})
    """
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, (client_id, module, client_id))
            last_upload_at, last_data_at = cur.fetchone()

    return {
        "last_upload_at": last_upload_at,
        "last_data_at": last_data_at,
    }


def humanize_age(when: datetime | date | None, *, lang: str = "vi") -> str:
    """'2 ngày trước' / '17 days ago' / '—' shorthand for the staleness
    bar. Coarse-grained (minutes/hours/days/months); precision beyond
    'days' isn't useful for this signal."""
    if when is None:
        return "—"
    if isinstance(when, datetime):
        delta = datetime.now(when.tzinfo) - when
    else:
        delta = datetime.now().date() - when
        delta = type("D", (), {"total_seconds": lambda self=None, d=delta: d.days * 86400})()

    secs = int(delta.total_seconds())
    if secs < 0:
        secs = 0

    days = secs // 86400
    if days >= 365:
        years = days // 365
        return _label(years, "năm trước", "years ago", lang)
    if days >= 30:
        months = days // 30
        return _label(months, "tháng trước", "months ago", lang)
    if days >= 1:
        return _label(days, "ngày trước", "days ago", lang)
    hours = secs // 3600
    if hours >= 1:
        return _label(hours, "giờ trước", "hours ago", lang)
    minutes = secs // 60
    if minutes >= 1:
        return _label(minutes, "phút trước", "minutes ago", lang)
    return "vừa xong" if lang == "vi" else "just now"


def _label(n: int, vi: str, en: str, lang: str) -> str:
    return f"{n} {vi}" if lang == "vi" else f"{n} {en}"


_DATA_LABEL_KEY: dict[str, str] = {
    "bcct": "staleness.most_recent_decl",
    "catalog": "staleness.most_recent_data",
    "bqd": "staleness.most_recent_data",
    "bom": "staleness.most_recent_bom",
}


def _format_when(when) -> str | None:
    """Pre-render datetimes with HH:MM, dates as just the date."""
    if when is None:
        return None
    if isinstance(when, datetime):
        return when.strftime("%Y-%m-%d %H:%M")
    return when.strftime("%Y-%m-%d")


def freshness_for_template(request, client_id: str, module: str) -> dict:
    """One-shot helper: return the dict shape the
    `clients/_staleness_bar.html` partial expects.

    Pre-renders timestamp strings + relative-age strings + the
    module-specific data label using the request's lang cookie so
    templates stay declarative.
    """
    from app import i18n

    lang = i18n.normalize_lang(request.cookies.get("data_hub_lang"))
    raw = tab_freshness(client_id, module)
    return {
        "last_upload_at": _format_when(raw["last_upload_at"]),
        "last_data_at": _format_when(raw["last_data_at"]),
        "upload_age": humanize_age(raw["last_upload_at"], lang=lang),
        "data_age": humanize_age(raw["last_data_at"], lang=lang),
        "data_label": i18n.t(_DATA_LABEL_KEY[module], lang=lang),
        "any": raw["last_upload_at"] is not None or raw["last_data_at"] is not None,
    }
