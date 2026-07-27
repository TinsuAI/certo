"""Track C — UoM cross-source drift gate at ingest preview time.

Today UoM drift only surfaces:
- catalog detail (`_uom_drift` warning panel) — view-time, not gating.
- flatten engine (decisions emitted at materialize time).

Track C wires a helper that runs at BOM + BCCT upload preview to surface
drift between the parsed rows and existing catalog/BCCT data, with
3-tier severity:
- info: same canonical (PCS == PIECE) — display only, no gate.
- info: same family different canonical (gam ↔ kg) — display only;
  flatten will convert deterministically via uom_canonical.base_factor.
- warn: cross-family (mass vs count) — requires staff acknowledgement
  checkbox before confirm upload. Red flag for likely data corruption.

Helper signature:
    compute_uom_drifts(client_id, rows) → list[dict]
where each row carries `{material_code, uom}` and the result item is
`{material_code, source_uom, source_canonical, source_dim,
 catalog_uom, catalog_canonical, catalog_dim,
 bcct_uoms, severity: 'info_alias'|'info_family'|'warn_cross_family',
 message}`.

`info_alias` = synonym (no real drift), still surfaced for transparency
when material_code isn't yet in catalog.
"""
from __future__ import annotations

import pytest

from app.database import connect


CLIENT = "track_c_test"


@pytest.fixture(autouse=True)
def setup():
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "insert into hub.clients (client_id, name) values (%s, %s) "
            "on conflict (client_id) do nothing",
            (CLIENT, "track C test"),
        )
        # Seed some catalog + bcct fixtures.
        cur.execute(
            "insert into hub.materials (client_id, material_code, name, "
            "category, uom) values (%s, %s, %s, %s, %s) "
            "on conflict (client_id, material_code) do update set uom = "
            "excluded.uom",
            (CLIENT, "MASS_KG", "mass-as-kg material", "nvl", "kg"),
        )
        cur.execute(
            "insert into hub.materials (client_id, material_code, name, "
            "category, uom) values (%s, %s, %s, %s, %s) "
            "on conflict (client_id, material_code) do update set uom = "
            "excluded.uom",
            (CLIENT, "COUNT_PCS", "count material", "nvl", "pcs"),
        )
        cur.execute(
            "insert into hub.materials (client_id, material_code, name, "
            "category, uom) values (%s, %s, %s, %s, %s) "
            "on conflict (client_id, material_code) do update set uom = "
            "excluded.uom",
            (CLIENT, "ALIAS_PIECE", "alias-piece material", "nvl",
             "PIECE"),
        )
        # Material with no catalog UoM (drift impossible against catalog).
        cur.execute(
            "insert into hub.materials (client_id, material_code, name, "
            "category) values (%s, %s, %s, %s) "
            "on conflict (client_id, material_code) do nothing",
            (CLIENT, "NO_CATALOG_UOM", "no-uom material", "nvl"),
        )
    yield
    with connect() as conn, conn.cursor() as cur:
        cur.execute("delete from hub.materials where client_id=%s",
                    (CLIENT,))
        cur.execute("delete from hub.bcct_rows where client_id=%s",
                    (CLIENT,))
        cur.execute("delete from hub.clients where client_id=%s",
                    (CLIENT,))


# ─────────────────────────────────────────────────────────────────────
# Helper exists + signature.
# ─────────────────────────────────────────────────────────────────────


def test_helper_module_importable():
    from app.stores.uom_drift import compute_uom_drifts
    assert callable(compute_uom_drifts)


def test_no_drift_returns_empty_list():
    """Parsed row UoM matches catalog canonical → no drift entry."""
    from app.stores.uom_drift import compute_uom_drifts
    rows = [{"material_code": "MASS_KG", "uom": "kg"}]
    drifts = compute_uom_drifts(CLIENT, rows)
    assert drifts == [], f"identical UoM should produce no drift. Got: {drifts}"


def test_alias_synonym_is_info_alias_severity():
    """PIECE vs pcs (same canonical via aliases) → severity info_alias.
    Surfaces transparency but does not gate ingest."""
    from app.stores.uom_drift import compute_uom_drifts
    rows = [{"material_code": "ALIAS_PIECE", "uom": "pcs"}]
    drifts = compute_uom_drifts(CLIENT, rows)
    if not drifts:
        # Acceptable: alias resolution agreed → no drift entry at all.
        return
    assert len(drifts) == 1
    assert drifts[0]["severity"] == "info_alias"


