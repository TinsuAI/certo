"""FAITHFUL, testable batch "sheet tổng hợp" CO case — seeds ONLY the CO dev DB.

Seeds a real growatt-vn case `e2e-batch-real` with 5 products SP-1..SP-5, all
linked to the Data Hub BOM product **INV-5000** (artifact `ba_WAa-MyJ66EVCSBlL`,
7 NVL). The BOM itself lives in Data Hub and renders only when a LOGGED-IN user
opens the case (the app pulls it with the session token — a script has none).

What the script DOES control is CO's own stock: it seeds `co_stock_rows`
(schema `co`, client growatt-vn) so that one material — **AL-100** (0.5 kg/unit)
— is short in exactly 2 of the 5 sheets, while the other 6 NVL are fully covered.

  Export qty 400/SP → AL-100 need 0.5*400 = 200 kg/SP, 5 SP = 1000 kg.
  Seeded AL-100 stock = 600 kg → SP-1..3 covered (600), SP-4 & SP-5 short 200 each.

Verification needs NO login session: an inline-material copy of the case (each SP
carries INV-5000's 7 NVL + `material_overrides {"0":{"norm_edit_only":true}}` to
force the recompute path) is run through `allocate_whole_case_preview` +
`case_shortfall_rollup` against the seeded stock.

Run (DB-mode — source the dev env first):
    set -a; . ./.env.dev; set +a
    PYTHONPATH=$(pwd) uv run python .ai/scripts/e2e_batch_real_seed.py
    # ...open http://127.0.0.1:8001/clients/growatt-vn/co-case/e2e-batch-real/origin ...
    PYTHONPATH=$(pwd) uv run python .ai/scripts/e2e_batch_real_seed.py --cleanup

Writes ONLY to co_dev. Never touches data_hub_dev / the Data Hub BOM.
"""
from __future__ import annotations

import sys

import app.main as m
from app import co_case_store, co_stock_materializer
from app.database import connect
from app.co_stock_materializer import _upsert_records
from app.source_index_records import build_co_stock_index_records

CLIENT = "growatt-vn"
CASE = "e2e-batch-real"
CASE_CODE = "E2E-BATCH-REAL"
BOM_PRODUCT = "INV-5000"
BOM_ARTIFACT = "ba_WAa-MyJ66EVCSBlL"
MARKER = "e2e-batch-real"          # transaction_key prefix — scopes stock cleanup
N = 5                              # SP-1..SP-5
QTY_PER_SP = 400                   # export units per SP

# INV-5000's 7 NVL (real Data Hub BOM). `stock` = seeded co_stock_rows qty.
# AL-100 is deliberately under-stocked so it goes short in 2/5 sheets; the other
# six carry stock >> their total need (need = qty_per * 400 * 5).
MATERIALS = [
    # code,        name,                         uom,  qty_per, hs,         unit_value_vnd, stock
    ("PE-001", "Polyethylene resin grade A", "kg",  "0.600", "39011010", "45000",  "5000"),
    ("PE-002", "Polyethylene resin grade B", "kg",  "0.200", "39011010", "42000",  "5000"),
    ("AL-100", "Aluminum sheet 1mm",         "kg",  "0.500", "76061110", "60000",  "600"),
    ("CU-WIRE-2", "Copper wire 2.5mm",       "m",   "1.200", "85447000", "18000",  "10000"),
    ("PCB-12", "PCB 12-layer",               "pcs", "1.000", "85340010", "250000", "10000"),
    ("HEATSINK-A", "Heatsink type A",        "pcs", "1.000", "76161000", "80000",  "10000"),
    ("CASE-INV", "Inverter casing",          "pcs", "1.000", "39269097", "120000", "10000"),
]

