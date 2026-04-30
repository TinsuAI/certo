from __future__ import annotations

from app.database import database_url
from app.source_index_store import (
    build_bcct_index_records,
    build_catalog_index_records,
    build_co_stock_index_records,
    build_correction_candidate_records,
    build_source_state_records,
    get_source_index_store,
    source_metadata_record_from_state,
    source_state_from_workspace,
)
from app.source_store import (
    SourceParseError,
    add_upload_record,
    append_audit,
    assert_unique_keys,
    bcct_rows_equal,
    catalog_module,
    co_stock_rows_from_bcct,
    correction_candidate,
    correction_candidate_exists,
    import_row_id,
    key_field,
    merge_catalog_rows,
    module_lock,
    normalized_rows_hash,
    parse_bcct_workbook,
    parse_catalog_workbook,
    publish_version,
    write_snapshot,
)


SOURCE_MODULES = ("material_catalog", "product_catalog", "bcct")


def get_source_write_store() -> "PostgresSourceWriteStore | None":
    url = database_url()
    return PostgresSourceWriteStore(url) if url else None


class PostgresSourceWriteStore:
    def __init__(self, url: str):
        self.url = url

    def has_client(self, client_id: str) -> bool:
        store = get_source_index_store()
        return bool(store and store.has_client(client_id))

    def process_catalog_upload(self, client: dict, catalog_type: str, content: bytes, filename: str, upload_scope: str, client_config: dict) -> dict:
        module = catalog_module(catalog_type)
        upload_scope = upload_scope if upload_scope in {"full_catalog", "partial_update"} else "full_catalog"
        with module_lock(client["id"], module):
            states = self.client_source_states(client["id"], client_config)
            state = states[module]
            upload = add_upload_record(client["id"], module, state, content, filename, {"upload_scope": upload_scope})
            try:
                rows = parse_catalog_workbook(content, module)
                assert_unique_keys(rows, key_field(module))
            except SourceParseError as exc:
                upload["parse_status"] = "failed"
                upload["parse_error"] = str(exc)
                upload["result"] = "failed"
                append_audit(state, f"{module}.parse.failed", {"upload_id": upload["upload_id"], "error": str(exc)})
                states[module] = state
                self.persist_client_source(client["id"], states, client_config)
                return {"status": "failed", "message": str(exc), "upload": upload}

            snapshot_id = write_snapshot(client["id"], module, upload["upload_id"], rows, write_artifacts=False)
            upload["parse_status"] = "parsed"
            upload["snapshot_id"] = snapshot_id
            upload["snapshot_rows_hash"] = normalized_rows_hash(rows)
            upload["row_count"] = len(rows)

            result_rows, summary = merge_catalog_rows(state["published_rows"], rows, module, upload_scope)
            upload["diff_summary"] = summary
            if normalized_rows_hash(result_rows) == normalized_rows_hash(state["published_rows"]):
                upload["result"] = "no_change"
                append_audit(state, f"{module}.diff.no_change", {"upload_id": upload["upload_id"]})
                states[module] = state
                self.persist_client_source(client["id"], states, client_config)
                return {"status": "no_change", "message": "No catalog changes.", "summary": summary, "upload": upload}

            version = publish_version(client["id"], module, state, result_rows, upload["upload_id"], summary, write_artifacts=False)
            version["snapshot_id"] = snapshot_id
            upload["result"] = "new_version"
            upload["created_version_id"] = version["version_id"]
            append_audit(state, f"{module}.version.published", {"version_id": version["version_id"], "upload_id": upload["upload_id"]})
            states[module] = state
            self.persist_client_source(client["id"], states, client_config)
            return {"status": "new_version", "message": f"Published {module} v{version['version_no']}.", "summary": summary, "upload": upload, "version": version}

    def process_bcct_upload(self, client: dict, content: bytes, filename: str, client_config: dict) -> dict:
        module = "bcct"
        with module_lock(client["id"], module):
            states = self.client_source_states(client["id"], client_config)
            state = states[module]
            upload = add_upload_record(client["id"], module, state, content, filename, {"upload_scope": "append_or_review_by_transaction_key"})
            try:
                rows = parse_bcct_workbook(content)
            except SourceParseError as exc:
                upload["parse_status"] = "failed"
                upload["parse_error"] = str(exc)
                upload["result"] = "failed"
                append_audit(state, "bcct.parse.failed", {"upload_id": upload["upload_id"], "error": str(exc)})
                states[module] = state
                self.persist_client_source(client["id"], states, client_config)
                return {"status": "failed", "message": str(exc), "upload": upload}

            snapshot_id = write_snapshot(client["id"], module, upload["upload_id"], rows, write_artifacts=False)
            upload["parse_status"] = "parsed"
            upload["snapshot_id"] = snapshot_id
            upload["snapshot_rows_hash"] = normalized_rows_hash(rows)
            upload["row_count"] = len(rows)

            existing_by_key = {row["transaction_key"]: row for row in state["published_rows"]}
            added_rows = []
            unchanged_rows = 0
            new_candidates = []
            for row in rows:
                existing = existing_by_key.get(row["transaction_key"])
                if existing is None:
                    published_row = {**row, "source_upload_id": upload["upload_id"], "review_status": "reviewed"}
                    if row["direction"] == "import":
                        published_row["import_row_id"] = import_row_id(row["transaction_key"])
                    added_rows.append(published_row)
                    existing_by_key[row["transaction_key"]] = published_row
                    continue
                if bcct_rows_equal(existing, row):
                    unchanged_rows += 1
                    continue
                candidate = correction_candidate(existing, row, upload["upload_id"])
                if not correction_candidate_exists(state["correction_candidates"], candidate):
                    new_candidates.append(candidate)

            if added_rows:
                state["published_rows"].extend(added_rows)
                state["published_rows"].sort(key=lambda row: (row["direction"], row["declaration_no"], row["line_no"], row["item_code"]))
            state["correction_candidates"].extend(new_candidates)

            summary = {
                "added_rows": len(added_rows),
                "unchanged_rows": unchanged_rows,
                "correction_candidates": len(new_candidates),
                "published_rows": len(state["published_rows"]),
            }
            upload["result"] = "review_required" if new_candidates else ("new_version" if added_rows else "no_change")
            upload["diff_summary"] = summary

            version = None
            if added_rows:
                version = publish_version(client["id"], module, state, state["published_rows"], upload["upload_id"], summary, write_artifacts=False)
                version["snapshot_id"] = snapshot_id
                upload["created_version_id"] = version["version_id"]
            append_audit(state, "bcct.diff.completed", {"upload_id": upload["upload_id"], **summary})
            states[module] = state
            self.persist_client_source(client["id"], states, client_config)

            status = "review_required" if new_candidates else ("new_version" if added_rows else "no_change")
            message = "BCCT has correction candidates." if new_candidates else ("Published BCCT rows." if added_rows else "No BCCT changes.")
            return {"status": status, "message": message, "summary": summary, "upload": upload, "version": version, "correction_candidates": new_candidates}

    def client_source_states(self, client_id: str, client_config: dict) -> dict[str, dict]:
        store = get_source_index_store()
        if store is None:
            raise RuntimeError("Postgres source index store is not configured.")
        workspace = store.source_workspace(client_id, client_config)
        return {
            module: source_state_from_workspace(client_id, module, workspace[module])
            for module in SOURCE_MODULES
        }

    def persist_client_source(self, client_id: str, states: dict[str, dict], client_config: dict) -> None:
        store = get_source_index_store()
        if store is None:
            raise RuntimeError("Postgres source index store is not configured.")

        stock_rows = co_stock_rows_from_bcct(states["bcct"]["published_rows"], client_config)
        catalog_records = (
            build_catalog_index_records(client_id, "material_catalog", states["material_catalog"]["published_rows"])
            + build_catalog_index_records(client_id, "product_catalog", states["product_catalog"]["published_rows"])
        )
        bcct_records, invoice_records = build_bcct_index_records(client_id, states["bcct"]["published_rows"])
        stock_records = build_co_stock_index_records(client_id, stock_rows)
        correction_records = (
            build_correction_candidate_records(client_id, "material_catalog", states["material_catalog"].get("correction_candidates", []))
            + build_correction_candidate_records(client_id, "product_catalog", states["product_catalog"].get("correction_candidates", []))
            + build_correction_candidate_records(client_id, "bcct", states["bcct"].get("correction_candidates", []))
        )
        metadata = [
            source_metadata_record_from_state(client_id, "material_catalog", states["material_catalog"]),
            source_metadata_record_from_state(client_id, "product_catalog", states["product_catalog"]),
            source_metadata_record_from_state(client_id, "bcct", states["bcct"]),
            {
                "client_id": client_id,
                "module": "co_stock",
                "version_id": "",
                "version_no": 0,
                "published_row_count": len(stock_rows),
                "reviewed_row_count": 0,
                "correction_candidate_count": 0,
                "state_mtime_ns": 0,
                "config_hash": client_config.get("config_hash", ""),
            },
        ]
        source_state_records = [
            build_source_state_records(client_id, "material_catalog", states["material_catalog"]),
            build_source_state_records(client_id, "product_catalog", states["product_catalog"]),
            build_source_state_records(client_id, "bcct", states["bcct"]),
        ]
        store.replace_client_indexes(
            client_id,
            catalog_records,
            bcct_records,
            invoice_records,
            stock_records,
            correction_records,
            metadata,
            source_state_records,
        )
