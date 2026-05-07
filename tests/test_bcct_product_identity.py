"""BCCT BOM product identity resolver.

Brief: .ai/features/2026-05-07-bcct-product-identity/brief.md

Resolver stages (D2):
  1. structured_field    — customs_code already in bom_artifacts.product_code
  2. goods_name_embedded — client adapter parses paren codes
  3. reviewed_line_mapping
  4. code_mapping_candidate (candidates only — never resolves)
  5. missing
"""
from __future__ import annotations

import pytest

from app.resolvers.bcct_product_identity import (
    ResolverContext,
    resolve_product_identity,
)


GROWATT_ROW = {
    "client_id": "growatt-vn",
    "transaction_key": "307591379560-3",
    "declaration_no": "307591379560",
    "line_no": "3",
    "customs_code": "BIENTAN.17",
    "internal_code": "BIENTAN.17",
    "goods_name": (
        "BIENTAN.17#&Thiết bị biến tần model MIN 4200TL-X2(Pro.E), "
        "dùng để chuyển đổi dòng điện dùng cho hệ thống điện mặt trời. "
        "Hàng mới 100% (PV01.0117500)#&VN"
    ),
}


def _make_catalog(specs):
    """Build a material_catalog dict from terse fixtures.

    Each spec is either:
      - "code"                            → defaults: kind=tp, has_bom=True, n_artifacts=1
      - ("code", "kind")                  → has_bom=True, n_artifacts=1
      - ("code", "kind", n_artifacts)     → has_bom=(n_artifacts>0)
    """
    out: dict[str, dict] = {}
    for spec in specs or []:
        if isinstance(spec, str):
            code, kind, n = spec, "tp", 1
        elif len(spec) == 2:
            code, kind = spec
            n = 1
        else:
            code, kind, n = spec
        out[code] = {
            "internal_code": code,
            "name": code,
            "category": kind,
            "n_artifacts": n,
            "has_bom": n > 0,
            "latest_flatten_status": "flattened" if n > 0 else None,
        }
    return out


def _ctx(*, materials=None, code_mappings=None, reviewed=None,
         adapter_name="growatt_bcct"):
    """Build a ResolverContext directly from in-memory fixtures (no DB).

    `materials` is an iterable of catalog specs (see _make_catalog)."""
    return ResolverContext(
        client_id="growatt-vn",
        material_catalog=_make_catalog(materials),
        code_mappings=code_mappings or {},
        reviewed=reviewed or {},
        adapter_name=adapter_name,
        candidate_limit=5,
    )


# ─────────────────────────────────────────────────────────────────────
# Stage 2: goods_name_embedded_code (Growatt happy path)
# ─────────────────────────────────────────────────────────────────────

def test_growatt_paren_code_resolves_when_bom_exists():
    """Growatt golden case: '(PV01.0117500)' embedded in goods_name +
    matching BOM artifact => resolved. bom_product_code alias populated
    because the resolved code has a BOM (kind=tp)."""
    ctx = _ctx(materials=[("PV01.0117500", "tp", 1)])
    pid = resolve_product_identity(GROWATT_ROW, ctx=ctx)

    assert pid["resolution_status"] == "resolved"
    assert pid["resolved_code"] == "PV01.0117500"
    assert pid["bom_product_code"] == "PV01.0117500"  # alias when has_bom
    assert pid["product_kind"] == "tp"
    assert pid["selected_candidate_code"] == "PV01.0117500"
    assert pid["resolution_source"] == "goods_name_embedded_code"
    assert pid["confidence"] == "high"
    assert pid["review_status"] == "system_resolved"
    assert pid["display_code"] == "BIENTAN.17"
    assert pid["declared_customs_code"] == "BIENTAN.17"
    assert pid["declared_internal_code"] == "BIENTAN.17"
    assert pid["line_key"] == {
        "client_id": "growatt-vn",
        "declaration_no": "307591379560",
        "line_no": "3",
        "transaction_key": "307591379560-3",
    }
    assert pid["evidence"]["source_field"] == "goods_name"
    assert pid["evidence"]["matched_text"] == "PV01.0117500"
    assert pid["evidence"]["match_rule"] == \
        "parenthesized_product_code_exists_in_bom_products"
    assert pid["parser_adapter"] == "growatt_bcct"
    assert isinstance(pid["parser_version"], str) and pid["parser_version"]
    # Candidates list contains the matched code with high confidence.
    assert any(c["product_code"] == "PV01.0117500"
               and c["confidence"] == "high" for c in pid["candidates"])


