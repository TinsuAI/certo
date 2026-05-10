"""Per-client data export/import for dev→demo promotion and onboarding.

See .ai/features/2026-05-04-data-promotion/brief.md for the design.

Bundle format (tar.gz):

  manifest.json                  metadata
  db/NNN_<table>.sql             one INSERT-per-row file per table
  files/<module>/<client>/...    appfiles mirror, scoped to the client

Allow-list (TABLES) intentionally excludes per-deployment data
(chat_threads, llm_usage, notifications, upload_pending, sessions,
service_accounts, user_managed_clients, user_client_access). Those are
operational/auth state, not customer truth, and should never travel
between deployments.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import tarfile
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path
from typing import Iterable

from psycopg import sql
from psycopg.types.json import Jsonb

from app.database import connect


FORMAT_VERSION = 1

# Match the convention enforced elsewhere on client_id columns: lowercase
# alphanumerics, hyphens, underscores. Refuses anything that could be a
# path traversal segment (`..`, `/`, etc.) when used as a directory name.
_CLIENT_ID_RE = re.compile(r"^[a-z0-9][a-z0-9_-]*$")


class SchemaVersionMismatch(RuntimeError):
    """Raised when a bundle's schema_version does not equal the target's."""


class UnsupportedBundleFormat(RuntimeError):
    """Raised when a bundle's format_version is unknown to this code."""


class CorruptBundle(RuntimeError):
    """Raised when a bundle is missing required members or unreadable."""


@dataclass(frozen=True)
class TableSpec:
    """One entry in the export allow-list.

    `where_template` is a psycopg SQL template restricting rows to a
    single client. For tables that scope by `client_id` directly it's
    a simple `client_id = %s` clause. For child tables (e.g.
    bom_artifact_rows) it joins through the parent's client_id.

    `null_columns` lists columns whose values must NOT travel — typically
    FKs to per-deployment tables (e.g. hub.users) where the source's IDs
    are meaningless on the target. Export emits these as NULL.
    """

    name: str
    where_template: sql.Composable
    order: int
    null_columns: tuple[str, ...] = ()
    # Set True for tables whose FK to hub.clients is `ON DELETE SET NULL`
    # (not CASCADE). Replace mode must explicitly DELETE these BEFORE
    # the cascade from hub.clients, otherwise the rows survive with a
    # NULLed client_id and the bundle's INSERT hits a PK conflict.
    pre_delete: bool = False


# Parent-first order. on-delete-cascade from hub.clients takes care of
# deletion on import; we still order INSERTs to satisfy non-cascade FKs
# (e.g. bom_artifact_rows → bom_artifacts.artifact_id).
TABLES: tuple[TableSpec, ...] = (
    TableSpec("clients",               sql.SQL("client_id = %s"),                                              order=10),
    TableSpec("client_config",         sql.SQL("client_id = %s"),                                              order=20, null_columns=("updated_by",)),
    TableSpec("file_uploads",          sql.SQL("client_id = %s"),                                              order=25, pre_delete=True),
    TableSpec("parser_mappings",       sql.SQL("client_id = %s"),                                              order=30, null_columns=("confirmed_by",)),
    TableSpec("code_mappings",         sql.SQL("client_id = %s"),                                              order=40),
    TableSpec("materials",             sql.SQL("client_id = %s"),                                              order=50),
    TableSpec("client_uom_overrides",  sql.SQL("client_id = %s"),                                              order=58),
    TableSpec("bcct_rows",             sql.SQL("client_id = %s"),                                              order=60),
    TableSpec("bcct_material_identity_review", sql.SQL("client_id = %s"),                                       order=65),
    TableSpec("bom_artifacts",          sql.SQL("client_id = %s"),                                              order=70),
    TableSpec(
        "bom_artifact_rows",
        sql.SQL("artifact_id in (select artifact_id from hub.bom_artifacts where client_id = %s)"),
        order=75,
    ),
    TableSpec("bom_flatten_decisions", sql.SQL("client_id = %s"),                                              order=78, null_columns=("confirmed_by",)),
    TableSpec("bom_presets", sql.SQL("client_id = %s"),                                            order=80, null_columns=("created_by",)),
    TableSpec("bom_change_requests",   sql.SQL("client_id = %s"),                                              order=85),
    TableSpec("customs_declaration_files", sql.SQL("client_id = %s"),                                          order=90),
    TableSpec("material_substitutes",  sql.SQL("client_id = %s"),                                              order=95),
)


