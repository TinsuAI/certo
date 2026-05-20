from __future__ import annotations

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DATA_HUB_ADAPTER = Path("app/data_hub_client.py")
APPROVED_DATA_HUB_ENDPOINTS = {
    "/v1/hub/dncxs",
    "/v1/hub/dncxs/{client_id}",
    "/v1/hub/dncxs/{client_id}/client-config",
    "/v1/hub/dncxs/{client_id}/source-summary",
    "/v1/hub/materials",
    "/v1/hub/bcct",
    "/v1/hub/bcct/invoice-matches",
    "/v1/hub/products",
    "/v1/hub/products/{product_code}/bom",
    "/v1/hub/products/{product_code}/bom/latest",
    "/v1/hub/products/{product_code}/bom/proposals",
    "/v1/hub/products/{product_code}/bom/artifacts",
    "/v1/hub/proposals/{proposal_id}",
    "/v1/hub/materials/{hub_path_part(material_code)}",
    "/v1/hub/clients/{hub_path_part(client_id)}/materials/{hub_path_part(material_code)}/substitutes",
    "/v1/hub/clients/{hub_path_part(client_id)}/bcct/by-codes",
    "/v1/hub/clients/{hub_path_part(client_id)}/declarations",
}


def _endpoint_literals(text: str) -> set[str]:
    pattern = r"""[furbFURB]*["']([^"']*/v1/hub[^"']*)["']"""
    return {match.group(1) for match in re.finditer(pattern, text)}


def test_raw_data_hub_api_calls_stay_in_adapter():
    violations: list[str] = []
    for path in sorted((ROOT / "app").rglob("*.py")):
        rel = path.relative_to(ROOT)
        if rel == DATA_HUB_ADAPTER:
            continue
        if "/v1/hub" in path.read_text(encoding="utf-8"):
            violations.append(str(rel))

    assert violations == [], (
        "Data Hub API calls must go through app/data_hub_client.py. "
        "If CO needs a new endpoint, create .ai/api-requests/YYYY-MM-DD-<slug>.md "
        "from .ai/templates/data-hub-api-request.md and wait for Data Hub contract approval. "
        f"Violations: {violations}"
    )


def test_data_hub_adapter_only_uses_approved_endpoints():
    adapter = (ROOT / DATA_HUB_ADAPTER).read_text(encoding="utf-8")
    endpoints = _endpoint_literals(adapter)

    assert endpoints <= APPROVED_DATA_HUB_ENDPOINTS, (
        "New Data Hub endpoint literals require a Data Hub API Request artifact "
        "and Data Hub-side contract/provider tests before CO consumes them. "
        f"Unapproved: {sorted(endpoints - APPROVED_DATA_HUB_ENDPOINTS)}"
    )


def test_data_hub_api_request_template_exists():
    template = ROOT / ".ai/templates/data-hub-api-request.md"
    assert template.exists()
    text = template.read_text(encoding="utf-8")
    required_sections = [
        "## Use Case",
        "## Existing Endpoint Gap",
        "## Proposed Contract",
        "## Auth",
        "## Data Semantics",
        "## Tests Required In Data Hub",
        "## CO Consumer Plan",
        "## Approval",
    ]
    assert all(section in text for section in required_sections)
