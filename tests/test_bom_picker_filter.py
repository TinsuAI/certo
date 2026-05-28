from __future__ import annotations

import httpx
import pytest

from app.bom_service import (
    DataHubBomService,
    PICKER_INTENTS,
    product_version_options_by_code,
)
from app.data_hub_client import DataHubClient


def _published(artifact_id: str, no: int, **extra) -> dict:
    base = {
        "artifact_id": artifact_id,
        "artifact_no": no,
        "row_count": 1,
        "status": "published",
        "flatten_status": "flattened",
        "tombstoned_at": None,
        "intent": "staff_edit",
    }
    base.update(extra)
    return base


def test_list_bom_artifacts_filtered_sends_picker_contract_and_reads_envelope():
    seen: list[tuple[str, dict]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append((request.url.path, dict(request.url.params)))
        return httpx.Response(
            200,
            json={
                "items": [_published("bv-1", 1)],
                "filter_applied": {
                    "lifecycle": "active",
                    "shape": "flat",
                    "intents": list(PICKER_INTENTS),
                    "latest_per_variant": True,
                    "case_id": "case-x",
                },
            },
        )

    client = DataHubClient(
        base_url="https://hub.test",
        token="tok",
        transport=httpx.MockTransport(handler),
    )

    envelope = client.list_bom_artifacts_filtered(
        "growatt-vn",
        "TP-1",
        intents=PICKER_INTENTS,
        case_id="case-x",
    )

    assert envelope["items"][0]["artifact_id"] == "bv-1"
    assert envelope["filter_applied"]["case_id"] == "case-x"
    path, params = seen[0]
    assert path == "/v1/hub/products/TP-1/bom/artifacts"
    assert params["lifecycle"] == "active"
    assert params["shape"] == "flat"
    assert params["latest_per_variant"] == "true"
    assert params["case_id"] == "case-x"
    assert set(params["intents"].split(",")) == set(PICKER_INTENTS)


def test_list_bom_artifacts_filtered_marks_missing_filter_applied_as_none():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"items": [_published("bv-1", 1)]})

    client = DataHubClient(
        base_url="https://hub.test",
        token="tok",
        transport=httpx.MockTransport(handler),
    )

    envelope = client.list_bom_artifacts_filtered("growatt-vn", "TP-1", case_id="case-x")
    assert envelope["filter_applied"] is None
    assert envelope["items"][0]["artifact_id"] == "bv-1"


def test_workspace_threads_case_id_into_filtered_adapter():
    captured: dict = {}

    class FakeDH:
        def list_bom_products(self, _client_id):
            return [{"product_code": "TP-1", "n_versions": 2}]

        def list_bom_artifacts_filtered(self, client_id, product_code, *, intents, lifecycle, shape, latest_per_variant, case_id):
            captured["call"] = {
                "client_id": client_id,
                "product_code": product_code,
                "intents": tuple(intents),
                "lifecycle": lifecycle,
                "shape": shape,
                "latest_per_variant": latest_per_variant,
                "case_id": case_id,
            }
            return {
                "items": [
                    _published("bv-1", 1),
                    _published("bv-2", 2, normalized_hash="h2"),
                ],
                "filter_applied": {"case_id": case_id},
            }

        def list_bom_artifacts(self, *_, **__):
            raise AssertionError("filtered adapter must win when case_id present")

        def get_bom_artifact(self, _client_id, product_code, artifact_id):
            return {
                "artifact": {
                    "artifact_id": artifact_id,
                    "product_code": product_code,
                    "artifact_no": int(artifact_id[-1]),
                    "row_count": 1,
                    "flatten_status": "flattened",
                },
                "rows": [{"material_code": "NVL-1", "qty_per_unit": 1, "uom": "PCS", "payload": {}}],
            }

    workspace = DataHubBomService(FakeDH()).workspace(
        {"id": "growatt-vn"}, case_id="co-case-abc"
    )

    assert captured["call"]["case_id"] == "co-case-abc"
    assert captured["call"]["lifecycle"] == "active"
    assert captured["call"]["shape"] == "flat"
    assert captured["call"]["latest_per_variant"] is True
    assert captured["call"]["intents"] == PICKER_INTENTS
    assert workspace["dh_picker_filter_active"] is True
    assert [v["product_version_id"] for v in workspace["product_version_options_by_code"]["TP-1"]] == ["bv-1", "bv-2"]


