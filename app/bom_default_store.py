"""Per-client default BOM pick per product code (#14).

When staff pick a BOM (định mức) artifact for a product, that pick is saved
as the client's default for that product code (pin the chosen version). Later
cases auto-reuse it unless overridden per-case. See
.ai/features/2026-06-18-bom-default-batch-flow.md (Slice A).

Storage strategy mirrors cost_allocation_store:
- Postgres is authoritative when BARRY_DATABASE_URL is set.
- JSON file fallback at config/bom-default/<client>.json keeps dev flowing.
  When both are available, writes go to both; reads prefer DB.

The default value is an artifact_id (a specific BOM version) — we intentionally
do NOT auto-upgrade to a newer version (user chose "pin").
"""
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

from app.database import DatabaseUnavailable, connect, database_url


# ---------- DB plumbing ----------


def _db_available() -> bool:
    return bool(database_url())


def _db_read(client_id: str) -> dict[str, str]:
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "select product_code, artifact_id from co_bom_product_default where client_id = %s",
            (client_id,),
        )
        return {str(code): str(artifact_id) for code, artifact_id in cur.fetchall() if code and artifact_id}


def _db_upsert(client_id: str, product_code: str, artifact_id: str) -> None:
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            """
            insert into co_bom_product_default
              (client_id, product_code, artifact_id, updated_at)
            values (%s, %s, %s, now())
            on conflict (client_id, product_code) do update set
              artifact_id = excluded.artifact_id,
              updated_at = now()
            """,
            (client_id, product_code, artifact_id),
        )


def _db_delete(client_id: str, product_code: str) -> None:
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "delete from co_bom_product_default where client_id = %s and product_code = %s",
            (client_id, product_code),
        )


# ---------- JSON fallback ----------


def _config_root() -> Path:
    return Path(os.environ.get("BOM_DEFAULT_CONFIG_ROOT", "config/bom-default"))


def _json_path(client_id: str) -> Path:
    return _config_root() / f"{client_id}.json"


def _json_read(client_id: str) -> dict[str, str]:
    path = _json_path(client_id)
    if not path.exists():
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    defaults = payload.get("defaults") or {}
    return {str(code): str(art) for code, art in defaults.items() if code and art}


def _json_write(client_id: str, defaults: dict[str, str]) -> None:
    path = _json_path(client_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"client_id": client_id, "defaults": defaults}
    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")
    os.replace(tmp_name, path)


# ---------- Public API ----------


def get_defaults(client_id: str) -> dict[str, str]:
    """Return {product_code: artifact_id} of the client's default BOM picks."""
    if not client_id:
        return {}
    if _db_available():
        try:
            return _db_read(client_id)
        except DatabaseUnavailable:
            pass
    return _json_read(client_id)


def get_default(client_id: str, product_code: str) -> str | None:
    return get_defaults(client_id).get(str(product_code or "").strip()) or None


def set_default(client_id: str, product_code: str, artifact_id: str) -> None:
    client_id = str(client_id or "").strip()
    product_code = str(product_code or "").strip()
    artifact_id = str(artifact_id or "").strip()
    if not (client_id and product_code and artifact_id):
        return
    if _db_available():
        try:
            _db_upsert(client_id, product_code, artifact_id)
        except DatabaseUnavailable:
            pass
    defaults = _json_read(client_id)
    defaults[product_code] = artifact_id
    _json_write(client_id, defaults)


def delete_default(client_id: str, product_code: str) -> None:
    client_id = str(client_id or "").strip()
    product_code = str(product_code or "").strip()
    if not (client_id and product_code):
        return
    if _db_available():
        try:
            _db_delete(client_id, product_code)
        except DatabaseUnavailable:
            pass
    defaults = _json_read(client_id)
    defaults.pop(product_code, None)
    _json_write(client_id, defaults)


def picks_from_payload(payload: dict) -> dict[str, str]:
    """Extract explicit BOM picks {product_code: artifact_id} from an action
    payload. Per-product fields win over the overrides map (matches
    merge_origin_action_payload)."""
    picks: dict[str, str] = {}
    if not isinstance(payload, dict):
        return picks
    incoming = payload.get("bom_product_artifact_overrides")
    if isinstance(incoming, dict):
        for code, artifact_id in incoming.items():
            code = str(code or "").strip()
            artifact_id = str(artifact_id or "").strip()
            if code and artifact_id:
                picks[code] = artifact_id
    for product in payload.get("products") or []:
        if not isinstance(product, dict):
            continue
        code = str(product.get("code") or product.get("product_code") or "").strip()
        artifact_id = str(
            product.get("bom_product_artifact_id") or product.get("bom_product_version_id") or ""
        ).strip()
        if code and artifact_id:
            picks[code] = artifact_id
    return picks