SP_CODES = [f"SP-{i}" for i in range(1, N + 1)]


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
# stock: co_stock_rows_from_bcct-shaped payloads (schema co)
# --------------------------------------------------------------------------- #
def _stock_payload(mat) -> dict:
    code, name, uom, _qty_per, hs, unit_value, stock = mat
    source_row = f"{MARKER}-{code}"
    from decimal import Decimal

    customs_value = str((Decimal(unit_value) * Decimal(stock)).quantize(Decimal("1")))
    return {
        "source_row": source_row,
        "source_transaction_key": f"{MARKER}-{code}-1",   # DB transaction_key (cleanup marker)
        "source_line_ids": [source_row],
        "import_declaration_no": f"90{MATERIALS.index(mat) + 100}/NK/A11",  # distinct per lot
        "registration_date": "2025-06-01",
        "line_no": str(MATERIALS.index(mat) + 1),          # distinct per lot
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
    rows = [_stock_payload(mat) for mat in MATERIALS]
    records = build_co_stock_index_records(CLIENT, rows)
    with connect() as conn, conn.cursor() as cur:
        _upsert_records(cur, records)
    co_stock_materializer.invalidate_co_stock_rows_cache(CLIENT)


# --------------------------------------------------------------------------- #
# case records
# --------------------------------------------------------------------------- #
def _faithful_products() -> list[dict]:
    """Products with NO inline materials — the 7 NVL load from Data Hub when a
    logged-in user opens the case. Each SP links to INV-5000's BOM."""
    products = []
    for i, code in enumerate(SP_CODES, start=1):
        products.append({
            "code": code,
            "product_code": code,
            "bom_product_code": BOM_PRODUCT,
            "bom_product_artifact_id": BOM_ARTIFACT,
            "bom_product_artifact_no": "1",
            "bom_product_version_id": BOM_ARTIFACT,
            "bom_product_version_no": "1",
            "allocation_sequence": str(i),
            "name": f"Bộ biến tần INV-5000 lô {i}",
            "finished_hs": "850440",
            "quantity": str(QTY_PER_SP),
            "unit": "pcs",
            "fob": "100000",
            "currency": "USD",
        })
    return products


def _inline_materials() -> list[dict]:
    out = []
    for seq, (code, name, uom, qty_per, hs, _uv, _st) in enumerate(MATERIALS, start=1):
        out.append({
            "material_code": code,
            "material_sequence": str(seq),
            "material_description": name,
            "uom": uom,
            "bom_qty_per": qty_per,
            "hs_code": hs,
        })
    return out


def _base_case(products, sheet_states) -> dict:
    now = co_case_store.now_iso()
    return {
        "id": CASE, "persisted_case_id": CASE, "case_id": CASE,
        "case_code": CASE_CODE, "title": "E2E batch REAL (INV-5000) — sheet tổng hợp",
        "customer": "Growatt E2E", "destination_market": "Ấn Độ", "status": "open",
        "created_at": now, "updated_at": now,
        "shipment": {"invoice_no": "E2E-BATCH-REAL", "export_declaration_nos": []},
        "source_invoice_matches": [],
        "origin_product_order": list(SP_CODES),
        "products": products,
        "origin_sheet_states": sheet_states,
    }


def _persist_faithful() -> None:
    from app.workflow_state_store import get_co_case_state_store
    store = get_co_case_state_store()
    assert store is not None, "expected DB-mode — source .env.dev"
    sheet_states = {code: {"status": "draft", "status_label": "Chưa tính"} for code in SP_CODES}
    case = _base_case(_faithful_products(), sheet_states)
    store.save_case_record(CLIENT, case, 0)


def _inline_case() -> dict:
    """In-memory verification copy: each SP carries INV-5000's 7 NVL + a
    norm_edit_only override so the recompute path allocates against seeded stock."""
    products = []
    for i, code in enumerate(SP_CODES, start=1):
        p = {
            "code": code, "product_code": code,
            "bom_product_code": BOM_PRODUCT, "bom_product_artifact_id": BOM_ARTIFACT,
            "allocation_sequence": str(i),
            "name": f"Bộ biến tần INV-5000 lô {i}",
            "finished_hs": "850440", "quantity": str(QTY_PER_SP), "unit": "pcs",
            "fob": "100000", "currency": "USD",
            "materials": _inline_materials(),
        }
        products.append(p)
    sheet_states = {
        code: {"status": "calculated", "status_label": "calculated",
               "material_overrides": {"0": {"norm_edit_only": True}}}
        for code in SP_CODES
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
    print(f"case={CASE} client={CLIENT} products={','.join(SP_CODES)} (all BOM {BOM_PRODUCT})", flush=True)
    print(f"stock rows seeded: {len(MATERIALS)} (AL-100=600kg constrained; other 6 generous)", flush=True)
    print("==== SHORTFALL ROLLUP (verified against seeded co_stock_rows, no session) ====", flush=True)
    print("material_count:", rollup.get("material_count"), flush=True)
    for mm in rollup.get("materials", []):
        print(
            f"  {mm['material_code']}: cần {mm['needed']} · tồn {mm['available']} · thiếu {mm['short_qty']} {mm['uom']}"
            f" · thiếu {mm['short_count']}/{mm['using_count']} SP · shortIn={mm['short_products']}",
            flush=True,
        )

    ok = (
        rollup.get("material_count") == 1
        and rollup["materials"][0]["material_code"] == "AL-100"
        and rollup["materials"][0]["needed"] == "1000"
        and rollup["materials"][0]["available"] == "600"
        and rollup["materials"][0]["short_qty"] == "400"
        and rollup["materials"][0]["short_count"] == 2
        and rollup["materials"][0]["short_products"] == ["SP-4", "SP-5"]
    )
    print("VERIFY_PASS" if ok else "VERIFY_FAIL", flush=True)
    print(f"URL: http://127.0.0.1:8001/clients/{CLIENT}/co-case/{CASE}/origin", flush=True)
    print("NOTE: the 7 NVL render only once a LOGGED-IN user opens the case (BOM comes from Data Hub via the session token).", flush=True)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
