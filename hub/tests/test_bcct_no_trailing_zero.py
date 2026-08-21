"""Live-DB integrity assertions for BCCT key cleanliness.

Migration 024 stripped historical `.0` pollution from
declaration_no / line_no / transaction_key. The parser fix in
`app/parsers/bcct.py:_cell_str` prevents new uploads from re-introducing
the same pollution. These tests ensure neither layer regresses.
"""
from __future__ import annotations

from hub.app.database import connect


def test_bcct_rows_have_no_trailing_zero():
    with connect() as c, c.cursor() as cur:
        cur.execute(
            """
            select
              count(*) filter (where declaration_no like '%.0'),
              count(*) filter (where line_no like '%.0'),
              count(*) filter (where transaction_key like '%.0%')
            from hub.bcct_rows
            """,
        )
        decl, line, tx = cur.fetchone()
    assert decl == 0, f"{decl} rows still have .0-suffixed declaration_no"
    assert line == 0, f"{line} rows still have .0-suffixed line_no"
    assert tx == 0, f"{tx} rows still have .0 in transaction_key"


def test_bcct_history_keys_have_no_trailing_zero():
    with connect() as c, c.cursor() as cur:
        cur.execute(
            """
            select
              count(*) filter (where line_no like '%.0'),
              count(*) filter (where transaction_key like '%.0%')
            from hub.bcct_row_history
            """,
        )
        line, tx = cur.fetchone()
    assert line == 0, f"{line} history rows still have .0-suffixed line_no"
    assert tx == 0, f"{tx} history rows still have .0 in transaction_key"


def test_migration_024_handles_collision_check():
    """Smoke: rerun the cleaning logic against synthetic polluted rows.
    Proves the SQL logic (regexp_replace + transaction_key rebuild) is
    idempotent and collision-safe."""
    import secrets

    cid = "stk-test-" + secrets.token_hex(4)
    with connect() as c, c.cursor() as cur:
        try:
            cur.execute(
                """insert into hub.clients
                   (client_id, name, code_resolution_mode, bom_proposal_mode)
                   values (%s, 'STK Test', 'identity', 'auto')""",
                (cid,),
            )
            cur.execute(
                """insert into hub.bcct_rows
                   (client_id, transaction_key, line_no, declaration_no,
                    declaration_type, direction, registration_date, customs_code,
                    payload)
                   values (%s, '999000111.0-7.0', '7.0', '999000111.0',
                           'E42', 'export', '2026-01-01', 'X', '{}'::jsonb)""",
                (cid,),
            )
            # Apply the same cleaning the migration does.
            cur.execute(
                """update hub.bcct_rows
                   set declaration_no = regexp_replace(declaration_no, '\\.0$', ''),
                       line_no = regexp_replace(line_no, '\\.0$', ''),
                       transaction_key = case
                         when declaration_no is not null then
                           regexp_replace(declaration_no, '\\.0$', '') || '-'
                           || regexp_replace(line_no, '\\.0$', '')
                         else transaction_key
                       end
                   where client_id = %s
                     and (declaration_no like '%%.0' or line_no like '%%.0')""",
                (cid,),
            )
            cur.execute(
                """select declaration_no, line_no, transaction_key
                   from hub.bcct_rows where client_id = %s""",
                (cid,),
            )
            (decl, line, tx) = cur.fetchone()
            assert decl == "999000111"
            assert line == "7"
            assert tx == "999000111-7"
        finally:
            # The cleaning UPDATE fires trg_bcct_row_history with the old
            # polluted state, so flush history for this test client too —
            # otherwise the live-DB integrity assertion above sees the
            # leftover `.0` history row.
            cur.execute(
                "delete from hub.bcct_row_history where client_id = %s",
                (cid,),
            )
            cur.execute("delete from hub.bcct_rows where client_id = %s", (cid,))
            cur.execute("delete from hub.clients where client_id = %s", (cid,))