# Audit tables that the cascade-DELETE on hub.clients triggers populate
# (e.g. trg_bcct_row_history fires on bcct_rows DELETE). Without explicit
# cleanup, every replace-import grows bcct_row_history by 23k+ rows for a
# Growatt-sized client. We can't disable the trigger as a non-superuser,
# so instead we DELETE these tables WHERE client_id = X right before
# bundle INSERTs. Trade-off: pre-import audit history for this client is
# lost; but it's per-deployment audit anyway, and the alternative is
# unbounded growth.
AUDIT_TABLES_TO_PURGE_ON_IMPORT = (
    "bcct_row_history",
    "material_audit_events",
    "bom_audit_events",
)


# Tables that legitimately have a `client_id` column but are deliberately
# excluded from the bundle. Listed here so the schema-evolution self-check
# can distinguish "intentionally excluded" from "forgotten new table."
EXCLUDED_CLIENT_SCOPED_TABLES = frozenset({
    "user_managed_clients",    # per-deployment auth state
    "user_client_access",      # per-deployment auth state
    "chat_threads",            # per-deployment user activity
    "chat_messages",           # per-deployment user activity
    "llm_usage",               # per-deployment metrics
    "notifications",           # per-deployment user-facing
    "upload_pending",          # transient staging state
    "background_jobs",         # per-deployment job log; not business data
    # Audit tables — no FK to clients, survive cascade by design. The
    # cascade-DELETE on bcct_rows fires `trg_bcct_row_history` and
    # produces fresh per-deployment history entries on import. Trying
    # to ship audit rows across deployments would PK-conflict on
    # bigserial IDs anyway.
    "bcct_row_history",        # trigger-driven audit on bcct_rows
    "material_audit_events",   # audit log
    "bom_audit_events",        # audit log
    # Per-deployment review queue. Re-derives from BCCT/BOM/code_mappings
    # on the destination via refresh_candidates() — no need to ship rows.
    "catalog_candidates",
    # Per-deployment parser rules + computed view (not a real table). The
    # rules are mig-seeded and tuned per-deployment; v_material_roles is
    # a view, picked up automatically by schema replay.
    "client_parser_rules",
    "v_material_roles",
})


def _audit_allow_list(cur) -> list[str]:
    """Return names of `client_id`-scoped hub.* tables that are neither
    in the export allow-list nor in EXCLUDED_CLIENT_SCOPED_TABLES.

    Empty result = the schema is fully accounted for. A non-empty result
    means a future migration added a new client-scoped table that hasn't
    been triaged. Callers should warn loudly so the operator knows the
    bundle may silently miss data.
    """
    cur.execute(
        """
        select table_name
        from information_schema.columns
        where table_schema = 'hub' and column_name = 'client_id'
        """,
    )
    seen = {r[0] for r in cur.fetchall()}
    known = {spec.name for spec in TABLES} | EXCLUDED_CLIENT_SCOPED_TABLES
    return sorted(seen - known)


def _files_root() -> Path:
    return Path(os.environ.get("DATA_HUB_FILES_ROOT", "data/files")).resolve()


def _schema_version(cur) -> str:
    cur.execute("select max(filename) from hub.schema_migrations")
    row = cur.fetchone()
    if row is None or row[0] is None:
        raise RuntimeError("hub.schema_migrations is empty — cannot export")
    return row[0]


def _verify_client_exists(cur, client_id: str) -> None:
    cur.execute("select 1 from hub.clients where client_id = %s", (client_id,))
    if cur.fetchone() is None:
        raise LookupError(f"unknown client_id: {client_id!r}")


def _column_info(cur, table: str) -> list[tuple[str, str]]:
    """Return [(column_name, data_type), ...] in ordinal order.

    Skips GENERATED ALWAYS columns — Postgres refuses INSERTs that
    supply explicit values for them (`column ... can only be updated
    to DEFAULT`). The generated value is recomputed from its source
    columns at import time, so dropping it from the bundle is correct.
    """
    cur.execute(
        """
        select column_name, data_type
        from information_schema.columns
        where table_schema = 'hub'
          and table_name = %s
          and is_generated <> 'ALWAYS'
        order by ordinal_position
        """,
        (table,),
    )
    return [(r[0], r[1]) for r in cur.fetchall()]