def test_workspace_falls_back_to_legacy_list_when_no_case_id():
    calls: list[str] = []

    class FakeDH:
        def list_bom_products(self, _client_id):
            return [{"product_code": "TP-1", "n_versions": 2}]

        def list_bom_artifacts_filtered(self, *_args, **_kwargs):
            calls.append("filtered")
            raise AssertionError("filtered path must not run without case_id")

        def list_bom_artifacts(self, client_id, product_code):
            calls.append("legacy")
            return [_published("bv-1", 1), _published("bv-2", 2)]

        def get_bom_artifact(self, _client_id, product_code, artifact_id):
            return {
                "artifact": {
                    "artifact_id": artifact_id,
                    "product_code": product_code,
                    "artifact_no": int(artifact_id[-1]),
                    "row_count": 1,
                    "flatten_status": "flattened",
                },
                "rows": [{"material_code": "NVL-1", "qty_per_unit": 1, "uom": "PCS", "payload": {}}],
            }

    workspace = DataHubBomService(FakeDH()).workspace({"id": "growatt-vn"})
    assert calls == ["legacy"]
    assert workspace["dh_picker_filter_active"] is False


def test_product_version_options_local_predicate_drops_tombstoned_draft_and_other_case_proposals():
    versions = [
        {
            "product_code": "TP-1",
            "product_version_id": "bv-keep",
            "product_version_no": 1,
            "status": "published",
            "flatten_status": "flattened",
            "intent": "staff_edit",
            "tombstoned_at": None,
        },
        {
            "product_code": "TP-1",
            "product_version_id": "bv-draft",
            "product_version_no": 2,
            "status": "draft",
            "flatten_status": "flattened",
            "intent": "staff_edit",
        },
        {
            "product_code": "TP-1",
            "product_version_id": "bv-superseded",
            "product_version_no": 3,
            "status": "superseded",
            "flatten_status": "flattened",
            "intent": "staff_edit",
        },
        {
            "product_code": "TP-1",
            "product_version_id": "bv-tomb",
            "product_version_no": 4,
            "status": "published",
            "flatten_status": "flattened",
            "intent": "staff_edit",
            "tombstoned_at": "2026-05-01T00:00:00Z",
        },
        {
            "product_code": "TP-1",
            "product_version_id": "bv-other-case",
            "product_version_no": 5,
            "status": "published",
            "flatten_status": "flattened",
            "intent": "modified_for_case",
            "context": {"case_id": "co-case-other"},
        },
        {
            "product_code": "TP-1",
            "product_version_id": "bv-this-case",
            "product_version_no": 6,
            "status": "published",
            "flatten_status": "flattened",
            "intent": "modified_for_case",
            "context": {"case_id": "co-case-mine"},
        },
    ]

    options = product_version_options_by_code(
        versions, case_id="co-case-mine", trust_server_filter=False
    )
    kept = {row["product_version_id"] for row in options["TP-1"]}
    assert kept == {"bv-keep", "bv-this-case"}


def test_product_version_options_trust_server_skips_local_predicate():
    versions = [
        {
            "product_code": "TP-1",
            "product_version_id": "bv-draft-but-ok",
            "product_version_no": 1,
            "status": "draft",  # would normally be filtered
            "flatten_status": "flattened",
            "intent": "staff_edit",
        },
    ]
    options = product_version_options_by_code(versions, trust_server_filter=True)
    assert [row["product_version_id"] for row in options["TP-1"]] == ["bv-draft-but-ok"]


def test_workspace_surfaces_dual_source_variants_as_separate_options():
    class FakeDH:
        def list_bom_products(self, _client_id):
            return [{"product_code": "TP-1", "n_versions": 2}]

        def list_bom_artifacts_filtered(self, client_id, product_code, **_kw):
            return {
                "items": [
                    _published("bv-leaf", 5, bom_variant_id="m16_2025", flatten_strategy="purchased_btp_as_leaf"),
                    _published("bv-exploded", 6, bom_variant_id="m16_2025", flatten_strategy="self_produced_btp_exploded"),
                ],
                "filter_applied": {"case_id": "co-case-x"},
            }

        def get_bom_artifact(self, _client_id, product_code, artifact_id):
            return {
                "artifact": {
                    "artifact_id": artifact_id,
                    "product_code": product_code,
                    "artifact_no": 5 if artifact_id == "bv-leaf" else 6,
                    "row_count": 1,
                    "flatten_status": "flattened",
                },
                "rows": [{"material_code": "NVL-1", "qty_per_unit": 1, "uom": "PCS", "payload": {}}],
            }

    workspace = DataHubBomService(FakeDH()).workspace(
        {"id": "growatt-vn"}, case_id="co-case-x"
    )
    ids = [row["product_version_id"] for row in workspace["product_version_options_by_code"]["TP-1"]]
    assert set(ids) == {"bv-leaf", "bv-exploded"}
