"""Phase 3b · BOM resolver core (`resolve_bom_artifact`).

Precedence (most-specific first):
1. preset_id — pinned via hub.bom_presets
2. case_id — bom_artifacts.context->>'case_id' match
3. shape filter — restrict latest set to specified shape
4. default — latest_flattened_versions; single → 200, multi → 409

Provenance trail (D2): list of strings explaining each decision step.
Tombstoned presets remain queryable (D5); resolver returns the
underlying artifact with a warning in the trail.
"""
from __future__ import annotations

import pytest

from hub.app.database import connect
from hub.app.stores.bom import (
    BomShape,
    ResolverError,
    resolve_bom_artifact,
)


CLIENT = "resolver_test"
PRODUCT = "TP_RES"


@pytest.fixture(autouse=True)
def setup():
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "insert into hub.clients (client_id, name) values (%s, %s) "
            "on conflict (client_id) do nothing",
            (CLIENT, "resolver test"),
        )
        cur.execute(
            "insert into hub.users (user_id, email, password_hash, role, display_name) "
            "values ('u_res', 'r@e', '', 'admin', 'R') on conflict do nothing"
        )
    yield
    with connect() as conn, conn.cursor() as cur:
        cur.execute("delete from hub.bom_presets where client_id=%s", (CLIENT,))
        cur.execute(
            "delete from hub.bom_artifacts where client_id=%s", (CLIENT,)
        )
        cur.execute("delete from hub.clients where client_id=%s", (CLIENT,))
        cur.execute("delete from hub.users where user_id='u_res'")


def _add_artifact(cur, *, artifact_id: str, status: str = "published",
                   strategy: str = "technical_exploded",
                   variant: str | None = None,
                   tombstoned: bool = False,
                   context: dict | None = None,
                   intent: str = "asserted_technical",
                   flatten_status: str = "flattened"):
    import json
    cur.execute(
        "insert into hub.bom_artifacts (artifact_id, client_id, product_code, "
        "artifact_no, actor, intent, normalized_hash, source_bom_kind, "
        "flatten_status, flatten_strategy, source_channel, flatten_method, "
        "flatten_method_version, status, bom_variant_id, tombstoned_at, "
        "context, published_at) "
        "values (%s, %s, %s, %s, 'agency_staff', %s, %s, "
        "'technical_flattened', %s, %s, 'agency_upload', "
        "'manual', '0.1', %s, %s, %s, %s, now())",
        (artifact_id, CLIENT, PRODUCT, hash(artifact_id) % 10000,
         intent, f"hash_{artifact_id}", flatten_status, strategy,
         status, variant, "now()" if tombstoned else None,
         json.dumps(context or {})),
    )
    if tombstoned:
        cur.execute(
            "update hub.bom_artifacts set tombstoned_at=now(), "
            "tombstone_reason='test' where artifact_id=%s",
            (artifact_id,),
        )


def _add_preset(cur, *, preset_id: str, artifact_id: str,
                 name: str = "default", tombstoned: bool = False):
    cur.execute(
        "insert into hub.bom_presets (preset_id, client_id, product_code, "
        "artifact_id, name, sourcing_choices, created_by) "
        "values (%s, %s, %s, %s, %s, '{}'::jsonb, 'u_res')",
        (preset_id, CLIENT, PRODUCT, artifact_id, name),
    )
    if tombstoned:
        cur.execute(
            "update hub.bom_presets set tombstoned_at=now(), "
            "tombstone_reason='test' where preset_id=%s",
            (preset_id,),
        )


# ─────────────────────────────────────────────────────────────────────
# Default precedence — single artifact, no hints
# ─────────────────────────────────────────────────────────────────────


def test_default_returns_single_alive_artifact():
    with connect() as conn, conn.cursor() as cur:
        _add_artifact(cur, artifact_id="ba_only")
        conn.commit()
        out = resolve_bom_artifact(client_id=CLIENT, product_code=PRODUCT)
    assert out["artifact_id"] == "ba_only"
    assert out["shape"] == "full_flat"
    assert any("default" in step for step in out["resolution_trail"])


def test_default_raises_on_dual_source():
    with connect() as conn, conn.cursor() as cur:
        _add_artifact(cur, artifact_id="ba_pur",
                       strategy="purchased_btp_as_leaf", variant="v1")
        _add_artifact(cur, artifact_id="ba_exp",
                       strategy="self_produced_btp_exploded", variant="v2")
    with pytest.raises(ResolverError) as exc:
        resolve_bom_artifact(client_id=CLIENT, product_code=PRODUCT)
    assert exc.value.code == "dual_source_variants"
    assert len(exc.value.extra["variants"]) == 2


def test_default_raises_on_no_alive_artifacts():
    with pytest.raises(ResolverError) as exc:
        resolve_bom_artifact(client_id=CLIENT, product_code=PRODUCT)
    assert exc.value.code == "no_alive_artifacts"


# ─────────────────────────────────────────────────────────────────────
# preset_id precedence — most specific
# ─────────────────────────────────────────────────────────────────────


def test_preset_id_pins_artifact():
    with connect() as conn, conn.cursor() as cur:
        _add_artifact(cur, artifact_id="ba_pinned")
        conn.commit()
        _add_preset(cur, preset_id="bp_def", artifact_id="ba_pinned")
        conn.commit()
        out = resolve_bom_artifact(
            client_id=CLIENT, product_code=PRODUCT, preset_id="bp_def",
        )
    assert out["artifact_id"] == "ba_pinned"
    assert any("preset" in step and "bp_def" in step
               for step in out["resolution_trail"])


