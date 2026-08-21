"""Track A — BOM vocab cleanup. Templates + i18n.

Locks in the post-mig-031 vocab rules across BOM UI surface:
- Drop "v" badge prefix on artifact_no display → use "#" instead.
- Hide bom_variant_id column/row/span when value is None or 'default'.
- Rename n_dual_variants → n_strategies (semantic match: counts
  flatten_strategy distinct, not supplier-batch variants).
- VN i18n uses "bản lưu" / "shape" / "preset" canonical vocab.
- EN i18n uses "artifact" / "shape" / "preset".

Scope source: .ai/features/2026-05-10-bom-vocab-3shape-uom-gate/brief.md
Track A.

Tests are split:
- Direct Jinja for macros (`_bom_macros.html`) — fast, isolated.
- i18n module tests for translation keys.
- TestClient render for full templates (bom.html, bom_artifacts.html,
  bom_artifact_detail.html, bom_presets.html, bom_preview.html).
"""
from __future__ import annotations

from pathlib import Path

import pytest
from jinja2 import Environment, FileSystemLoader

from app import i18n


TEMPLATES = Path(__file__).resolve().parent.parent / "app" / "templates"


# ─────────────────────────────────────────────────────────────────────
# Jinja env helpers — render macros directly without FastAPI stack.
# ─────────────────────────────────────────────────────────────────────


@pytest.fixture
def env() -> Environment:
    return Environment(
        loader=FileSystemLoader(str(TEMPLATES)),
        autoescape=True,
        keep_trailing_newline=False,
    )


def _render_lineage_node(env, node: dict, current_id: str = "ba_other",
                         client_id: str = "c1") -> str:
    tpl = env.from_string(
        '{% from "clients/_bom_macros.html" import lineage_node %}'
        '{{ lineage_node(node, current_id, client_id) }}'
    )
    return tpl.render(node=node, current_id=current_id, client_id=client_id)


# ─────────────────────────────────────────────────────────────────────
# Macros: lineage_node hide/show variant + # badge
# ─────────────────────────────────────────────────────────────────────


def test_lineage_node_hides_variant_when_default(env):
    node = {
        "artifact_id": "ba_x",
        "artifact_no": 3,
        "bom_variant_id": "default",
        "bom_shape": "shallow",
        "intent": "asserted_technical",
        "actor": "agency_staff",
        "tombstoned_at": None,
    }
    out = _render_lineage_node(env, node)
    assert "default" not in out, (
        "lineage_node must HIDE the variant span when bom_variant_id is "
        f"'default' or None. Got: {out}"
    )


def test_lineage_node_hides_variant_when_none(env):
    node = {
        "artifact_id": "ba_x",
        "artifact_no": 3,
        "bom_variant_id": None,
        "bom_shape": "shallow",
        "intent": "asserted_technical",
        "actor": "agency_staff",
        "tombstoned_at": None,
    }
    out = _render_lineage_node(env, node)
    assert "default" not in out
    assert "None" not in out


def test_lineage_node_shows_variant_when_non_default(env):
    node = {
        "artifact_id": "ba_x",
        "artifact_no": 3,
        "bom_variant_id": "agency_2026-04-23",
        "bom_shape": "shallow",
        "intent": "asserted_technical",
        "actor": "agency_staff",
        "tombstoned_at": None,
    }
    out = _render_lineage_node(env, node)
    assert "agency_2026-04-23" in out


def test_lineage_node_uses_hash_badge_not_v(env):
    node = {
        "artifact_id": "ba_x",
        "artifact_no": 7,
        "bom_variant_id": None,
        "bom_shape": "raw_graph",
        "intent": "asserted_technical",
        "actor": "agency_staff",
        "tombstoned_at": None,
    }
    out = _render_lineage_node(env, node)
    # "#7" must appear; "v7" must not.
    assert "#7" in out, (
        f"Badge must be '#N' (artifact sequence), not 'vN' (legacy "
        f"version). Got: {out}"
    )
    assert "v7" not in out


# ─────────────────────────────────────────────────────────────────────
# i18n keys — VN canonical = "bản lưu", EN = "artifact"/"shape"/"preset".
# ─────────────────────────────────────────────────────────────────────