# ─────────────────────────────────────────────────────────────────────
# Stage 1: structured_field — customs_code IS the BOM product code
# ─────────────────────────────────────────────────────────────────────

def test_customs_code_in_bom_artifacts_resolves_via_structured_field():
    """Some Growatt rows declare customs_code='SA00.0001402' which is
    itself a BOM product. Resolver picks this before any goods_name parse."""
    row = {
        **GROWATT_ROW,
        "customs_code": "SA00.0001402",
        "internal_code": "SA00.0001402",
        "goods_name": "SA00.0001402#&Hộp điều khiển ... (PV01.0117500)#&VN",
    }
    # Both codes exist in materials. Stage 1 wins.
    ctx = _ctx(materials=[("SA00.0001402", "tp", 1), ("PV01.0117500", "tp", 1)])
    pid = resolve_product_identity(row, ctx=ctx)

    assert pid["resolution_status"] == "resolved"
    assert pid["resolved_code"] == "SA00.0001402"
    assert pid["bom_product_code"] == "SA00.0001402"
    assert pid["resolution_source"] == "structured_field"
    assert pid["evidence"]["match_rule"] == "customs_code_exists_in_bom_products"


# ─────────────────────────────────────────────────────────────────────
# Stage 2 — negative: parsed code without same-client BOM
# ─────────────────────────────────────────────────────────────────────

def test_parsed_code_without_catalog_entry_returns_unverified():
    """Negative test from spec: '(PV01.0117500)' parsed but not in
    materials catalog for this client → unverified, NOT resolved."""
    ctx = _ctx(materials=[])  # Empty catalog.
    pid = resolve_product_identity(GROWATT_ROW, ctx=ctx)

    assert pid["resolution_status"] == "unverified"
    assert pid["resolved_code"] is None
    assert pid["bom_product_code"] is None
    assert pid["selected_candidate_code"] == "PV01.0117500"  # for UI preselect
    assert pid["resolution_source"] == "goods_name_embedded_code"
    # Candidate present with low confidence.
    assert any(c["product_code"] == "PV01.0117500"
               and c["confidence"] == "low" for c in pid["candidates"])


# ─────────────────────────────────────────────────────────────────────
# Stage 2 — edge: model-only parens like (Pro.E) do NOT pollute
# ─────────────────────────────────────────────────────────────────────

def test_model_paren_alone_does_not_resolve():
    """`(Pro.E)` and `(MIN ...)` are model names, not BOM codes. Shape
    regex excludes them. With no BOM-shape paren in goods_name,
    resolver falls through to missing (no code_mappings either)."""
    row = {
        **GROWATT_ROW,
        "goods_name": (
            "BIENTAN.17#&Thiết bị biến tần model MIN 4200TL-X2(Pro.E), "
            "Hàng mới 100%#&VN"
        ),
    }
    ctx = _ctx(materials=[("PV01.0117500", "tp", 1)])
    pid = resolve_product_identity(row, ctx=ctx)

    assert pid["resolution_status"] == "missing"
    assert pid["resolved_code"] is None
    assert pid["candidates"] == []


# ─────────────────────────────────────────────────────────────────────
# Stage 2 — edge: multiple paren codes both in catalog → ambiguous
# ─────────────────────────────────────────────────────────────────────

def test_multiple_paren_codes_both_in_catalog_returns_ambiguous():
    """Spec edge: 'multiple plausible codes' must return ambiguous,
    not auto-resolve. Both candidates ranked by bom_artifact_count."""
    row = {
        **GROWATT_ROW,
        "goods_name": "BIENTAN.17#&Variant A (PV01.0117500) variant B (PV02.0229000)#&VN",
    }
    ctx = _ctx(materials=[
        ("PV01.0117500", "tp", 1),
        ("PV02.0229000", "tp", 3),
    ])
    pid = resolve_product_identity(row, ctx=ctx)

    assert pid["resolution_status"] == "ambiguous"
    assert pid["resolved_code"] is None
    assert pid["bom_product_code"] is None
    # Tie-break: PV02.0229000 has more artifacts, ranked first.
    assert pid["selected_candidate_code"] == "PV02.0229000"
    assert [c["product_code"] for c in pid["candidates"]] == [
        "PV02.0229000", "PV01.0117500",
    ]


