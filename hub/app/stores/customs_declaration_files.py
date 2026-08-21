"""Persistence for hub.customs_declaration_files (TKX/TKN file metadata).

File contents are stored via `app.storage` (FileBackend); this module
holds the metadata + linkage to BCCT declarations. Per Feature 6 brief,
the same byte-identical upload is a no-op (sha256 dedupe inside
(client_id, declaration_no, direction)).
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Iterable

from app.database import connect


@dataclass(frozen=True)
class DeclarationFile:
    id: int
    client_id: str
    declaration_no: str
    direction: str           # 'import' | 'export'
    file_kind: str           # 'xls' | 'pdf' | 'scan' | 'other'
    backend_key: str
    original_filename: str
    declaration_date: date | None
    sha256: str
    size_bytes: int
    uploaded_by: str | None
    uploaded_at: datetime
    notes: str | None


def insert_declaration_file(
    *,
    client_id: str,
    declaration_no: str,
    direction: str,
    file_kind: str,
    backend_key: str,
    original_filename: str,
    sha256: str,
    size_bytes: int,
    declaration_date: date | None = None,
    uploaded_by: str | None = None,
    notes: str | None = None,
) -> tuple[int, bool]:
    """Insert metadata row. Returns (id, created).

    `created=False` when an idempotent no-op (same sha256 already exists
    for the same client/declaration/direction) — returns the existing id.
    """
    if direction not in ("import", "export"):
        raise ValueError(f"direction must be 'import' or 'export', got {direction!r}")
    if file_kind not in ("xls", "pdf", "scan", "other"):
        raise ValueError(f"file_kind invalid: {file_kind!r}")

    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            """
            insert into hub.customs_declaration_files
              (client_id, declaration_no, direction, file_kind, backend_key,
               original_filename, declaration_date, sha256, size_bytes,
               uploaded_by, notes)
            values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            on conflict (client_id, declaration_no, direction, sha256)
              do nothing
            returning id
            """,
            (client_id, declaration_no, direction, file_kind, backend_key,
             original_filename, declaration_date, sha256, size_bytes,
             uploaded_by, notes),
        )
        row = cur.fetchone()
        if row is not None:
            return row[0], True
        # Conflict: fetch existing.
        cur.execute(
            """
            select id from hub.customs_declaration_files
             where client_id=%s and declaration_no=%s
               and direction=%s and sha256=%s
            """,
            (client_id, declaration_no, direction, sha256),
        )
        existing = cur.fetchone()
        if existing is None:
            raise RuntimeError(
                "insert returned no id and conflict-fetch found no row "
                "(should not happen)",
            )
        return existing[0], False


def get_declaration_file(file_id: int) -> DeclarationFile | None:
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "select * from hub.customs_declaration_files where id=%s",
            (file_id,),
        )
        row = cur.fetchone()
        if row is None:
            return None
        cols = [d.name for d in cur.description]
        return DeclarationFile(**dict(zip(cols, row)))


def list_files_for_declaration(
    client_id: str, declaration_no: str, *, direction: str | None = None,
) -> list[DeclarationFile]:
    sql = """
        select * from hub.customs_declaration_files
         where client_id=%s and declaration_no=%s
    """
    params: list = [client_id, declaration_no]
    if direction is not None:
        sql += " and direction=%s"
        params.append(direction)
    sql += " order by uploaded_at desc, id desc"
    with connect() as conn, conn.cursor() as cur:
        cur.execute(sql, params)
        cols = [d.name for d in cur.description]
        return [DeclarationFile(**dict(zip(cols, r))) for r in cur.fetchall()]


def file_count_per_declaration(
    client_id: str, *, direction: str | None = None,
) -> dict[tuple[str, str], int]:
    """Returns {(declaration_no, direction): file_count}. For the BCCT
    row badge ("Có TK" / "Thiếu TK")."""
    sql = """
        select declaration_no, direction, count(*)
          from hub.customs_declaration_files
         where client_id=%s
    """
    params: list = [client_id]
    if direction is not None:
        sql += " and direction=%s"
        params.append(direction)
    sql += " group by declaration_no, direction"
    with connect() as conn, conn.cursor() as cur:
        cur.execute(sql, params)
        return {(d, dr): n for d, dr, n in cur.fetchall()}


@dataclass(frozen=True)
class DeclarationSummary:
    declaration_no: str
    direction: str
    bcct_line_count: int
    file_count: int
    earliest_bcct_date: date | None


def list_declarations_with_status(
    client_id: str, *,
    direction: str | None = None,
    has_files: bool | None = None,
    declaration_nos: list[str] | None = None,
    limit: int = 200,
    offset: int = 0,
    search: str | None = None,
) -> list[DeclarationSummary]:
    """List declarations from BCCT with attached file counts.

    Used for the declarations index page + sister-app declaration
    summary API. Combines bcct_rows aggregated by declaration with the
    file count from customs_declaration_files. Filters: direction
    (import/export), has_files (true/false/None), declaration_nos
    (exact-match list), search (substring match on declaration_no).
    """
    sql_parts = ["""
        with bcct_decls as (
            select declaration_no, direction,
                   count(*) as line_count,
                   min(registration_date) as earliest_date
              from hub.bcct_rows
             where client_id = %(cid)s
    """]
    params: dict = {"cid": client_id}
    if direction is not None:
        sql_parts.append("    and direction = %(dir)s")
        params["dir"] = direction
    if declaration_nos is not None:
        sql_parts.append("    and declaration_no = any(%(decls)s)")
        params["decls"] = list(declaration_nos)
    if search:
        sql_parts.append("    and declaration_no like %(srch)s")
        params["srch"] = f"%{search}%"
    sql_parts.append("""
            group by declaration_no, direction
        ),
        file_counts as (
            select declaration_no, direction, count(*) as file_count
              from hub.customs_declaration_files
             where client_id = %(cid)s
             group by declaration_no, direction
        )
        select b.declaration_no, b.direction, b.line_count,
               coalesce(f.file_count, 0) as file_count,
               b.earliest_date
          from bcct_decls b
          left join file_counts f
            on b.declaration_no = f.declaration_no
           and b.direction = f.direction
    """)
    if has_files is True:
        sql_parts.append(" where coalesce(f.file_count, 0) > 0")
    elif has_files is False:
        sql_parts.append(" where coalesce(f.file_count, 0) = 0")
    sql_parts.append(" order by b.earliest_date desc nulls last, b.declaration_no")
    sql_parts.append(" limit %(lim)s offset %(off)s")
    params["lim"] = limit
    params["off"] = offset

    with connect() as conn, conn.cursor() as cur:
        cur.execute("".join(sql_parts), params)
        return [
            DeclarationSummary(
                declaration_no=r[0], direction=r[1],
                bcct_line_count=r[2], file_count=r[3],
                earliest_bcct_date=r[4],
            )
            for r in cur.fetchall()
        ]


def count_declarations_with_status(
    client_id: str, *,
    direction: str | None = None,
    has_files: bool | None = None,
    declaration_nos: list[str] | None = None,
    search: str | None = None,
) -> int:
    """Total count for the same query as `list_declarations_with_status`.
    Used for pagination context."""
    sql_parts = ["""
        with bcct_decls as (
            select declaration_no, direction
              from hub.bcct_rows
             where client_id = %(cid)s
    """]
    params: dict = {"cid": client_id}
    if direction is not None:
        sql_parts.append("    and direction = %(dir)s")
        params["dir"] = direction
    if declaration_nos is not None:
        sql_parts.append("    and declaration_no = any(%(decls)s)")
        params["decls"] = list(declaration_nos)
    if search:
        sql_parts.append("    and declaration_no like %(srch)s")
        params["srch"] = f"%{search}%"
    sql_parts.append("""
            group by declaration_no, direction
        ),
        file_counts as (
            select declaration_no, direction, count(*) as file_count
              from hub.customs_declaration_files
             where client_id = %(cid)s
             group by declaration_no, direction
        )
        select count(*) from bcct_decls b
          left join file_counts f
            on b.declaration_no = f.declaration_no
           and b.direction = f.direction
    """)
    if has_files is True:
        sql_parts.append(" where coalesce(f.file_count, 0) > 0")
    elif has_files is False:
        sql_parts.append(" where coalesce(f.file_count, 0) = 0")
    with connect() as conn, conn.cursor() as cur:
        cur.execute("".join(sql_parts), params)
        return cur.fetchone()[0]


def list_files_for_declarations(
    client_id: str, declaration_nos: list[str], *, direction: str,
) -> list[DeclarationFile]:
    """Bulk fetch of every uploaded file for the (client, direction,
    declaration_no IN nos) tuple. Used by the ZIP download route. The
    return list is empty when nothing matches; the caller produces the
    NO_FILES_FOUND marker."""
    if not declaration_nos:
        return []
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            """
            select * from hub.customs_declaration_files
             where client_id = %s
               and direction = %s
               and declaration_no = any(%s)
             order by declaration_no, uploaded_at, id
            """,
            (client_id, direction, list(declaration_nos)),
        )
        cols = [d.name for d in cur.description]
        return [DeclarationFile(**dict(zip(cols, r))) for r in cur.fetchall()]


def delete_declaration_file(file_id: int) -> bool:
    """Delete metadata row. Caller is responsible for FileBackend cleanup
    (the backend_key isn't auto-removed)."""
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "delete from hub.customs_declaration_files where id=%s",
            (file_id,),
        )
        return cur.rowcount > 0
