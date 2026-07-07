"""FAITHFUL, testable batch "sheet tổng hợp" CO case — seeds ONLY the CO dev DB.

Seeds a real growatt-vn case `e2e-batch-real` with **3 products whose `code` IS a
real Data Hub product code**: INV-5000, INV-10K, INV-3000 (each has a published DH
BOM). This matters: the app resolves a sheet's BOM by the product's **`code`**
(`co_case_bom_product_codes` → the invoice-match / product code), NOT by any
`bom_product_code` field. So the persisted products carry **no inline `materials`
and no `bom_product_code`/`bom_product_artifact_id`** — the latest BOM loads from
Data Hub by `code` when a LOGGED-IN user opens the case (the app pulls it with the
session token; a script has none).

The 3 BOMs SHARE {PE-001, AL-100, PCB-12, HEATSINK-A, CASE-INV}; PE-002 (only
INV-5000) and CU-WIRE-2 (INV-5000+INV-10K) are extra. AL-100 qty/unit differs per
product: INV-5000=0.5, INV-10K=0.9, INV-3000=0.3 kg.

What the script DOES control is CO's own stock: it seeds `co_stock_rows` (schema
`co`, client growatt-vn) so that ONE material — **AL-100** — is short. Export qty
1000/product, sequential allocation in product order [INV-5000, INV-10K, INV-3000]:

  AL-100 need = 0.5*1000 + 0.9*1000 + 0.3*1000 = 500 + 900 + 300 = 1700 kg.
  Seeded AL-100 stock = 1000 kg → INV-5000 covered (500, 500 left);
  INV-10K needs 900, 500 left → SHORT 400 (0 left); INV-3000 needs 300, 0 left →
  SHORT 300. ⇒ AL-100 short in 2/3 products (INV-10K, INV-3000).

The other 6 NVL are stocked generously (100000) so only AL-100 goes short.

Verification needs NO login session: an inline-material copy of the case is built
by READING the REAL BOM rows from data_hub_dev (hub.bom_artifacts join
hub.bom_artifact_rows, artifact_no=1) for each product, plus a
`material_overrides {"0":{"norm_edit_only":true}}` on every sheet to force the
recompute path. That copy is run through `allocate_whole_case_preview` +
`case_shortfall_rollup` against the seeded co_stock_rows. data_hub_dev is opened
READ-ONLY (SELECT only) for this — the seed never writes to it.

Run (DB-mode — source the dev env first):
    set -a; . ./.env.dev; set +a
    PYTHONPATH=$(pwd) uv run python .ai/scripts/e2e_batch_real_seed.py
    # ...open http://127.0.0.1:8001/clients/growatt-vn/co-case/e2e-batch-real/origin ...
    PYTHONPATH=$(pwd) uv run python .ai/scripts/e2e_batch_real_seed.py --cleanup

Writes ONLY to co_dev. Never writes to data_hub_dev / the Data Hub BOM.
"""
from __future__ import annotations

import os
import sys
from decimal import Decimal

import app.main as m
from app import co_case_store, co_stock_materializer
from app.database import connect
from app.co_stock_materializer import _upsert_records
from app.source_index_records import build_co_stock_index_records

CLIENT = "growatt-vn"
CASE = "e2e-batch-real"
CASE_CODE = "E2E-BATCH-REAL"
MARKER = "e2e-batch-real"          # transaction_key prefix — scopes stock cleanup
QTY = 1000                         # export units per product

# Products — `code` IS the real Data Hub product code (BOM resolves by code).
# order drives sequential cross-product stock allocation.
PRODUCTS = [
    # code,       friendly name,                       fob
    ("INV-5000", "Bộ biến tần INV-5000 5kW",           "100000"),
    ("INV-10K",  "Bộ biến tần INV-10K 10kW",           "180000"),
    ("INV-3000", "Bộ biến tần INV-3000 3kW",           "70000"),
]
PRODUCT_ORDER = [code for code, _n, _f in PRODUCTS]

# read-only Data Hub dev DB (SELECT only — never written by this seed)
DATA_HUB_DB_URL = os.environ.get(
    "DATA_HUB_DATABASE_URL",
    "postgresql://vdev:813b05c51be11a6be55a333a50db6029@127.0.0.1:5433/data_hub_dev",
)

# Stock metadata for every material in the union of the 3 BOMs. `stock` is the
# seeded co_stock_rows qty: AL-100 constrained to 1000 (short), the rest generous.
GENEROUS = "100000"
MATERIAL_META = {
    # code:        (friendly name,                  uom,   hs_code,    unit_value_vnd, stock)
    "PE-001":    ("Polyethylene resin grade A", "kg",  "39011010", "45000",  GENEROUS),
    "PE-002":    ("Polyethylene resin grade B", "kg",  "39011010", "42000",  GENEROUS),
    "AL-100":    ("Aluminum sheet 1mm",         "kg",  "76061110", "60000",  "1000"),
    "CU-WIRE-2": ("Copper wire 2.5mm",          "m",   "85447000", "18000",  GENEROUS),
    "PCB-12":    ("PCB 12-layer",               "pcs", "85340010", "250000", GENEROUS),
    "HEATSINK-A":("Heatsink type A",            "pcs", "76161000", "80000",  GENEROUS),
    "CASE-INV":  ("Inverter casing",            "pcs", "39269097", "120000", GENEROUS),
}
STOCK_CODES = list(MATERIAL_META.keys())