# ─────────────────────────────────────────────────────────────────────
# Stage 4 — negative: code_mappings alone never resolve
# ─────────────────────────────────────────────────────────────────────

def test_code_mappings_alone_never_resolves():
    """Spec critical guard (R1): code-mappings are candidate evidence
    only. Many-to-many cardinality means they cannot auto-resolve."""
    row = {
        **GROWATT_ROW,
        "goods_name": "BIENTAN.17#&No paren BOM code here#&VN",
    }
    ctx = _ctx(
        materials=[("PV01.0117500", "tp", 1), ("PV02.0229000", "tp", 1)],
        code_mappings={
            "BIENTAN.17": [
                {"internal_code": "PV01.0117500", "customs_code": "BIENTAN.17"},
                {"internal_code": "PV02.0229000", "customs_code": "BIENTAN.17"},
            ],
        },
    )
    pid = resolve_product_identity(row, ctx=ctx)

    assert pid["resolution_status"] == "ambiguous"
    assert pid["resolved_code"] is None
    assert pid["bom_product_code"] is None
    # Two low-confidence candidates from code_mappings.
    assert len(pid["candidates"]) == 2
    assert all(c["confidence"] == "low"
               and c["source"] == "code_mapping_candidate"
               for c in pid["candidates"])


def test_single_code_mapping_returns_unverified_not_resolved():
    """Even a single code_mappings hit is `unverified` — code-mappings
    can't resolve on their own per spec R1."""
    row = {
        **GROWATT_ROW,
        "goods_name": "BIENTAN.17#&No paren BOM code here#&VN",
    }
    ctx = _ctx(
        materials=[("PV01.0117500", "tp", 1)],
        code_mappings={
            "BIENTAN.17": [
                {"internal_code": "PV01.0117500", "customs_code": "BIENTAN.17"},
            ],
        },
    )
    pid = resolve_product_identity(row, ctx=ctx)

    assert pid["resolution_status"] == "unverified"
    assert pid["bom_product_code"] is None
    assert pid["selected_candidate_code"] == "PV01.0117500"


# ─────────────────────────────────────────────────────────────────────
# Stage 3: reviewed_line_mapping
# ─────────────────────────────────────────────────────────────────────

def test_reviewed_line_mapping_resolves_high_confidence():
    """A 'reviewed' mapping for this exact line_key resolves with
    review_status='reviewed' (operator-confirmed)."""
    row = {
        **GROWATT_ROW,
        "goods_name": "BIENTAN.17#&No paren code here#&VN",
    }
    ctx = _ctx(
        materials=[("PV01.0117500", "tp", 1)],
        reviewed={
            ("307591379560", "3", "307591379560-3"): {
                "bom_product_code": "PV01.0117500",
                "status": "reviewed",
                "reviewed_by": "ops@data-hub.local",
                "reviewed_at": "2026-05-07T10:00:00Z",
            },
        },
    )
    pid = resolve_product_identity(row, ctx=ctx)

    assert pid["resolution_status"] == "resolved"
    assert pid["resolved_code"] == "PV01.0117500"
    assert pid["bom_product_code"] == "PV01.0117500"
    assert pid["resolution_source"] == "reviewed_line_mapping"
    assert pid["review_status"] == "reviewed"


def test_reviewed_code_with_no_catalog_entry_returns_unverified():
    """Guard: a reviewed mapping pointing at a code that's no longer in
    materials must NOT return resolved (consumer would fail to load it).
    Downgrade to unverified with the reviewed candidate retained for UI."""
    row = {
        **GROWATT_ROW,
        "goods_name": "BIENTAN.17#&No paren code here#&VN",
    }
    ctx = _ctx(
        materials=[],  # The reviewed code is GONE from catalog.
        reviewed={
            ("307591379560", "3", "307591379560-3"): {
                "bom_product_code": "PV01.0117500",
                "status": "reviewed",
                "reviewed_by": "ops@data-hub.local",
                "reviewed_at": "2026-05-07T10:00:00Z",
            },
        },
    )
    pid = resolve_product_identity(row, ctx=ctx)

    assert pid["resolution_status"] == "unverified"
    assert pid["bom_product_code"] is None
    assert pid["selected_candidate_code"] == "PV01.0117500"
    assert pid["resolution_source"] == "reviewed_line_mapping"
    assert pid["evidence"]["match_rule"] == "reviewed_code_no_alive_bom"