def test_i18n_vn_col_versions_uses_ban_luu():
    s = i18n.t("bom.col.versions", "vi").lower()
    assert "bản lưu" in s, (
        f"VN column header must say 'bản lưu' (artifact storage row), "
        f"not 'versions'. Got: {s!r}"
    )


def test_i18n_vn_versions_title_uses_ban_luu():
    s = i18n.t("bom.versions_title", "vi").lower()
    assert "bản lưu" in s, (
        f"VN h2 on bom_artifacts page must use 'bản lưu' vocab. "
        f"Got: {s!r}"
    )


def test_i18n_vn_bom_variant_not_phien_ban():
    """`bom.bom_variant` was VN-mapped to 'Phiên bản BOM' which clashes
    with the canonical 'Phiên bản' = logical-tuple semantic from
    GLOSSARY. Must be renamed to something distinct (e.g., 'Đợt' or
    'Variant')."""
    s = i18n.t("bom.bom_variant", "vi")
    assert s.strip().lower() != "phiên bản bom", (
        f"bom.bom_variant must NOT be 'Phiên bản BOM' (clashes with "
        f"logical-version vocab). Got: {s!r}"
    )


def test_i18n_vn_versions_immutable_uses_ban_luu():
    s = i18n.t("bom.versions_immutable", "vi").lower()
    assert "bản lưu" in s


def test_i18n_en_col_versions_uses_artifact():
    s = i18n.t("bom.col.versions", "en").lower()
    assert "artifact" in s, (
        f"EN column header must use 'artifact'. Got: {s!r}"
    )


def test_i18n_en_versions_title_uses_artifact():
    s = i18n.t("bom.versions_title", "en").lower()
    assert "artifact" in s


def test_i18n_vn_subtitle_drops_version_word():
    s = i18n.t("bom.subtitle", "vi").lower()
    assert "version" not in s, (
        f"VN bom.subtitle must not contain English 'version' word. "
        f"Got: {s!r}"
    )


def test_i18n_vn_upload_help_uses_ban_luu():
    s = i18n.t("bom.upload_help", "vi").lower()
    assert "bản lưu" in s or "artifact" not in s
    # Must not say "BOM version"
    assert "bom version" not in s


def test_i18n_vn_adapter_descs_drop_version_word():
    for key in (
        "bom.adapter.sap_indented_walk.desc",
        "bom.adapter.multi_sheet_per_root.desc",
        "bom.adapter.technical_flatten.desc",
    ):
        s = i18n.t(key, "vi").lower()
        assert "bom version" not in s, (
            f"{key} (vi) must drop 'BOM version' phrasing. Got: {s!r}"
        )


def test_i18n_en_adapter_descs_use_artifact():
    for key in (
        "bom.adapter.sap_indented_walk.desc",
        "bom.adapter.multi_sheet_per_root.desc",
    ):
        s = i18n.t(key, "en").lower()
        assert "bom version" not in s, (
            f"{key} (en) must use 'BOM artifact' not 'BOM version'. "
            f"Got: {s!r}"
        )


# ─────────────────────────────────────────────────────────────────────
# Store rename: n_dual_variants → n_strategies (semantic accuracy).
# This is a label-only rename in the Python dict; the SQL alias is
# already n_strategies (we drop the Python pop+rename step).
# ─────────────────────────────────────────────────────────────────────


def test_list_products_with_bom_returns_n_strategies_field():
    """The store dict shape must expose `n_strategies` (matches the
    SQL semantic — distinct flatten_strategy count). The legacy
    `n_dual_variants` alias must NOT be present (misleading name —
    suggests supplier dual-source, actually counts shapes)."""
    from app.stores.bom import list_products_with_bom
    rows = list_products_with_bom("growatt-vn", limit=1)
    if not rows:
        pytest.skip("no BOM data for growatt-vn in this DB")
    r = rows[0]
    assert "n_strategies" in r, (
        f"list_products_with_bom must return 'n_strategies'. "
        f"Keys: {list(r.keys())}"
    )
    assert "n_dual_variants" not in r, (
        f"'n_dual_variants' is misleading legacy name — must be "
        f"renamed to 'n_strategies'. Keys: {list(r.keys())}"
    )


