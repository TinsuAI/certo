"""Mig 047 — catalog_candidates state-machine table + materials.code_kind +
Phase 2 manual fields. Drops catalog_derive_configs."""
from __future__ import annotations

from app.database import connect


def _columns(table: str) -> set[str]:
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "select column_name from information_schema.columns "
            "where table_schema='hub' and table_name=%s",
            (table,),
        )
        return {r[0] for r in cur.fetchall()}


def _table_exists(table: str) -> bool:
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "select 1 from information_schema.tables "
            "where table_schema='hub' and table_name=%s",
            (table,),
        )
        return cur.fetchone() is not None


def test_catalog_candidates_table_exists():
    assert _table_exists("catalog_candidates")


def test_catalog_candidates_has_required_columns():
    cols = _columns("catalog_candidates")
    expected = {
        "candidate_id", "client_id", "code", "code_kind",
        "sources", "observed_count", "first_seen", "last_seen",
        "sample_text", "suggested_category", "multi_direction",
        "status", "decided_at", "decided_by", "decision_reason",
        "created_at", "updated_at",
    }
    missing = expected - cols
    assert not missing, f"missing columns: {missing}"


def test_catalog_candidates_unique_index():
    """Unique on (client_id, code, code_kind) — same string can be both nb+hq."""
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "select indexdef from pg_indexes where schemaname='hub' "
            "and tablename='catalog_candidates'"
        )
        defs = [r[0] for r in cur.fetchall()]
    assert any(
        "client_id" in d and "code" in d and "code_kind" in d
        and ("UNIQUE" in d or "unique" in d)
        for d in defs
    ), f"missing unique idx on (client_id, code, code_kind); got: {defs}"


def test_materials_has_code_kind_column():
    cols = _columns("materials")
    assert "code_kind" in cols


def test_materials_has_phase2_manual_columns():
    cols = _columns("materials")
    expected = {"production_source", "supplier_hint", "uom"}
    missing = expected - cols
    assert not missing, f"missing Phase 2 columns: {missing}"


def test_catalog_derive_configs_dropped():
    assert not _table_exists("catalog_derive_configs"), (
        "mig 047 should DROP catalog_derive_configs (replaced by candidate feed)"
    )


def test_code_kind_check_constraint_accepts_valid_values():
    """code_kind enum: 'nb' | 'hq' | 'unified'."""
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "insert into hub.clients (client_id, name) values "
            "('_test_kind_client', 'kind test') on conflict do nothing"
        )
        for kind in ("nb", "hq", "unified"):
            cur.execute("delete from hub.materials where client_id='_test_kind_client'")
            cur.execute(
                "insert into hub.materials (client_id, material_code, name, "
                "category, status, source, code_kind) "
                "values ('_test_kind_client', %s, 'x', 'nvl', 'active', "
                "'client_declared', %s)",
                (f"TEST_{kind}", kind),
            )
        cur.execute("delete from hub.materials where client_id='_test_kind_client'")
        cur.execute("delete from hub.clients where client_id='_test_kind_client'")


def test_code_kind_check_constraint_rejects_invalid():
    import psycopg
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "insert into hub.clients (client_id, name) values "
            "('_test_kind_bad', 'bad kind') on conflict do nothing"
        )
        try:
            try:
                cur.execute(
                    "insert into hub.materials (client_id, material_code, name, "
                    "category, status, source, code_kind) "
                    "values ('_test_kind_bad', 'X', 'x', 'nvl', 'active', "
                    "'client_declared', 'invalid_kind')"
                )
                raise AssertionError("expected check-constraint violation")
            except psycopg.errors.CheckViolation:
                pass
        finally:
            conn.rollback()
            with connect() as c2, c2.cursor() as cur2:
                cur2.execute("delete from hub.clients where client_id='_test_kind_bad'")


def test_status_check_constraint_on_candidates():
    """status: 'pending' | 'accepted' | 'rejected'."""
    import psycopg
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "insert into hub.clients (client_id, name) values "
            "('_test_status', 'status test') on conflict do nothing"
        )
        try:
            try:
                cur.execute(
                    "insert into hub.catalog_candidates (client_id, code, code_kind, status) "
                    "values ('_test_status', 'X', 'nb', 'bogus_status')"
                )
                raise AssertionError("expected check-constraint violation")
            except psycopg.errors.CheckViolation:
                pass
        finally:
            conn.rollback()
            with connect() as c2, c2.cursor() as cur2:
                cur2.execute(
                    "delete from hub.catalog_candidates where client_id='_test_status'"
                )
                cur2.execute("delete from hub.clients where client_id='_test_status'")