def test_reviewed_code_now_classified_as_nvl_resolves_with_no_bom_alias():
    """A reviewed mapping that points at an NVL code (kind=nvl, no BOM)
    still resolves — the consumer chose this code intentionally. But
    `bom_product_code` alias stays None because the code has no BOM."""
    row = {
        **GROWATT_ROW,
        "goods_name": "BIENTAN.17#&No paren code here#&VN",
    }
    ctx = _ctx(
        materials=[("NVL.001", "nvl", 0)],  # NVL with no BOM artifacts.
        reviewed={
            ("307591379560", "3", "307591379560-3"): {
                "bom_product_code": "NVL.001",
                "status": "reviewed",
                "reviewed_by": "ops@data-hub.local",
                "reviewed_at": "2026-05-07T10:00:00Z",
            },
        },
    )
    pid = resolve_product_identity(row, ctx=ctx)

    assert pid["resolution_status"] == "resolved"
    assert pid["resolved_code"] == "NVL.001"
    assert pid["bom_product_code"] is None  # alias gated by has_bom
    assert pid["product_kind"] == "nvl"


def test_rejected_review_blocks_other_evidence():
    """A 'rejected' review for a line acts as a kill switch — even when
    code-mappings would otherwise produce candidates, the row stays missing."""
    row = {
        **GROWATT_ROW,
        "goods_name": "BIENTAN.17#&No paren code here#&VN",
    }
    ctx = _ctx(
        materials=[("PV01.0117500", "tp", 1)],
        code_mappings={
            "BIENTAN.17": [
                {"internal_code": "PV01.0117500", "customs_code": "BIENTAN.17"},
            ],
        },
        reviewed={
            ("307591379560", "3", "307591379560-3"): {
                "bom_product_code": None,
                "status": "rejected",
                "reviewed_by": "ops@data-hub.local",
                "reviewed_at": "2026-05-07T10:00:00Z",
            },
        },
    )
    pid = resolve_product_identity(row, ctx=ctx)

    assert pid["resolution_status"] == "missing"
    assert pid["bom_product_code"] is None
    assert pid["candidates"] == []


# ─────────────────────────────────────────────────────────────────────
# Stage 5: missing
# ─────────────────────────────────────────────────────────────────────

def test_no_evidence_returns_missing():
    row = {
        **GROWATT_ROW,
        "customs_code": "BIENTAN.17",
        "goods_name": "BIENTAN.17#&Plain text no codes#&VN",
    }
    ctx = _ctx(materials=[("PV01.0117500", "tp", 1)])  # not relevant
    pid = resolve_product_identity(row, ctx=ctx)

    assert pid["resolution_status"] == "missing"
    assert pid["resolved_code"] is None
    assert pid["bom_product_code"] is None
    assert pid["product_kind"] is None
    assert pid["candidates"] == []
    assert pid["resolution_source"] == "none"


# ─────────────────────────────────────────────────────────────────────
# NVL / import resolution (BCQT use case)
# ─────────────────────────────────────────────────────────────────────

def test_nvl_import_customs_code_resolves_via_structured_field():
    """An import row whose customs_code is an NVL in materials catalog
    resolves. resolved_code is set; bom_product_code stays None
    because NVL has no BOM artifact (preserves CO 'load BOM if non-null')."""
    row = {
        **GROWATT_ROW,
        "customs_code": "NVL.PE001",
        "internal_code": "NVL.PE001",
        "goods_name": "NVL.PE001#&Polyethylene resin#&CN",
    }
    ctx = _ctx(materials=[("NVL.PE001", "nvl", 0)])  # NVL: no BOM.
    pid = resolve_product_identity(row, ctx=ctx)

    assert pid["resolution_status"] == "resolved"
    assert pid["resolved_code"] == "NVL.PE001"
    assert pid["bom_product_code"] is None  # alias gated by has_bom
    assert pid["product_kind"] == "nvl"
    assert pid["resolution_source"] == "structured_field"