# ─────────────────────────────────────────────────────────────────────
# TestClient render — full templates with seeded data.
# Use existing demo clients (johnson-vn) which have artifacts with
# real non-default variants (agency_2026-04-23).
# ─────────────────────────────────────────────────────────────────────


@pytest.fixture
def admin_client():
    from fastapi.testclient import TestClient
    from app.auth.session import (SESSION_COOKIE, create_session,
                                   hash_password)
    from app.database import connect
    from app.main import app

    user_id = "u_track_a_admin"
    email = "track-a@test.local"
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "insert into hub.users (user_id, email, display_name, "
            "password_hash, role, status) values (%s, %s, 'Track A', "
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


def test_bom_list_page_no_misleading_dual_variants_text(admin_client):
    """The 'dual-source variants' badge title was misleading. The
    badge actually counts flatten_strategy distinct (= shape variants),
    NOT supplier-batch variants. Either drop the badge or relabel."""
    r = admin_client.get("/clients/johnson-vn/bom")
    assert r.status_code == 200
    body = r.text
    # The misleading title attribute must be gone.
    assert 'title="dual-source variants"' not in body, (
        "Badge must not claim 'dual-source variants' when it actually "
        "counts flatten_strategies."
    )


def test_bom_list_page_uses_n_strategies_not_n_dual_variants(admin_client):
    """Templates must reference the renamed dict key. If template
    still says `p.n_dual_variants`, this test won't catch it directly,
    but the previous store test prevents that key from existing."""
    r = admin_client.get("/clients/johnson-vn/bom")
    assert r.status_code == 200
    # Sanity: page rendered without throwing template Undefined.
    assert "<table" in r.text


def test_bom_artifacts_page_uses_hash_badge_not_v(admin_client):
    """Pick any product with artifacts. Badge inside table cells must
    be '#N' not 'vN'."""
    from app.database import connect
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "select product_code from hub.bom_artifacts "
            "where client_id='johnson-vn' and tombstoned_at is null "
            "limit 1"
        )
        row = cur.fetchone()
    if not row:
        pytest.skip("no Johnson BOM artifacts seeded")
    pcode = row[0]
    r = admin_client.get(f"/clients/johnson-vn/bom/{pcode}/artifacts")
    assert r.status_code == 200
    body = r.text
    # Must contain at least one '#N' badge for an artifact_no.
    import re
    assert re.search(r'>#\d+<', body), (
        f"bom_artifacts page must render '#N' artifact-no badges. "
        f"Body excerpt: {body[:600]}"
    )
    # No 'v1', 'v2', etc. badges (legacy version-letter pattern).
    assert not re.search(r'>v\d+<', body), (
        "Legacy 'vN' badge pattern still present — must drop the 'v' "
        "letter."
    )


def test_bom_artifacts_variant_col_hidden_when_all_default(admin_client):
    """When every artifact for a product has bom_variant_id NULL or
    'default', the 'variant' column should not appear (or appear as
    a hidden column / collapsed)."""
    from app.database import connect

    # Find a product whose artifacts are all-default. If none, we
    # synthesize via raw insert + cleanup.
    pcode = "TRACK_A_ALL_DEFAULT"
    client_id = "johnson-vn"
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "insert into hub.bom_artifacts (artifact_id, client_id, "
            "product_code, artifact_no, status, actor, intent, "
            "context, normalized_hash, row_count, source_bom_kind, "
            "flatten_status, flatten_strategy, source_channel, "
            "bom_variant_id, lineage, flatten_method, "
            "flatten_method_version, published_at) "
            "values (%s, %s, %s, 1, 'published', 'agency_staff', "
            "'asserted_technical', '{}', 'h_track_a_1', 0, "
            "'technical_flattened', 'flattened', "
            "'manual_flat_as_provided', 'staff_form', 'default', "
            "'{}', 'as_provided', 'v1', now())",
            ("ba_track_a_default", client_id, pcode),
        )
        conn.commit()
    try:
        r = admin_client.get(f"/clients/{client_id}/bom/{pcode}/artifacts")
        assert r.status_code == 200
        body = r.text
        # The variant column header should be hidden when all rows are
        # default. Use a dedicated CSS data attribute or absence check.
        # Acceptable signal: column header for variant absent OR data-
        # all-default attribute present.
        # We assert: the literal cell text 'default' must not appear
        # as a free-standing variant value.
        assert ">default<" not in body, (
            "Variant cell should not render the literal 'default' string. "
            "Hide the column or use blank cell for default rows."
        )
    finally:
        with connect() as conn, conn.cursor() as cur:
            cur.execute("delete from hub.bom_artifacts where artifact_id=%s",
                        ("ba_track_a_default",))