def _dump_table(cur, spec: TableSpec, client_id: str) -> str:
    """Return SQL text containing one INSERT per row for the table."""
    info = _column_info(cur, spec.name)
    if not info:
        return ""
    cols = [c for c, _ in info]
    types = [t for _, t in info]
    null_idxs = {i for i, c in enumerate(cols) if c in spec.null_columns}
    select_stmt = sql.SQL("select {cols} from {tbl} where {where}").format(
        cols=sql.SQL(", ").join(map(sql.Identifier, cols)),
        tbl=sql.Identifier("hub", spec.name),
        where=spec.where_template,
    )
    cur.execute(select_stmt, (client_id,))
    rows = cur.fetchall()
    if not rows:
        return f"-- hub.{spec.name}: 0 rows\n"

    lines = [f"-- hub.{spec.name}: {len(rows)} rows"]
    cols_clause = sql.SQL(", ").join(map(sql.Identifier, cols))
    tbl = sql.Identifier("hub", spec.name)
    for row in rows:
        vals_clause = sql.SQL(", ").join(
            sql.Literal(None if i in null_idxs else _for_literal(v, types[i]))
            for i, v in enumerate(row)
        )
        stmt = sql.SQL("insert into {tbl} ({cols}) values ({vals})").format(
            tbl=tbl, cols=cols_clause, vals=vals_clause,
        )
        lines.append(stmt.as_string(cur) + ";")
    return "\n".join(lines) + "\n"


def _for_literal(value, data_type: str):
    """Type-aware wrap for sql.Literal.

    Only wrap dict/list as Jsonb when the column is actually json/jsonb.
    For ARRAY columns (text[] etc.), psycopg's default adapter renders
    Python list as a PG array literal — wrapping as Jsonb would generate
    a `'[...]'::jsonb` cast that fails type-check on re-INSERT.
    """
    if isinstance(value, (dict, list)) and data_type in ("jsonb", "json"):
        return Jsonb(value)
    return value


def _add_bytes_to_tar(tar: tarfile.TarFile, name: str, data: bytes) -> None:
    info = tarfile.TarInfo(name=name)
    info.size = len(data)
    info.mtime = int(datetime.now(timezone.utc).timestamp())
    tar.addfile(info, BytesIO(data))


def _add_client_files_to_tar(tar: tarfile.TarFile, client_id: str) -> int:
    root = _files_root()
    if not root.exists():
        return 0
    count = 0
    for module_dir in sorted(p for p in root.iterdir() if p.is_dir()):
        client_dir = module_dir / client_id
        if not client_dir.exists() or not client_dir.is_dir():
            continue
        for entry in sorted(client_dir.rglob("*")):
            if entry.is_file():
                rel = entry.relative_to(root)
                tar.add(entry, arcname=f"files/{rel.as_posix()}")
                count += 1
    return count


def export_client(*, client_id: str, out_path: Path | str, source: str | None = None) -> dict:
    """Bundle all data for `client_id` into a tar.gz at out_path.

    Returns the manifest dict. Raises LookupError if the client doesn't
    exist (no partial bundle is written).
    """
    out_path = Path(out_path)
    with connect() as conn, conn.cursor() as cur:
        _verify_client_exists(cur, client_id)
        schema_version = _schema_version(cur)
        unaccounted = _audit_allow_list(cur)
        if unaccounted:
            # A new migration added a client-scoped table that nobody
            # triaged into the allow-list or the exclusion list. Loud
            # warning beats silent data loss in the bundle.
            import warnings
            warnings.warn(
                f"data_promotion: {len(unaccounted)} client-scoped hub.* "
                f"tables are not triaged: {unaccounted}. Add them to TABLES "
                f"or EXCLUDED_CLIENT_SCOPED_TABLES in app/data_promotion.py.",
                stacklevel=2,
            )

        manifest = {
            "format_version": FORMAT_VERSION,
            "client_id": client_id,
            "schema_version": schema_version,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "source": source or os.environ.get("DATA_HUB_DEPLOYMENT_NAME", "unknown"),
        }

        sql_payloads: list[tuple[str, bytes]] = []
        for spec in sorted(TABLES, key=lambda s: s.order):
            body = _dump_table(cur, spec, client_id)
            if body:
                fname = f"db/{spec.order:03d}_{spec.name}.sql"
                sql_payloads.append((fname, body.encode("utf-8")))

    out_path.parent.mkdir(parents=True, exist_ok=True)
    with tarfile.open(out_path, "w:gz") as tar:
        _add_bytes_to_tar(tar, "manifest.json",
                          json.dumps(manifest, indent=2, sort_keys=True).encode("utf-8"))
        for name, data in sql_payloads:
            _add_bytes_to_tar(tar, name, data)
        _add_client_files_to_tar(tar, client_id)
    return manifest


