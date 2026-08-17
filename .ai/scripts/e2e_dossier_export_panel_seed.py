"""Seed a CLOSED case whose dossier export is mid-flight, so the review page
renders the "Đang tạo hồ sơ .zip…" panel and the browser e2e can check that the
progress poll survives an in-app tab switch (VNG26030107, 2026-08-17).

  set -a; . ./.env; set +a
  PYTHONPATH=$(pwd) uv run python .ai/scripts/e2e_dossier_export_panel_seed.py            # seed
  PYTHONPATH=$(pwd) uv run python .ai/scripts/e2e_dossier_export_panel_seed.py --cleanup  # remove

The running entry has no live Future in the server process, so the status view
reports it orphaned once `ORPHAN_GRACE_SECONDS` passes — run the browser check
right after seeding (the seed stamps `started_at` at "now").
"""
import copy
import sys

from app.co_case_store import load_state, now_iso, save_state
from app.database import connect
from app.routers.co_case import persisted_origin_case
from app.co_case_store import json_safe
from app.web.client_context import resolve_client
from app.workflow_state_store import get_co_case_state_store

CID = "johnson-vn"
SRC = "co-case-e0b390ead3b0"
CLONE = "e2e-export-panel"


def _cleanup():
    with connect() as c, c.cursor() as cur:
        cur.execute("delete from co_stock_claims where case_id=%s", (CLONE,))
        cur.execute("delete from co_cases where case_id=%s", (CLONE,))
    state = load_state(CID)
    (state.get("dossier_exports") or {}).pop(CLONE, None)
    save_state(CID, state)
    print("CLEANED", CLONE, flush=True)


if "--cleanup" in sys.argv:
    _cleanup()
    sys.exit(0)

_cleanup()  # a re-seed must start from no row (save_case_record expects revision 0)

client = resolve_client(CID)
case = copy.deepcopy(persisted_origin_case(client, SRC))
case["id"] = case["persisted_case_id"] = case["case_id"] = CLONE
case["case_code"] = "E2E-EXPORT-PANEL"
case["title"] = "Export panel E2E DELETE ME"
case["status"] = "completed"
case.setdefault("created_at", now_iso())
case["updated_at"] = now_iso()
for product in case.get("products", []):
    product["origin_sheet_status"] = "locked"
states = case.get("origin_sheet_states") or {}
for code, state in states.items():
    if isinstance(state, dict):
        state["status"] = "locked"
case["origin_sheet_states"] = states

store = get_co_case_state_store()
store.save_case_record(CID, json_safe(case), expected_revision=0)

state = load_state(CID)
state.setdefault("dossier_exports", {})[CLONE] = {
    "status": "running",
    "built_from_revision": "e2e-revision",
    "filename": "E2E-EXPORT-PANEL-dossier.zip",
    "started_at": now_iso(),
    "warnings": [],
}
save_state(CID, state)
print(f"SEEDED {CLONE} status=completed export=running", flush=True)
print(f"URL /clients/{CID}/co-case/{CLONE}/review", flush=True)
