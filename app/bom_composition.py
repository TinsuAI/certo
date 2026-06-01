from __future__ import annotations



def group_rows_by_product(rows: list[dict]) -> dict[str, list[dict]]:
    groups: dict[str, list[dict]] = {}
    for row in rows:
        product_code = row.get("product_code", "")
        if not product_code:
            continue
        groups.setdefault(product_code, []).append(row)
    return {key: sorted(value, key=lambda row: row["row_key"]) for key, value in sorted(groups.items())}
def latest_product_version(state: dict, product_code: str) -> dict | None:
    versions = state.get("product_versions", {}).get(product_code, [])
    if not versions:
        return None
    return max(versions, key=lambda version: version["product_version_no"])
def flattened_product_versions(state: dict) -> list[dict]:
    output = []
    for product_code in sorted(state.get("product_versions", {})):
        output.extend(
            sorted(
                state["product_versions"][product_code],
                key=lambda version: version["product_version_no"],
                reverse=True,
            )
        )
    return output
def product_version_options_by_code(product_versions: list[dict]) -> dict[str, list[dict]]:
    output: dict[str, list[dict]] = {}
    for version in product_versions:
        output.setdefault(version["product_code"], []).append(version)
    return output
def latest_composition_map(state: dict) -> dict[str, dict]:
    latest = latest_published_version(state)
    if latest.get("product_versions"):
        return {row["product_code"]: dict(row) for row in latest["product_versions"]}
    return {
        product_code: composition_entry(version)
        for product_code, version in (
            (product_code, latest_product_version(state, product_code))
            for product_code in state.get("product_versions", {})
        )
        if version
    }
def composition_entry(product_version: dict) -> dict:
    product_artifact_id = product_version.get("product_artifact_id") or product_version["product_version_id"]
    product_artifact_no = product_version.get("product_artifact_no") or product_version["product_version_no"]
    return {
        "product_code": product_version["product_code"],
        "product_artifact_id": product_artifact_id,
        "product_artifact_no": product_artifact_no,
        "product_version_id": product_artifact_id,
        "product_version_no": product_artifact_no,
        "version_hash": product_version["version_hash"],
        "row_count": product_version["row_count"],
        "status": product_version.get("status", "current"),
    }
def with_aggregate_rows(state: dict, version: dict) -> dict:
    output = dict(version)
    if "rows" not in output:
        output["rows"] = compose_rows_from_composition(state, output.get("product_versions", []))
    output["row_count"] = len(output.get("rows", []))
    output.setdefault("product_versions", [])
    return output
def compose_rows_from_composition(state: dict, composition: list[dict]) -> list[dict]:
    return compose_rows_from_product_versions(state.get("product_versions", {}), composition)
def compose_rows_from_product_versions(product_versions: dict[str, list[dict]], composition: list[dict]) -> list[dict]:
    version_index = {
        version["product_version_id"]: version
        for versions in product_versions.values()
        for version in versions
    }
    rows = []
    for entry in sorted(composition, key=lambda row: row["product_code"]):
        product_version = version_index.get(entry["product_version_id"])
        if not product_version:
            continue
        for row in product_version.get("rows", []):
            enriched = dict(row)
            enriched["product_version_id"] = product_version["product_version_id"]
            enriched["product_version_no"] = product_version["product_version_no"]
            rows.append(enriched)
    return rows
def latest_published_version(state: dict) -> dict:
    published = [version for version in state.get("versions", []) if version["status"] == "published"]
    if not published:
        return {"version_no": 0, "version_id": "", "rows": []}
    return max(published, key=lambda version: version["version_no"])