def _read_manifest(tar: tarfile.TarFile) -> dict:
    try:
        member = tar.getmember("manifest.json")
    except KeyError as exc:
        raise CorruptBundle("manifest.json missing from bundle") from exc
    extracted = tar.extractfile(member)
    if extracted is None:
        raise CorruptBundle("manifest.json is unreadable")
    return json.loads(extracted.read().decode("utf-8"))


def _extract_files_to_staging(tar: tarfile.TarFile, staging: Path) -> int:
    """Extract `files/*` members under staging, refusing path-traversal.

    Refuses `files/../escape.txt` style attacks via resolved-path check
    before DB or files-root is touched. Symlinks and hardlinks under
    `files/` are refused outright (rather than silently dropped) so a
    malicious bundle can't substitute a tampered file via link.
    """
    staging = staging.resolve()
    staging.mkdir(parents=True, exist_ok=True)
    count = 0
    for member in tar.getmembers():
        if not member.name.startswith("files/"):
            continue
        rel = member.name[len("files/"):]
        if not rel:
            continue
        if member.issym() or member.islnk():
            raise CorruptBundle(
                f"bundle member is a link, refusing: {member.name!r}"
            )
        if not member.isfile():
            continue
        dest = (staging / rel).resolve()
        try:
            dest.relative_to(staging)
        except ValueError as exc:
            raise CorruptBundle(
                f"bundle member escapes files root: {member.name!r}"
            ) from exc
        dest.parent.mkdir(parents=True, exist_ok=True)
        extracted = tar.extractfile(member)
        if extracted is None:
            continue
        dest.write_bytes(extracted.read())
        count += 1
    return count


def _purge_client_files(target_root: Path, client_id: str) -> None:
    """Remove every `<target_root>/<module>/<client_id>/` directory.

    The bundle is the source of truth for this client_id; any pre-existing
    files on the target under that client must go before Phase 3 moves
    in the bundle's set. Other clients in the same module are untouched.
    """
    if not target_root.exists():
        return
    for module_dir in target_root.iterdir():
        if not module_dir.is_dir() or module_dir.name.startswith(".staging-"):
            continue
        client_dir = module_dir / client_id
        if client_dir.exists() and client_dir.is_dir():
            shutil.rmtree(client_dir)


def _move_staging_into_files_root(staging: Path, target_root: Path) -> None:
    """Move every file from staging into target_root, preserving relative
    paths. Best-effort: if a single move fails, partially-moved files
    remain — but the DB transaction has already committed by this point,
    so the alternative (rollback after commit) is not possible."""
    target_root.mkdir(parents=True, exist_ok=True)
    for src in staging.rglob("*"):
        if not src.is_file():
            continue
        rel = src.relative_to(staging)
        dest = target_root / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        os.replace(src, dest)  # atomic on the same filesystem


