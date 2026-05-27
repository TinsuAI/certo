"""Cost allocation ratio store — per-client × per-Mã-SP coefficients.

Drives the cost-buildup auto-fill on origin product panels. See
.ai/features/2026-05-27-cost-allocation-ratios.md for the data model.

Storage strategy:
- Postgres is authoritative when BARRY_DATABASE_URL is set.
- JSON file fallback at config/cost-allocation/<client>.json keeps dev
  flowing without Postgres. When both are available, writes go to both;
  reads prefer DB.
- Mode B (per-client default) is stored as a row with product_code = ''.
"""
from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Iterable

from app.database import DatabaseUnavailable, connect, database_url


_COEF_FIELDS = (
    "coef_wages",
    "coef_welfare",
    "coef_rent",
    "coef_depreciation",
    "coef_other_mfg",
    "coef_transport_storage",
)


@dataclass
class CostAllocationRow:
    product_code: str  # '' = Mode B default
    coef_wages: Decimal = Decimal(0)
    coef_welfare: Decimal = Decimal(0)
    coef_rent: Decimal = Decimal(0)
    coef_depreciation: Decimal = Decimal(0)
    coef_other_mfg: Decimal = Decimal(0)
    coef_transport_storage: Decimal = Decimal(0)
    note: str = ""
    updated_at: str = ""

    def coef_dict(self) -> dict[str, Decimal]:
        return {key: getattr(self, key) for key in _COEF_FIELDS}

    def to_json(self) -> dict:
        return {
            "product_code": self.product_code,
            **{key: str(getattr(self, key)) for key in _COEF_FIELDS},
            "note": self.note,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_json(cls, payload: dict) -> "CostAllocationRow":
        return cls(
            product_code=str(payload.get("product_code", "")),
            coef_wages=_dec(payload.get("coef_wages")),
            coef_welfare=_dec(payload.get("coef_welfare")),
            coef_rent=_dec(payload.get("coef_rent")),
            coef_depreciation=_dec(payload.get("coef_depreciation")),
            coef_other_mfg=_dec(payload.get("coef_other_mfg")),
            coef_transport_storage=_dec(payload.get("coef_transport_storage")),
            note=str(payload.get("note", "") or ""),
            updated_at=str(payload.get("updated_at", "") or ""),
        )


def _dec(value) -> Decimal:
    if value is None or value == "":
        return Decimal(0)
    if isinstance(value, Decimal):
        return value
    try:
        return Decimal(str(value))
    except Exception:
        return Decimal(0)


# ---------- DB plumbing ----------


def _db_available() -> bool:
    return bool(database_url())


def _row_from_db(record) -> CostAllocationRow:
    return CostAllocationRow(
        product_code=record[0] or "",
        coef_wages=_dec(record[1]),
        coef_welfare=_dec(record[2]),
        coef_rent=_dec(record[3]),
        coef_depreciation=_dec(record[4]),
        coef_other_mfg=_dec(record[5]),
        coef_transport_storage=_dec(record[6]),
        note=record[7] or "",
        updated_at=record[8].isoformat() if record[8] else "",
    )


_SELECT_COLUMNS = (
    "product_code, coef_wages, coef_welfare, coef_rent, coef_depreciation, "
    "coef_other_mfg, coef_transport_storage, note, updated_at"
)


def _db_list(client_id: str) -> list[CostAllocationRow]:
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            f"select {_SELECT_COLUMNS} from co_cost_allocation_ratio where client_id = %s",
            (client_id,),
        )
        return [_row_from_db(r) for r in cur.fetchall()]


def _db_upsert(client_id: str, row: CostAllocationRow) -> None:
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            """
            insert into co_cost_allocation_ratio
              (client_id, product_code, coef_wages, coef_welfare, coef_rent,
               coef_depreciation, coef_other_mfg, coef_transport_storage,
               note, updated_at)
            values (%s, %s, %s, %s, %s, %s, %s, %s, %s, now())
            on conflict (client_id, product_code) do update set
              coef_wages = excluded.coef_wages,
              coef_welfare = excluded.coef_welfare,
              coef_rent = excluded.coef_rent,
              coef_depreciation = excluded.coef_depreciation,
              coef_other_mfg = excluded.coef_other_mfg,
              coef_transport_storage = excluded.coef_transport_storage,
              note = excluded.note,
              updated_at = now()
            """,
            (
                client_id,
                row.product_code,
                row.coef_wages,
                row.coef_welfare,
                row.coef_rent,
                row.coef_depreciation,
                row.coef_other_mfg,
                row.coef_transport_storage,
                row.note,
            ),
        )


def _db_delete(client_id: str, product_code: str) -> None:
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "delete from co_cost_allocation_ratio where client_id = %s and product_code = %s",
            (client_id, product_code),
        )


