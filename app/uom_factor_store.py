"""Operator-confirmed ĐVT conversion factors, per client.

A factor answers a question about the material, not about units — "1 SET của mã này
là mấy PIECES" — so it comes from the person reading the declaration, and it is kept
with who confirmed it and when (an audit has to be able to see why 4 SETS became 20
PIECES on a filed bảng kê).

Storage mirrors `app/cost_allocation_store.py`: Postgres is authoritative when
BARRY_DATABASE_URL is set, with a JSON file fallback (CO_UOM_FACTOR_ROOT, default
`config/uom-factors/<client>.json`) so DB-less dev and the file-mode test suite work.
A row with `material_code = ''` applies client-wide; a row naming a material wins.
"""
from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path

from app.database import DatabaseUnavailable, connect, database_url
from app.uom_conversion import canonical_uom


@dataclass
class UomFactorRow:
    bom_uom: str
    lot_uom: str
    factor: Decimal
    material_code: str = ""
    confirmed_by: str = ""
    confirmed_at: str = ""
    note: str = ""

    def key(self) -> tuple:
        return (
            (self.bom_uom, self.lot_uom, self.material_code)
            if self.material_code
            else (self.bom_uom, self.lot_uom)
        )

    def to_json(self) -> dict:
        return {
            "bom_uom": self.bom_uom,
            "lot_uom": self.lot_uom,
            "material_code": self.material_code,
            "factor": str(self.factor),
            "confirmed_by": self.confirmed_by,
            "confirmed_at": self.confirmed_at,
            "note": self.note,
        }

    @classmethod
    def from_json(cls, payload: dict) -> "UomFactorRow":
        return cls(
            bom_uom=canonical_uom(payload.get("bom_uom", "")),
            lot_uom=canonical_uom(payload.get("lot_uom", "")),
            factor=_decimal(payload.get("factor")) or Decimal("1"),
            material_code=str(payload.get("material_code") or "").strip(),
            confirmed_by=str(payload.get("confirmed_by") or ""),
            confirmed_at=str(payload.get("confirmed_at") or ""),
            note=str(payload.get("note") or ""),
        )


def _decimal(value) -> Decimal | None:
    try:
        return Decimal(str(value).strip())
    except (InvalidOperation, ValueError, AttributeError):
        return None


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _root() -> Path:
    return Path(os.environ.get("CO_UOM_FACTOR_ROOT", "config/uom-factors"))


def _json_path(client_id: str) -> Path:
    return _root() / f"{client_id}.json"


def _json_read(client_id: str) -> list[UomFactorRow]:
    path = _json_path(client_id)
    if not path.exists():
        return []
    payload = json.loads(path.read_text(encoding="utf-8"))
    return [UomFactorRow.from_json(row) for row in payload.get("rows") or []]


def _json_write(client_id: str, rows: list[UomFactorRow]) -> None:
    path = _json_path(client_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"client_id": client_id, "rows": [row.to_json() for row in rows]}
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
        temp_name = handle.name
    os.replace(temp_name, path)


_SELECT = "bom_uom, lot_uom, material_code, factor, confirmed_by, confirmed_at, note"


def _db_available() -> bool:
    return bool(database_url())


def _db_list(client_id: str) -> list[UomFactorRow]:
    with connect() as conn, conn.cursor() as cur:
        cur.execute(f"select {_SELECT} from co_uom_factor where client_id = %s", (client_id,))
        return [
            UomFactorRow(
                bom_uom=record[0] or "",
                lot_uom=record[1] or "",
                material_code=record[2] or "",
                factor=_decimal(record[3]) or Decimal("1"),
                confirmed_by=record[4] or "",
                confirmed_at=record[5].isoformat() if record[5] else "",
                note=record[6] or "",
            )
            for record in cur.fetchall()
        ]


def _db_upsert(client_id: str, row: UomFactorRow) -> None:
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            """
            insert into co_uom_factor (client_id, bom_uom, lot_uom, material_code, factor,
                                       confirmed_by, confirmed_at, note)
            values (%s, %s, %s, %s, %s, %s, now(), %s)
            on conflict (client_id, bom_uom, lot_uom, material_code) do update set
                factor = excluded.factor,
                confirmed_by = excluded.confirmed_by,
                confirmed_at = now(),
                note = excluded.note
            """,
            (client_id, row.bom_uom, row.lot_uom, row.material_code, row.factor,
             row.confirmed_by, row.note),
        )


def _db_delete(client_id: str, bom_uom: str, lot_uom: str, material_code: str) -> None:
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            """delete from co_uom_factor
               where client_id = %s and bom_uom = %s and lot_uom = %s and material_code = %s""",
            (client_id, bom_uom, lot_uom, material_code),
        )


def list_factors(client_id: str) -> list[UomFactorRow]:
    if _db_available():
        try:
            return _db_list(client_id)
        except DatabaseUnavailable:
            pass
    return _json_read(client_id)


def factor_map(client_id: str) -> dict[tuple, Decimal]:
    """Shape `resolve_uom_factor(confirmed=...)` consumes."""
    return {row.key(): row.factor for row in list_factors(client_id)}


def set_factor(
    client_id: str,
    *,
    bom_uom: str,
    lot_uom: str,
    factor: Decimal | str,
    confirmed_by: str = "",
    material_code: str = "",
    note: str = "",
) -> UomFactorRow:
    value = _decimal(factor)
    if value is None or value <= 0:
        raise ValueError("Hệ số quy đổi phải là số lớn hơn 0.")
    row = UomFactorRow(
        bom_uom=canonical_uom(bom_uom),
        lot_uom=canonical_uom(lot_uom),
        factor=value,
        material_code=str(material_code or "").strip(),
        confirmed_by=str(confirmed_by or ""),
        confirmed_at=_now(),
        note=str(note or ""),
    )
    if not row.bom_uom or not row.lot_uom:
        raise ValueError("Thiếu đơn vị tính để lưu hệ số quy đổi.")
    if _db_available():
        try:
            _db_upsert(client_id, row)
        except DatabaseUnavailable:
            pass
    rows = [
        existing for existing in _json_read(client_id)
        if (existing.bom_uom, existing.lot_uom, existing.material_code)
        != (row.bom_uom, row.lot_uom, row.material_code)
    ]
    rows.append(row)
    _json_write(client_id, rows)
    return row


def delete_factor(client_id: str, *, bom_uom: str, lot_uom: str, material_code: str = "") -> None:
    bom_uom = canonical_uom(bom_uom)
    lot_uom = canonical_uom(lot_uom)
    material_code = str(material_code or "").strip()
    if _db_available():
        try:
            _db_delete(client_id, bom_uom, lot_uom, material_code)
        except DatabaseUnavailable:
            pass
    rows = [
        row for row in _json_read(client_id)
        if (row.bom_uom, row.lot_uom, row.material_code) != (bom_uom, lot_uom, material_code)
    ]
    _json_write(client_id, rows)