def import_client_bundle(*, bundle_path: Path | str) -> dict:
    """Restore a per-client bundle into the current DB + files root.

    Replace mode: deletes the target's existing rows for this client_id
    (cascade via hub.clients), then re-inserts from the bundle. Files
    are restored to DATA_HUB_FILES_ROOT preserving relative paths.

    Refuses to start if the bundle's schema_version doesn't match the
    target DB's max applied migration filename. The check is exact —
    we don't auto-migrate bundle data across schema changes.

    Atomicity: file extraction is staged in a temp dir (validates paths
    + fails fast on disk errors). Only after the DB transaction commits
    do staged files move into DATA_HUB_FILES_ROOT. So if the file phase
    fails, the DB is rolled back; the small remaining window is "DB
    committed, mid-way through moving files," which uses os.replace
    (atomic per file) to keep that window narrow.
    """
    bundle_path = Path(bundle_path)
    if not bundle_path.exists():
        raise FileNotFoundError(str(bundle_path))

    # Stage under files_root so os.replace in Phase 3 stays on the same
    # filesystem. Default tempdir (/tmp) is typically a different mount
    # in Docker deployments — would raise EXDEV on the move.
    files_root = _files_root()
    files_root.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=".staging-import-", dir=files_root))
    try:
        with tarfile.open(bundle_path, "r:gz") as tar:
            manifest = _read_manifest(tar)
            if manifest.get("format_version") != FORMAT_VERSION:
                raise UnsupportedBundleFormat(
                    f"bundle format_version={manifest.get('format_version')!r} "
                    f"is not supported (this code expects {FORMAT_VERSION})"
                )
            client_id = manifest.get("client_id")
            if not client_id:
                raise CorruptBundle("manifest.client_id is missing")
            if not isinstance(client_id, str) or not _CLIENT_ID_RE.match(client_id):
                # Defense in depth: client_id flows into a filesystem path
                # in _purge_client_files. A value like '..' or 'foo/bar'
                # would let a malicious bundle wipe arbitrary dirs under
                # files_root.
                raise CorruptBundle(
                    f"manifest.client_id {client_id!r} contains "
                    "characters not allowed in a client_id"
                )

            # Phase 1: extract files to staging. Path-traversal check
            # happens here, before any DB write.
            files_count = _extract_files_to_staging(tar, staging)

            sql_members = sorted(
                (m for m in tar.getmembers()
                 if m.isfile() and m.name.startswith("db/") and m.name.endswith(".sql")),
                key=lambda m: m.name,
            )
            # Refuse `db/*.sql` filenames outside the export's allow-list.
            # Otherwise a forged bundle could ship `db/999_arbitrary.sql`
            # whose contents we'd execute as raw SQL on the target.
            allowed_sql_names = {
                f"db/{spec.order:03d}_{spec.name}.sql" for spec in TABLES
            }
            for m in sql_members:
                if m.name not in allowed_sql_names:
                    raise CorruptBundle(
                        f"unexpected db/*.sql file in bundle: {m.name!r}"
                    )

            # Phase 2: DB transaction. If anything raises, the context
            # manager rolls back; staged files are cleaned up in finally.
            with connect() as conn, conn.cursor() as cur:
                target_version = _schema_version(cur)
                bundle_version = manifest.get("schema_version")
                if bundle_version != target_version:
                    raise SchemaVersionMismatch(
                        f"bundle schema_version={bundle_version!r} "
                        f"does not match target {target_version!r}"
                    )
                # Pre-DELETE for tables that don't cascade-delete from
                # hub.clients (would otherwise PK-conflict on re-INSERT).
                for spec in TABLES:
                    if spec.pre_delete:
                        cur.execute(
                            sql.SQL("delete from {tbl} where client_id = %s").format(
                                tbl=sql.Identifier("hub", spec.name),
                            ),
                            (client_id,),
                        )
                cur.execute(
                    "delete from hub.clients where client_id = %s",
                    (client_id,),
                )
                # Cascade-DELETE on bcct_rows/etc fires audit triggers
                # that insert spurious history for this client. Wipe
                # those (and any pre-existing per-client audit) before
                # bundle INSERTs. Otherwise repeated imports balloon
                # the audit tables.
                for tbl in AUDIT_TABLES_TO_PURGE_ON_IMPORT:
                    cur.execute(
                        sql.SQL("delete from {tbl} where client_id = %s").format(
                            tbl=sql.Identifier("hub", tbl),
                        ),
                        (client_id,),
                    )
                for m in sql_members:
                    extracted = tar.extractfile(m)
                    if extracted is None:
                        continue
                    body = extracted.read().decode("utf-8")
                    if body.strip():
                        # body is a multi-INSERT script; psycopg3 routes
                        # the no-params path through libpq's PQexec which
                        # accepts multiple statements. Don't add %s
                        # placeholders here — that would break it.
                        cur.execute(body)

        # Phase 3: DB committed; clear stale per-client files on the
        # target, then move staged files in (same filesystem).
        _purge_client_files(files_root, client_id)
        _move_staging_into_files_root(staging, files_root)

    finally:
        shutil.rmtree(staging, ignore_errors=True)

    return {
        "client_id": client_id,
        "schema_version": bundle_version,
        "sql_files_applied": len(sql_members),
        "files_restored": files_count,
    }
