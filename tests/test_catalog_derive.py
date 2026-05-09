"""Phase 5+6 — catalog-derive tool: configs CRUD + preview + bulk-apply."""
from __future__ import annotations

import pytest

from app.database import connect


CLIENT = "derive_test_client"


@pytest.fixture(autouse=True)
def setup():
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "insert into hub.clients (client_id, name) values (%s, %s) "
            "on conflict do nothing",
            (CLIENT, "derive test"),
        )
        # Clean previous-run residues.
        cur.execute("delete from hub.bcct_rows where client_id=%s", (CLIENT,))
        cur.execute("delete from hub.materials where client_id=%s", (CLIENT,))
        cur.execute("delete from hub.catalog_derive_configs where client_id=%s", (CLIENT,))
        # Seed BCCT rows with codes in goods_name parens.
        bcct_rows = [
            ("D001", "1", "BUCKET-A", "(007.0050100) widget", "import", "E11"),
            ("D002", "1", "BUCKET-A", "(007.0050100) widget v2", "import", "E11"),
            ("D003", "1", "BUCKET-A", "(007.0050100) widget v3", "import", "E11"),
            ("D004", "1", "BUCKET-B", "(015.0052000) adapter", "import", "E11"),
        ]
        for decl, line, customs, goods, dirn, dtype in bcct_rows:
            cur.execute(
                """
                insert into hub.bcct_rows
                  (client_id, transaction_key, line_no, declaration_no,
                   declaration_type, direction, registration_date,
                   customs_code, goods_name, payload)
                values (%s, %s, %s, %s, %s, %s, '2026-04-01', %s, %s, '{}'::jsonb)
                on conflict do nothing
                """,
                (CLIENT, f"TX_{decl}_{line}", line, decl, dtype, dirn, customs, goods),
            )
    yield
    with connect() as conn, conn.cursor() as cur:
        cur.execute("delete from hub.catalog_derive_configs where client_id=%s", (CLIENT,))
        cur.execute("delete from hub.bcct_rows where client_id=%s", (CLIENT,))
        cur.execute("delete from hub.materials where client_id=%s", (CLIENT,))
        cur.execute("delete from hub.clients where client_id=%s", (CLIENT,))


def _seed_config(pattern: str, *, min_observed_count: int = 1,
                 default_category: str = "nvl"):
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            """
            insert into hub.catalog_derive_configs
              (client_id, name, source_table, pattern, source_field,
               match_group, min_observed_count, default_status,
               default_category, created_by, updated_by)
            values (%s, 'test', 'bcct_rows', %s, 'goods_name', 1, %s,
                    'under_review', %s, 'sys', 'sys')
            returning config_id
            """,
            (CLIENT, pattern, min_observed_count, default_category),
        )
        return cur.fetchone()[0]


def test_preview_returns_codes_not_yet_in_catalog():
    """Preview should surface codes appearing in BCCT goods_name parens
    that don't yet have a materials row."""
    from app.routes.catalog_derive import _run_preview, _get_config
    config_id = _seed_config(r"\((\d{3}\.[\w\-]+)\)")
    config = _get_config(CLIENT, config_id)
    rows = _run_preview(CLIENT, config, limit=50)
    codes = {r["code"] for r in rows}
    assert "007.0050100" in codes
    assert "015.0052000" in codes


def test_preview_anti_joins_existing_materials():
    """Codes already in materials should NOT appear in preview."""
    from app.routes.catalog_derive import _run_preview, _get_config
    # Seed an existing material for one of the codes.
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "insert into hub.materials (client_id, material_code, name, category) "
            "values (%s, '007.0050100', 'pre-existing', 'nvl')",
            (CLIENT,),
        )
    config_id = _seed_config(r"\((\d{3}\.[\w\-]+)\)")
    config = _get_config(CLIENT, config_id)
    rows = _run_preview(CLIENT, config, limit=50)
    codes = {r["code"] for r in rows}
    assert "007.0050100" not in codes  # already in catalog → excluded
    assert "015.0052000" in codes      # not in catalog → included


def test_preview_min_observed_count_filters():
    """Codes appearing fewer times than min_observed_count are filtered."""
    from app.routes.catalog_derive import _run_preview, _get_config
    config_id = _seed_config(r"\((\d{3}\.[\w\-]+)\)", min_observed_count=2)
    config = _get_config(CLIENT, config_id)
    rows = _run_preview(CLIENT, config, limit=50)
    codes = {r["code"]: r["observed_count"] for r in rows}
    # 007.0050100 appears in 3 declarations → kept
    assert "007.0050100" in codes
    assert codes["007.0050100"] == 3
    # 015.0052000 appears in 1 declaration → filtered (min=2)
    assert "015.0052000" not in codes


def test_apply_inserts_codes_with_bcct_observed_source():
    """Bulk-apply inserts previewed codes with source='bcct_observed'."""
    from app.routes.catalog_derive import _run_apply, _get_config
    config_id = _seed_config(r"\((\d{3}\.[\w\-]+)\)")
    config = _get_config(CLIENT, config_id)
    n = _run_apply(CLIENT, config, actor="staff@example.com")
    assert n == 2  # 007.0050100 + 015.0052000
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "select material_code, source, status, category "
            "from hub.materials where client_id=%s order by material_code",
            (CLIENT,),
        )
        rows = cur.fetchall()
    assert len(rows) == 2
    for code, source, status, category in rows:
        assert source == "bcct_observed"
        assert status == "under_review"
        assert category == "nvl"


def test_apply_idempotent_on_existing_codes():
    """Re-applying after an Apply doesn't duplicate or error."""
    from app.routes.catalog_derive import _run_apply, _get_config
    config_id = _seed_config(r"\((\d{3}\.[\w\-]+)\)")
    config = _get_config(CLIENT, config_id)
    n1 = _run_apply(CLIENT, config, actor="staff@example.com")
    n2 = _run_apply(CLIENT, config, actor="staff@example.com")
    # Second run sees nothing new in preview (already in catalog), so n2=0.
    # But we run apply over the preview snapshot; it may re-execute the
    # preview query. Either way, no duplicate rows.
    assert n1 == 2
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "select count(*) from hub.materials where client_id=%s",
            (CLIENT,),
        )
        assert cur.fetchone()[0] == 2


def test_resolver_returns_resolved_pending_review_for_under_review_material():
    """When resolver hits a `bcct_observed/under_review` material, status
    should be `resolved_pending_review` (not just `resolved`)."""
    from app.parsers.derivations import compute_internal_code
    from app.resolvers.bcct_material_identity import (
        ResolverContext, resolve_material_identity,
    )
    # Seed an under_review material that matches the BCCT customs_code.
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "insert into hub.materials "
            "(client_id, material_code, name, category, status, source) "
            "values (%s, 'BUCKET-A', 'under-review code', 'nvl', "
            "'under_review', 'bcct_observed')",
            (CLIENT,),
        )
    row = {
        "customs_code": "BUCKET-A",
        "goods_name": "(007.0050100) widget",
        "direction": "import",
        "declaration_no": "D001",
        "line_no": "1",
    }
    row["internal_code"] = compute_internal_code(
        row, client={"client_id": CLIENT, "name": "test"},
    )
    with connect() as conn, conn.cursor() as cur:
        ctx = ResolverContext.from_db(CLIENT, cur)
    pid = resolve_material_identity(row, ctx=ctx)
    assert pid["resolved_code"] == "BUCKET-A"
    assert pid["resolution_status"] == "resolved_pending_review"