def test_btp_import_resolves_with_kind_btp_sx():
    """A BTP import (semi-finished good) resolves with product_kind=btp_sx.
    bom_product_code may or may not be populated depending on whether
    the BTP has its own BOM artifact."""
    row = {
        **GROWATT_ROW,
        "customs_code": "BTP.MOTOR01",
        "internal_code": "BTP.MOTOR01",
        "goods_name": "BTP.MOTOR01#&Motor sub-assembly#&CN",
    }
    # BTP with own BOM artifact (Growatt-shape).
    ctx = _ctx(materials=[("BTP.MOTOR01", "btp_sx", 2)])
    pid = resolve_product_identity(row, ctx=ctx)

    assert pid["resolution_status"] == "resolved"
    assert pid["resolved_code"] == "BTP.MOTOR01"
    assert pid["bom_product_code"] == "BTP.MOTOR01"  # has BOM
    assert pid["product_kind"] == "btp_sx"


# ─────────────────────────────────────────────────────────────────────
# Cross-client isolation
# ─────────────────────────────────────────────────────────────────────

def test_resolver_does_not_consider_other_clients():
    """Context is built per-client; cross-client codes aren't in
    `material_catalog`. With empty catalog, no resolve."""
    ctx = _ctx(materials=[])
    pid = resolve_product_identity(GROWATT_ROW, ctx=ctx)
    assert pid["resolution_status"] != "resolved"


# ─────────────────────────────────────────────────────────────────────
# Candidate cap (D8)
# ─────────────────────────────────────────────────────────────────────

# ─────────────────────────────────────────────────────────────────────
# Adapter dispatch — pin real-world client config values
# ─────────────────────────────────────────────────────────────────────

def test_adapter_dispatch_for_real_growatt_mode():
    """Real Growatt clients have code_resolution_mode='batch_aggregate_resolution',
    NOT 'growatt'. Dispatcher must route them to the Growatt adapter.
    Regression test: an earlier dispatcher hardcoded 'growatt' and
    silently returned identity for actual Growatt clients."""
    from app.parsers.bcct_adapters import adapter_for_client
    a = adapter_for_client("growatt-vn", "batch_aggregate_resolution")
    assert a.name == "growatt_bcct"


def test_adapter_dispatch_for_identity_mode():
    from app.parsers.bcct_adapters import adapter_for_client
    a = adapter_for_client("dke-vietnam-d0e3", "identity")
    assert a.name == "identity"


def test_adapter_dispatch_for_null_mode():
    """Null mode falls through to Growatt (matches internal_code_parser_for)."""
    from app.parsers.bcct_adapters import adapter_for_client
    a = adapter_for_client("any-client", None)
    assert a.name == "growatt_bcct"


# ─────────────────────────────────────────────────────────────────────
# DB-backed context factory (ResolverContext.from_db)
# ─────────────────────────────────────────────────────────────────────