def test_same_family_different_canonical_is_info_family():
    """gam vs kg — both family 'mass' but different canonical → info_family.
    Flatten engine will convert deterministically; no gate needed."""
    from app.stores.uom_drift import compute_uom_drifts
    rows = [{"material_code": "MASS_KG", "uom": "g"}]
    drifts = compute_uom_drifts(CLIENT, rows)
    assert len(drifts) == 1, f"expected 1 drift, got {drifts}"
    d = drifts[0]
    assert d["severity"] == "info_family", (
        f"same-family different-canonical should be info_family. "
        f"Got: {d['severity']!r}"
    )
    assert d["material_code"] == "MASS_KG"
    assert d["source_canonical"] == "g"
    assert d["catalog_canonical"] == "kg"


def test_cross_family_is_warn_severity():
    """File says 'kg' (mass) for material whose catalog says 'pcs'
    (count) → severity warn_cross_family. Gates upload until ack."""
    from app.stores.uom_drift import compute_uom_drifts
    rows = [{"material_code": "COUNT_PCS", "uom": "kg"}]
    drifts = compute_uom_drifts(CLIENT, rows)
    assert len(drifts) == 1
    d = drifts[0]
    assert d["severity"] == "warn_cross_family", (
        f"cross-family drift must be warn. Got: {d['severity']!r}"
    )
    assert d["source_dim"] == "mass"
    assert d["catalog_dim"] == "count"


def test_unknown_alias_either_side_is_info_unknown():
    """One or both sides has an alias not in uom_aliases → severity
    info_unknown. Helps staff add missing aliases."""
    from app.stores.uom_drift import compute_uom_drifts
    rows = [{"material_code": "MASS_KG", "uom": "zzz_unknown_alias"}]
    drifts = compute_uom_drifts(CLIENT, rows)
    assert len(drifts) == 1
    assert drifts[0]["severity"] == "info_unknown"


def test_no_catalog_uom_no_drift():
    """Material exists in catalog but has no UoM declared → can't drift
    against catalog."""
    from app.stores.uom_drift import compute_uom_drifts
    rows = [{"material_code": "NO_CATALOG_UOM", "uom": "kg"}]
    drifts = compute_uom_drifts(CLIENT, rows)
    # Should not warn (no catalog reference to disagree with).
    cat_drifts = [d for d in drifts if d.get("catalog_canonical")]
    assert cat_drifts == [], (
        f"no catalog UoM → no drift against catalog. Got: {cat_drifts}"
    )


def test_material_not_in_catalog_at_all_no_drift():
    """Code not in materials table → no drift (also not flagged as
    info_unknown — that's about UoM aliases, not catalog membership).
    Helper gracefully skips."""
    from app.stores.uom_drift import compute_uom_drifts
    rows = [{"material_code": "TOTALLY_UNSEEN_CODE", "uom": "kg"}]
    drifts = compute_uom_drifts(CLIENT, rows)
    assert drifts == []


def test_drift_against_bcct_history():
    """Catalog might be missing UoM, but BCCT historical rows have one.
    Helper falls back to most-common BCCT.unit when catalog lacks UoM."""
    from app.stores.uom_drift import compute_uom_drifts
    # Add bcct rows with UoM 'kg' for NO_CATALOG_UOM.
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "insert into hub.bcct_rows (client_id, declaration_no, "
            "line_no, transaction_key, customs_code, goods_name, "
            "unit, quantity, hs_code, direction, registration_date) "
            "values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
            (CLIENT, "DK_TEST_C", 1, "DK_TEST_C-1", "NO_CATALOG_UOM",
             "test", "kg", 100, "11111111", "import", "2026-01-01"),
        )
        conn.commit()
    rows = [{"material_code": "NO_CATALOG_UOM", "uom": "g"}]
    drifts = compute_uom_drifts(CLIENT, rows)
    assert len(drifts) == 1
    d = drifts[0]
    # Catalog has no UoM, but BCCT has 'kg' → drift against BCCT side
    # is same family (mass) different canonical = info_family.
    assert d["severity"] == "info_family"
    assert "kg" in d["bcct_uoms"]


def test_dedupes_repeated_rows():
    """If a single material appears multiple times in the upload with
    same UoM, helper emits ONE drift entry."""
    from app.stores.uom_drift import compute_uom_drifts
    rows = [
        {"material_code": "COUNT_PCS", "uom": "kg"},
        {"material_code": "COUNT_PCS", "uom": "kg"},
        {"material_code": "COUNT_PCS", "uom": "kg"},
    ]
    drifts = compute_uom_drifts(CLIENT, rows)
    assert len(drifts) == 1