def _db_replace_per_product(client_id: str, rows: list[CostAllocationRow]) -> None:
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "delete from co_cost_allocation_ratio where client_id = %s and product_code <> ''",
            (client_id,),
        )
        for row in rows:
            if not row.product_code:
                continue
            cur.execute(
                """
                insert into co_cost_allocation_ratio
                  (client_id, product_code, coef_wages, coef_welfare, coef_rent,
                   coef_depreciation, coef_other_mfg, coef_transport_storage,
                   note, updated_at)
                values (%s, %s, %s, %s, %s, %s, %s, %s, %s, now())
                """,
                (
                    client_id,
                    row.product_code,
                    row.coef_wages,
                    row.coef_welfare,
                    row.coef_rent,
                    row.coef_depreciation,
                    row.coef_other_mfg,
                    row.coef_transport_storage,
                    row.note,
                ),
            )


# ---------- JSON fallback ----------


def _config_root() -> Path:
    return Path(os.environ.get("COST_ALLOCATION_CONFIG_ROOT", "config/cost-allocation"))


def _json_path(client_id: str) -> Path:
    return _config_root() / f"{client_id}.json"


def _json_read(client_id: str) -> list[CostAllocationRow]:
    path = _json_path(client_id)
    if not path.exists():
        return []
    payload = json.loads(path.read_text(encoding="utf-8"))
    rows = payload.get("rows") or []
    return [CostAllocationRow.from_json(r) for r in rows]


def _json_write(client_id: str, rows: list[CostAllocationRow]) -> None:
    path = _json_path(client_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "client_id": client_id,
        "rows": [r.to_json() for r in rows],
    }
    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")
    os.replace(tmp_name, path)


# ---------- Public API ----------


def list_ratios(client_id: str) -> list[CostAllocationRow]:
    """Return all per-Mã-SP rows for a client. Excludes the Mode B default."""
    rows = _read_all(client_id)
    return [r for r in rows if r.product_code]


def get_ratio(client_id: str, product_code: str) -> CostAllocationRow | None:
    """Mode A lookup with Mode B fallback. None if neither matches."""
    rows = _read_all(client_id)
    if product_code:
        for row in rows:
            if row.product_code == product_code:
                return row
    for row in rows:
        if not row.product_code:
            return row
    return None


def get_mode_b_default(client_id: str) -> CostAllocationRow | None:
    rows = _read_all(client_id)
    for row in rows:
        if not row.product_code:
            return row
    return None


def upsert_ratio(client_id: str, row: CostAllocationRow) -> None:
    row.updated_at = _now_iso()
    if _db_available():
        try:
            _db_upsert(client_id, row)
        except DatabaseUnavailable:
            pass
    rows = _json_read(client_id)
    replaced = False
    for i, existing in enumerate(rows):
        if existing.product_code == row.product_code:
            rows[i] = row
            replaced = True
            break
    if not replaced:
        rows.append(row)
    _json_write(client_id, rows)


def delete_ratio(client_id: str, product_code: str) -> None:
    if _db_available():
        try:
            _db_delete(client_id, product_code)
        except DatabaseUnavailable:
            pass
    rows = _json_read(client_id)
    rows = [r for r in rows if r.product_code != product_code]
    _json_write(client_id, rows)


def replace_all(client_id: str, new_rows: Iterable[CostAllocationRow]) -> dict:
    """Replace every per-Mã-SP row for the client. Mode B default is preserved.

    Returns {'added': [...], 'removed': [...], 'changed': [...]} where each
    list contains product codes.
    """
    new_rows = [r for r in new_rows if r.product_code]
    diff = diff_replace(client_id, new_rows)
    now = _now_iso()
    for row in new_rows:
        row.updated_at = now
    if _db_available():
        try:
            _db_replace_per_product(client_id, new_rows)
        except DatabaseUnavailable:
            pass
    # JSON write: keep Mode B, overwrite the rest.
    current = _json_read(client_id)
    mode_b = [r for r in current if not r.product_code]
    _json_write(client_id, mode_b + new_rows)
    return diff


def diff_replace(client_id: str, new_rows: list[CostAllocationRow]) -> dict:
    """Compute the delta replace_all would produce, without committing."""
    current = {r.product_code: r for r in list_ratios(client_id)}
    incoming = {r.product_code: r for r in new_rows if r.product_code}
    added = sorted(set(incoming) - set(current))
    removed = sorted(set(current) - set(incoming))
    changed = sorted(
        code for code in set(current) & set(incoming)
        if current[code].coef_dict() != incoming[code].coef_dict()
        or (current[code].note or "") != (incoming[code].note or "")
    )
    return {"added": added, "removed": removed, "changed": changed}


# ---------- Internals ----------


def _read_all(client_id: str) -> list[CostAllocationRow]:
    if _db_available():
        try:
            return _db_list(client_id)
        except DatabaseUnavailable:
            pass
    return _json_read(client_id)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()