def test_from_db_loads_catalog_mappings_reviewed():
    """End-to-end: context factory reads materials catalog (with has_bom
    flag), code_mappings, and reviewed line mappings for a single client.
    Cross-client data must NOT appear."""
    from app.database import connect

    client = "ctx_from_db_test"
    other = "other_client_test"
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "insert into hub.clients (client_id, name) values (%s, %s), (%s, %s) "
            "on conflict (client_id) do nothing",
            (client, "ctx test", other, "other"),
        )
        # Materials: TP w/BOM, TP w/BOM, NVL w/o BOM, plus cross-client TP.
        for cid, code, kind in [
            (client, "PV01.0117500", "tp"),
            (client, "PV02.0229000", "tp"),
            (client, "NVL.PE001", "nvl"),
            (other,  "PV99.9999999", "tp"),
        ]:
            cur.execute(
                "insert into hub.materials (client_id, customs_code, "
                "internal_code, name, category) values (%s, %s, %s, %s, %s) "
                "on conflict do nothing",
                (cid, code, code, code, kind),
            )
        # BOM artifacts only for the two TPs in `client` (and the other).
        for cid, code, art_id in [
            (client, "PV01.0117500", "ba_test_a"),
            (client, "PV02.0229000", "ba_test_b"),
            (other,  "PV99.9999999", "ba_test_c"),
        ]:
            cur.execute(
                "insert into hub.bom_artifacts (artifact_id, client_id, "
                "product_code, artifact_no, actor, intent, normalized_hash, "
                "source_bom_kind, flatten_status, flatten_strategy, "
                "source_channel, flatten_method, flatten_method_version, "
                "status, published_at) "
                "values (%s, %s, %s, 1, 'agency_staff', 'asserted_technical', "
                "%s, 'technical_flattened', 'flattened', 'technical_exploded', "
                "'agency_upload', 'manual', '0.1', 'published', now()) "
                "on conflict (artifact_id) do nothing",
                (art_id, cid, code, f"hash_{art_id}"),
            )
        cur.execute(
            "insert into hub.code_mappings (client_id, internal_code, customs_code) "
            "values (%s, %s, %s) on conflict do nothing",
            (client, "PV01.0117500", "BIENTAN.17"),
        )
        cur.execute(
            "insert into hub.bcct_product_identity_review "
            "(client_id, declaration_no, line_no, transaction_key, "
            " bom_product_code, status, reviewed_by) "
            "values (%s, %s, %s, %s, %s, %s, %s)",
            (client, "DECLAA1", "1", "DECLAA1-1",
             "PV02.0229000", "reviewed", "ops@test"),
        )

    try:
        with connect() as conn, conn.cursor() as cur:
            ctx = ResolverContext.from_db(client, cur)
        # Catalog has only this client's materials.
        assert "PV01.0117500" in ctx.material_catalog
        assert "PV02.0229000" in ctx.material_catalog
        assert "NVL.PE001" in ctx.material_catalog
        assert "PV99.9999999" not in ctx.material_catalog
        # has_bom signals BOM-backed kind.
        assert ctx.material_catalog["PV01.0117500"]["has_bom"] is True
        assert ctx.material_catalog["PV01.0117500"]["category"] == "tp"
        # NVL has no BOM artifact → has_bom False.
        assert ctx.material_catalog["NVL.PE001"]["has_bom"] is False
        assert ctx.material_catalog["NVL.PE001"]["category"] == "nvl"
        # Mappings keyed by both sides.
        assert any(e["internal_code"] == "PV01.0117500"
                   for e in ctx.code_mappings.get("BIENTAN.17", []))
        assert any(e["customs_code"] == "BIENTAN.17"
                   for e in ctx.code_mappings.get("PV01.0117500", []))
        # Reviewed mapping loaded.
        assert ("DECLAA1", "1", "DECLAA1-1") in ctx.reviewed
        rev = ctx.reviewed[("DECLAA1", "1", "DECLAA1-1")]
        assert rev["bom_product_code"] == "PV02.0229000"
        assert rev["status"] == "reviewed"
    finally:
        with connect() as conn, conn.cursor() as cur:
            cur.execute(
                "delete from hub.bcct_product_identity_review where client_id=%s",
                (client,),
            )
            cur.execute("delete from hub.code_mappings where client_id=%s", (client,))
            cur.execute(
                "delete from hub.bom_artifacts where client_id in (%s, %s)",
                (client, other),
            )
            cur.execute(
                "delete from hub.materials where client_id in (%s, %s)",
                (client, other),
            )
            cur.execute("delete from hub.clients where client_id in (%s, %s)",
                        (client, other))


def test_candidate_limit_caps_returned_candidates():
    """`candidate_limit` truncates the candidates[] list."""
    row = {
        **GROWATT_ROW,
        "goods_name": (
            "X#&(PV01.0001000) (PV01.0002000) (PV01.0003000) "
            "(PV01.0004000) (PV01.0005000) (PV01.0006000) (PV01.0007000)#&VN"
        ),
    }
    ctx = _ctx(materials=[(f"PV01.000{i}000", "tp", 1) for i in range(1, 8)])
    ctx.candidate_limit = 3
    pid = resolve_product_identity(row, ctx=ctx)

    assert pid["resolution_status"] == "ambiguous"
    assert len(pid["candidates"]) == 3