def test_severity_sort_order():
    """When multiple materials drift, helper returns them sorted by
    severity (warn > info_*) so banner UI renders most-critical first."""
    from app.stores.uom_drift import compute_uom_drifts
    rows = [
        {"material_code": "MASS_KG", "uom": "g"},      # info_family
        {"material_code": "COUNT_PCS", "uom": "kg"},   # warn_cross_family
        {"material_code": "ALIAS_PIECE", "uom": "pcs"}, # info_alias or no drift
    ]
    drifts = compute_uom_drifts(CLIENT, rows)
    severities = [d["severity"] for d in drifts]
    # warn must precede info_* in the ordering.
    if "warn_cross_family" in severities and "info_family" in severities:
        assert severities.index("warn_cross_family") < severities.index("info_family")


def test_has_blocking_drift_helper():
    from app.stores.uom_drift import has_blocking_drift
    assert has_blocking_drift([{"severity": "warn_cross_family"}]) is True
    assert has_blocking_drift([{"severity": "info_family"}]) is False
    assert has_blocking_drift([
        {"severity": "info_family"},
        {"severity": "warn_cross_family"},
    ]) is True
    assert has_blocking_drift([]) is False


# ─────────────────────────────────────────────────────────────────────
# Route integration — banner appears in BOM + BCCT preview HTML.
# ─────────────────────────────────────────────────────────────────────


@pytest.fixture
def admin_client():
    from fastapi.testclient import TestClient
    from app.auth.session import (SESSION_COOKIE, create_session,
                                   hash_password)
    from app.main import app
    user_id = "u_track_c_admin"
    email = "track-c@test.local"
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "insert into hub.users (user_id, email, display_name, "
            "password_hash, role, status) values (%s, %s, 'Track C', "
            "%s, 'admin', 'active') on conflict (user_id) do update "
            "set role='admin', status='active'",
            (user_id, email, hash_password("test-pw")),
        )
    sess = create_session(user_id)
    c = TestClient(app)
    c.cookies.set(SESSION_COOKIE, sess)
    yield c
    with connect() as conn, conn.cursor() as cur:
        cur.execute("delete from hub.sessions where user_id=%s", (user_id,))
        cur.execute("delete from hub.users where user_id=%s", (user_id,))


def _stash_bom_pending_with_drift(client_id: str) -> str:
    """Insert an upload_pending row whose parsed_rows contain a
    cross-family UoM drift on COUNT_PCS (catalog says pcs, file says kg)."""
    import json
    import secrets
    from datetime import datetime, timedelta, timezone
    pending_id = secrets.token_urlsafe(16)
    parsed = {
        "products": {
            "P_DRIFT_TEST": [
                {"material_code": "COUNT_PCS", "qty_per_unit": 1.0,
                 "uom": "kg"},
            ]
        }
    }
    diff = {"profile": "manual_flat"}
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "insert into hub.upload_pending (pending_id, client_id, "
            "module, parsed_rows, diff_summary, expires_at) "
            "values (%s, %s, 'bom', %s::jsonb, %s::jsonb, %s)",
            (pending_id, client_id, json.dumps(parsed), json.dumps(diff),
             datetime.now(timezone.utc) + timedelta(hours=1)),
        )
        conn.commit()
    return pending_id


def test_bom_preview_route_renders_uom_drift_banner(admin_client):
    pending = _stash_bom_pending_with_drift(CLIENT)
    try:
        r = admin_client.get(
            f"/clients/{CLIENT}/bom/preview/{pending}",
        )
        assert r.status_code == 200
        body = r.text
        assert "uom-drift-panel" in body, (
            "BOM preview must include UoM drift banner panel."
        )
        # Cross-family drift triggers warn-level banner + ack checkbox.
        assert 'name="ack_uom_drift"' in body, (
            "warn-level drift must surface the ack checkbox."
        )
        assert "COUNT_PCS" in body
    finally:
        with connect() as conn, conn.cursor() as cur:
            cur.execute("delete from hub.upload_pending where pending_id=%s",
                        (pending,))