def test_preset_id_unknown_raises():
    with pytest.raises(ResolverError) as exc:
        resolve_bom_artifact(
            client_id=CLIENT, product_code=PRODUCT, preset_id="bp_missing",
        )
    assert exc.value.code == "preset_not_found"


def test_preset_id_tombstoned_resolves_with_warning():
    """D5: tombstoned presets remain queryable for audit reproduction."""
    with connect() as conn, conn.cursor() as cur:
        _add_artifact(cur, artifact_id="ba_audit")
        conn.commit()
        _add_preset(cur, preset_id="bp_old", artifact_id="ba_audit",
                     tombstoned=True)
        conn.commit()
    out = resolve_bom_artifact(
        client_id=CLIENT, product_code=PRODUCT, preset_id="bp_old",
    )
    assert out["artifact_id"] == "ba_audit"
    assert any("tombstoned" in step.lower()
               for step in out["resolution_trail"])


def test_preset_id_resolves_even_when_underlying_artifact_tombstoned():
    """D5 corollary: artifact tombstoned but preset alive — preset wins."""
    with connect() as conn, conn.cursor() as cur:
        _add_artifact(cur, artifact_id="ba_dead", tombstoned=True)
        conn.commit()
        _add_preset(cur, preset_id="bp_pin", artifact_id="ba_dead")
        conn.commit()
        out = resolve_bom_artifact(
            client_id=CLIENT, product_code=PRODUCT, preset_id="bp_pin",
        )
    assert out["artifact_id"] == "ba_dead"


# ─────────────────────────────────────────────────────────────────────
# case_id precedence — second
# ─────────────────────────────────────────────────────────────────────


def test_case_id_finds_modified_for_case_artifact():
    with connect() as conn, conn.cursor() as cur:
        _add_artifact(cur, artifact_id="ba_base")
        _add_artifact(cur, artifact_id="ba_case_xyz",
                       intent="modified_for_case",
                       context={"case_id": "co_xyz"})
        conn.commit()
    out = resolve_bom_artifact(
        client_id=CLIENT, product_code=PRODUCT, case_id="co_xyz",
    )
    assert out["artifact_id"] == "ba_case_xyz"
    assert any("case_id" in step and "co_xyz" in step
               for step in out["resolution_trail"])


def test_case_id_not_found_raises():
    with connect() as conn, conn.cursor() as cur:
        _add_artifact(cur, artifact_id="ba_other")
        conn.commit()
    with pytest.raises(ResolverError) as exc:
        resolve_bom_artifact(
            client_id=CLIENT, product_code=PRODUCT, case_id="co_missing",
        )
    assert exc.value.code == "case_not_found"


# ─────────────────────────────────────────────────────────────────────
# shape filter — third precedence
# ─────────────────────────────────────────────────────────────────────


def test_shape_filter_picks_matching_artifact():
    with connect() as conn, conn.cursor() as cur:
        _add_artifact(cur, artifact_id="ba_shal",
                       strategy="purchased_btp_as_leaf", variant="v1")
        _add_artifact(cur, artifact_id="ba_full",
                       strategy="technical_exploded", variant="v2")
        conn.commit()
    out = resolve_bom_artifact(
        client_id=CLIENT, product_code=PRODUCT, shape="shallow",
    )
    assert out["artifact_id"] == "ba_shal"
    assert out["shape"] == "shallow"


def test_shape_filter_no_match_raises():
    with connect() as conn, conn.cursor() as cur:
        _add_artifact(cur, artifact_id="ba_full",
                       strategy="technical_exploded")
    with pytest.raises(ResolverError) as exc:
        resolve_bom_artifact(
            client_id=CLIENT, product_code=PRODUCT, shape="raw_graph",
        )
    assert exc.value.code == "no_artifact_for_shape"


def test_shape_filter_tie_breaks_when_multiple_variants():
    """Two artifacts of the same shape but different variants — shape
    filter narrows + tie-breaks to latest published; no 409."""
    with connect() as conn, conn.cursor() as cur:
        _add_artifact(cur, artifact_id="ba_var1",
                       strategy="technical_exploded", variant="v1")
        _add_artifact(cur, artifact_id="ba_var2",
                       strategy="technical_exploded", variant="v2")
        conn.commit()
    out = resolve_bom_artifact(
        client_id=CLIENT, product_code=PRODUCT, shape="full_flat",
    )
    assert out["shape"] == "full_flat"
    assert out["artifact_id"] in {"ba_var1", "ba_var2"}
    assert any("tie-break" in s for s in out["resolution_trail"])


# ─────────────────────────────────────────────────────────────────────
# Provenance trail content — D2
# ─────────────────────────────────────────────────────────────────────


def test_resolution_trail_is_a_list_of_strings():
    with connect() as conn, conn.cursor() as cur:
        _add_artifact(cur, artifact_id="ba_prov")
        conn.commit()
        out = resolve_bom_artifact(client_id=CLIENT, product_code=PRODUCT)
    assert isinstance(out["resolution_trail"], list)
    assert all(isinstance(s, str) for s in out["resolution_trail"])
    assert len(out["resolution_trail"]) >= 1