# --------------------------------------------------------------------------- #
# real BOM rows — READ-ONLY from data_hub_dev (verification proxy only)
# --------------------------------------------------------------------------- #
def _read_dh_bom_rows(product_code: str) -> list[dict]:
    """SELECT the published artifact_no=1 BOM rows for a product from data_hub_dev.
    Read-only: opens its own connection, issues SELECTs, never writes."""
    import psycopg

    with psycopg.connect(DATA_HUB_DB_URL) as conn, conn.cursor() as cur:
        cur.execute(
            """
            select r.material_code, r.qty_per_unit, r.uom
            from hub.bom_artifacts a
            join hub.bom_artifact_rows r on r.artifact_id = a.artifact_id
            where a.product_code = %s and a.artifact_no = 1 and r.excluded_at is null
            order by r.row_index
            """,
            (product_code,),
        )
        rows = cur.fetchall()
    out = []
    for seq, (code, qty_per, uom) in enumerate(rows, start=1):
        code = str(code).strip()
        meta = MATERIAL_META.get(code, (code, uom, "", "", GENEROUS))
        out.append({
            "material_code": code,
            "material_sequence": str(seq),
            "material_description": meta[0],
            "uom": str(uom or meta[1]),
            "bom_qty_per": format(Decimal(str(qty_per)).normalize(), "f"),
            "hs_code": meta[2] if len(meta) > 2 else "",
        })
    return out


# --------------------------------------------------------------------------- #
# cleanup
# --------------------------------------------------------------------------- #
def _cleanup() -> None:
    with connect() as c, c.cursor() as cur:
        cur.execute("delete from co_stock_claims where case_id=%s", (CASE,))
        cur.execute("delete from co_cases where case_id=%s", (CASE,))
        cur.execute(
            "delete from co_stock_rows where client_id=%s and transaction_key like %s",
            (CLIENT, MARKER + "%"),
        )
    co_stock_materializer.invalidate_co_stock_rows_cache(CLIENT)


# --------------------------------------------------------------------------- #
# stock: co_stock_rows-shaped payloads (schema co)
# --------------------------------------------------------------------------- #
def _stock_payload(code: str) -> dict:
    name, uom, hs, unit_value, stock = MATERIAL_META[code]
    idx = STOCK_CODES.index(code)
    source_row = f"{MARKER}-{code}"
    customs_value = str((Decimal(unit_value) * Decimal(stock)).quantize(Decimal("1")))
    return {
        "source_row": source_row,
        "source_transaction_key": f"{MARKER}-{code}-1",   # DB transaction_key (cleanup marker)
        "source_line_ids": [source_row],
        "import_declaration_no": f"90{idx + 100}/NK/A11",  # distinct per lot
        "registration_date": "2025-06-01",
        "line_no": str(idx + 1),                           # distinct per lot
        "declaration_type": "A11",
        # match keys — all three equal `code` so the allocator finds the lot by material_code
        "customs_item_code": code,
        "allocation_code": code,
        "material_code": code,
        "allocation_code_source": "seed",
        "allocation_code_status": "resolved",              # required for eligibility
        "allocation_code_confidence": "high",
        "allocation_code_reason": "e2e_batch_real_seed",
        "eligibility_status": "eligible",                  # in ALLOWED_ELIGIBILITY_VALUES
        "eligibility_reason": "e2e_batch_real_seed",
        "material_description": name,
        "hs_code": hs,
        "unit": uom,
        "origin_country": "China",
        "available_qty": stock,                            # apply_used_qty → remaining = this
        "used_qty": "0",
        "remaining_qty": stock,
        "customs_value": customs_value,
        "taxable_unit_price": unit_value,
        "unit_value": unit_value,
        "unit_value_source": "bcct_taxable_unit_price",
        "currency": "VND",
        "value_currency": "VND",
        "exchange_rate_to_vnd": "1",
        "exchange_rate_source": "vnd_native",
    }


def _seed_stock() -> None:
    rows = [_stock_payload(code) for code in STOCK_CODES]
    records = build_co_stock_index_records(CLIENT, rows)
    with connect() as conn, conn.cursor() as cur:
        _upsert_records(cur, records)
    co_stock_materializer.invalidate_co_stock_rows_cache(CLIENT)


# --------------------------------------------------------------------------- #
# case records
# --------------------------------------------------------------------------- #
def _faithful_products() -> list[dict]:
    """Products with NO inline materials and NO bom_product_code/artifact — the app
    resolves the LATEST DH BOM by the product's `code` when a logged-in user opens
    the case. `code` IS the real Data Hub product code."""
    products = []
    for i, (code, name, fob) in enumerate(PRODUCTS, start=1):
        products.append({
            "code": code,
            "product_code": code,
            "allocation_sequence": str(i),
            "name": name,
            "finished_hs": "850440",
            "quantity": str(QTY),
            "unit": "pcs",
            "fob": fob,
            "currency": "USD",
        })
    return products