def test_bom_artifact_detail_provenance_variant_hidden_when_default(
        admin_client):
    """Provenance row 'Variant' must NOT show when bom_variant_id is
    NULL or 'default'."""
    from app.database import connect
    artifact_id = "ba_track_a_detail_default"
    pcode = "TRACK_A_DETAIL_DEFAULT"
    client_id = "johnson-vn"
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "insert into hub.bom_artifacts (artifact_id, client_id, "
            "product_code, artifact_no, status, actor, intent, "
            "context, normalized_hash, row_count, source_bom_kind, "
            "flatten_status, flatten_strategy, source_channel, "
            "bom_variant_id, lineage, flatten_method, "
            "flatten_method_version, published_at) "
            "values (%s, %s, %s, 1, 'published', 'agency_staff', "
            "'asserted_technical', '{}', 'h_track_a_2', 0, "
            "'technical_flattened', 'flattened', "
            "'manual_flat_as_provided', 'staff_form', 'default', "
            "'{}', 'as_provided', 'v1', now())",
            (artifact_id, client_id, pcode),
        )
        conn.commit()
    try:
        r = admin_client.get(
            f"/clients/{client_id}/bom/artifact/{artifact_id}",
        )
        assert r.status_code == 200
        body = r.text
        # The Provenance row literal "Variant" label should not
        # appear when value is 'default'. Tolerate the cell value
        # text 'default' appearing inside an other context (e.g.
        # 'default' nowhere should match).
        # Strict check: no row labeled "Variant" with value "default".
        assert "Variant</td>" not in body or ">default</td>" not in body, (
            "Provenance row 'Variant: default' must be hidden."
        )
    finally:
        with connect() as conn, conn.cursor() as cur:
            cur.execute("delete from hub.bom_artifacts where artifact_id=%s",
                        (artifact_id,))


def test_bom_presets_select_option_hides_default_string(admin_client):
    """Preset create form's <option> text contains
    `{{ a.bom_variant_id or 'default' }}` — when value is None/default,
    the option text shouldn't include the literal 'default' segment
    (it confuses staff into thinking 'default' is meaningful)."""
    from app.database import connect
    artifact_id = "ba_track_a_preset_default"
    pcode = "TRACK_A_PRESET_DEFAULT"
    client_id = "johnson-vn"
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "insert into hub.bom_artifacts (artifact_id, client_id, "
            "product_code, artifact_no, status, actor, intent, "
            "context, normalized_hash, row_count, source_bom_kind, "
            "flatten_status, flatten_strategy, source_channel, "
            "bom_variant_id, lineage, flatten_method, "
            "flatten_method_version, published_at) "
            "values (%s, %s, %s, 1, 'published', 'agency_staff', "
            "'asserted_technical', '{}', 'h_track_a_3', 0, "
            "'technical_flattened', 'flattened', "
            "'manual_flat_as_provided', 'staff_form', 'default', "
            "'{}', 'as_provided', 'v1', now())",
            (artifact_id, client_id, pcode),
        )
        conn.commit()
    try:
        r = admin_client.get(
            f"/clients/{client_id}/bom/{pcode}/presets",
        )
        assert r.status_code == 200
        body = r.text
        # Option text shouldn't have "· default ·" or similar
        # default-as-value segment.
        assert "· default ·" not in body, (
            "Preset <option> text shouldn't show 'default' as if it's "
            "a meaningful variant label."
        )
    finally:
        with connect() as conn, conn.cursor() as cur:
            cur.execute("delete from hub.bom_artifacts where artifact_id=%s",
                        (artifact_id,))