def _stash_bcct_pending_with_drift(client_id: str,
                                   diff: dict | None = None) -> str:
    """Same but for BCCT shape (customs_code/unit instead of
    material_code/uom). Pass `diff` to also surface value-diff rows (the
    confirm_diffs checkbox + Apply button); default is an all-new summary
    with no diffs."""
    import json
    import secrets
    from datetime import datetime, timedelta, timezone
    pending_id = secrets.token_urlsafe(16)
    parsed = [
        {"customs_code": "COUNT_PCS", "unit": "kg",
         "declaration_no": "TEST_DRIFT", "line_no": 1,
         "transaction_key": "TEST_DRIFT-1", "direction": "import"},
    ]
    if diff is None:
        diff = {"new": 1, "noop": 0, "diff": [], "orphan": [], "total": 1}
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "insert into hub.upload_pending (pending_id, client_id, "
            "module, parsed_rows, diff_summary, expires_at) "
            "values (%s, %s, 'bcct', %s::jsonb, %s::jsonb, %s)",
            (pending_id, client_id, json.dumps(parsed), json.dumps(diff),
             datetime.now(timezone.utc) + timedelta(hours=1)),
        )
        conn.commit()
    return pending_id


def test_bcct_preview_route_renders_uom_drift_banner(admin_client):
    pending = _stash_bcct_pending_with_drift(CLIENT)
    try:
        r = admin_client.get(
            f"/clients/{CLIENT}/bcct/upload/preview/{pending}",
        )
        assert r.status_code == 200
        body = r.text
        assert "uom-drift-panel" in body, (
            "BCCT preview must include UoM drift banner panel."
        )
        assert 'name="ack_uom_drift"' in body
        assert "COUNT_PCS" in body
    finally:
        with connect() as conn, conn.cursor() as cur:
            cur.execute("delete from hub.upload_pending where pending_id=%s",
                        (pending,))


def test_bcct_preview_apply_gate_hint_when_blocking_drift(admin_client):
    """Regression for #56: when a blocking cross-family drift disables the
    Apply button, the preview must render a discoverable hint that (a) says
    the button is locked, (b) links to the ack checkbox, (c) clarifies that
    confirm_diffs does not unlock it and per-row factors are optional."""
    # Johnson VN scenario: value-diff rows (so confirm_diffs + the Apply
    # button render) plus a blocking cross-family drift.
    diff = {
        "new": 14164, "noop": 31171, "total": 14164, "orphan": [],
        "diff": [{
            "key": ["TEST_DRIFT-1", 1], "decl_no": "TEST_DRIFT", "line_no": 1,
            "changed_fields": ["invoice_date"],
            "old": {"invoice_date": "2026-04-19"},
            "new": {"invoice_date": "2026-05-19"},
        }],
    }
    pending = _stash_bcct_pending_with_drift(CLIENT, diff=diff)
    try:
        r = admin_client.get(
            f"/clients/{CLIENT}/bcct/upload/preview/{pending}")
        assert r.status_code == 200
        body = r.text
        # Precondition: this is the gated scenario (diff rows + blocking drift).
        assert 'name="ack_uom_drift"' in body
        assert 'name="confirm_diffs"' in body
        assert "Apply confirmed changes" in body
        # The fix: a discoverable locked-state hint + jump link to the ack box.
        assert 'id="uom-gate-hint"' in body, (
            "disabled Apply button must carry a hint explaining the UoM ack gate")
        assert 'id="uom-gate-jump"' in body, (
            "hint must link to the ack checkbox")
        assert "không mở nút" in body, (
            "hint must clarify confirm_diffs does not unlock the button")
        assert "Không cần gán hệ số" in body, (
            "hint must clarify per-row factors are optional")
    finally:
        with connect() as conn, conn.cursor() as cur:
            cur.execute("delete from hub.upload_pending where pending_id=%s",
                        (pending,))


def test_no_drift_route_no_banner(admin_client):
    """Upload with no drift → banner block absent (just empty render)."""
    import json
    import secrets
    from datetime import datetime, timedelta, timezone
    pending_id = secrets.token_urlsafe(16)
    parsed = {"products": {
        "P_NO_DRIFT": [
            {"material_code": "COUNT_PCS", "qty_per_unit": 1.0, "uom": "pcs"}
        ]
    }}
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "insert into hub.upload_pending (pending_id, client_id, "
            "module, parsed_rows, diff_summary, expires_at) "
            "values (%s, %s, 'bom', %s::jsonb, %s::jsonb, %s)",
            (pending_id, CLIENT, json.dumps(parsed), '{}',
             datetime.now(timezone.utc) + timedelta(hours=1)),
        )
        conn.commit()
    try:
        r = admin_client.get(f"/clients/{CLIENT}/bom/preview/{pending_id}")
        assert r.status_code == 200
        body = r.text
        assert "uom-drift-panel" not in body, (
            "No drift → no banner."
        )
    finally:
        with connect() as conn, conn.cursor() as cur:
            cur.execute("delete from hub.upload_pending where pending_id=%s",
                        (pending_id,))