def _base_case(products, sheet_states) -> dict:
    now = co_case_store.now_iso()
    return {
        "id": CASE, "persisted_case_id": CASE, "case_id": CASE,
        "case_code": CASE_CODE, "title": "E2E batch REAL (3 SP) — sheet tổng hợp",
        "customer": "Growatt E2E", "destination_market": "Ấn Độ", "status": "open",
        "created_at": now, "updated_at": now,
        "shipment": {"invoice_no": "E2E-BATCH-REAL", "export_declaration_nos": []},
        "source_invoice_matches": [],
        "origin_product_order": list(PRODUCT_ORDER),
        "products": products,
        "origin_sheet_states": sheet_states,
    }


def _persist_faithful() -> None:
    from app.workflow_state_store import get_co_case_state_store
    store = get_co_case_state_store()
    assert store is not None, "expected DB-mode — source .env.dev"
    sheet_states = {code: {"status": "draft", "status_label": "Chưa tính"} for code in PRODUCT_ORDER}
    case = _base_case(_faithful_products(), sheet_states)
    store.save_case_record(CLIENT, case, 0)


def _inline_case() -> dict:
    """In-memory verification copy: each product carries its REAL DH BOM rows (read
    from data_hub_dev) + a norm_edit_only override so the recompute path allocates
    against the seeded co_stock_rows in product order."""
    products = []
    for i, (code, name, fob) in enumerate(PRODUCTS, start=1):
        products.append({
            "code": code, "product_code": code,
            "allocation_sequence": str(i),
            "name": name, "finished_hs": "850440",
            "quantity": str(QTY), "unit": "pcs",
            "fob": fob, "currency": "USD",
            "materials": _read_dh_bom_rows(code),
        })
    sheet_states = {
        code: {"status": "calculated", "status_label": "calculated",
               "material_overrides": {"0": {"norm_edit_only": True}}}
        for code in PRODUCT_ORDER
    }
    return _base_case(products, sheet_states)


# --------------------------------------------------------------------------- #
# verify (no session) — allocate the inline case against seeded stock
# --------------------------------------------------------------------------- #
def _verify_rollup():
    from app.web.client_context import resolve_client
    from app.routers.co_case import allocate_whole_case_preview, _origin_min_gap_days
    from app.web.co_case_context import case_shortfall_rollup, minimal_bom_workspace

    client = resolve_client(CLIENT)
    context = {
        "origin_source_context": {"invoice_matches": [], "material_rows": []},
        "bom_workspace": minimal_bom_workspace(),
        "recommended_form_lane": {},
    }
    alloc = allocate_whole_case_preview(
        client, _inline_case(), context, [], _origin_min_gap_days(client)
    )
    return case_shortfall_rollup(alloc)


# --------------------------------------------------------------------------- #
# main
# --------------------------------------------------------------------------- #
def main() -> int:
    if "--cleanup" in sys.argv:
        _cleanup()
        print("CLEANED", CASE, "+ stock marker", MARKER, flush=True)
        return 0

    m.require_local_source_writes = lambda: None

    _cleanup()          # idempotent: cleanup then seed
    _seed_stock()
    _persist_faithful()

    rollup = _verify_rollup()

    print("==== SEEDED ====", flush=True)
    print(f"case={CASE} client={CLIENT} products={','.join(PRODUCT_ORDER)}"
          f" (code == real DH BOM product code)", flush=True)
    print(f"stock rows seeded: {len(STOCK_CODES)} (AL-100=1000kg constrained; other 6 generous={GENEROUS})", flush=True)
    print("==== SHORTFALL ROLLUP (verified vs seeded co_stock_rows, real DH BOM rows, no session) ====", flush=True)
    print("material_count:", rollup.get("material_count"), flush=True)
    for mm in rollup.get("materials", []):
        print(
            f"  {mm['material_code']}: cần {mm['needed']} · tồn {mm['available']} · thiếu {mm['short_qty']} {mm['uom']}"
            f" · thiếu {mm['short_count']}/{mm['using_count']} SP · shortIn={mm['short_products']}",
            flush=True,
        )

    only = rollup["materials"][0] if rollup.get("materials") else {}
    ok = (
        rollup.get("material_count") == 1
        and only.get("material_code") == "AL-100"
        and only.get("needed") == "1700"
        and only.get("available") == "1000"
        and only.get("short_qty") == "700"
        and only.get("short_count") == 2
        and only.get("short_products") == ["INV-10K", "INV-3000"]
    )
    print("VERIFY_PASS" if ok else "VERIFY_FAIL", flush=True)
    print(f"URL: http://127.0.0.1:8001/clients/{CLIENT}/co-case/{CASE}/origin", flush=True)
    print("NOTE: each BOM renders only once a LOGGED-IN user opens the case (the app"
          " resolves the latest DH BOM by product code via the session token).", flush=True)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
