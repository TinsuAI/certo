"""Seed a Johnson clone that still HAS its rác, to exercise the aggregate
"chọn NVL rác → xoá" on real data. The live johnson-vn case has already had its
rác soft-deleted (129 rows); this clones it with all deletions REVERTED so the
no-stock (allocation_count==0) rows resurface in the aggregate.

  set -a; . ./.env; set +a
  PYTHONPATH=$(pwd) uv run python .ai/scripts/e2e_johnson_rac_seed.py            # seed + report
  PYTHONPATH=$(pwd) uv run python .ai/scripts/e2e_johnson_rac_seed.py --cleanup  # remove clone
"""
import copy
import sys

from app.database import connect
from app.web.client_context import resolve_client
from app.routers.co_case import (
    persisted_origin_case, _origin_preview_context, _origin_min_gap_days, allocate_whole_case_preview,
)
from app.web.co_case_context import case_shortfall_rollup
from app.co_case_store import json_safe, now_iso
from app.workflow_state_store import get_co_case_state_store

CID = "johnson-vn"
SRC = "co-case-e0b390ead3b0"
CLONE = "johnson-e2e-rac"


def _cleanup():
    with connect() as c, c.cursor() as cur:
        cur.execute("delete from co_stock_claims where case_id=%s", (CLONE,))
        cur.execute("delete from co_cases where case_id=%s", (CLONE,))
    print("CLEANED", CLONE, flush=True)


if "--cleanup" in sys.argv:
    _cleanup()
    sys.exit(0)

client = resolve_client(CID)
case = copy.deepcopy(persisted_origin_case(client, SRC))
case["id"] = case["persisted_case_id"] = case["case_id"] = CLONE
case["case_code"] = "JOHNSON-E2E-RAC"
case["title"] = "Johnson rác E2E DELETE ME"
case.setdefault("created_at", now_iso())
case["updated_at"] = now_iso()
case.setdefault("status", "open")

# Revert every soft-deletion so the rác rows come back.
for p in case.get("products", []):
    for m in p.get("materials", []) or []:
        if m.get("deleted"):
            m["deleted"] = False
for st in (case.get("origin_sheet_states") or {}).values():
    for v in ((st or {}).get("material_overrides") or {}).values():
        if isinstance(v, dict):
            v.pop("deleted", None)

store = get_co_case_state_store()
assert store is not None, "expected DB-mode — source .env"
_cleanup()
store.save_case_record(CID, json_safe(case), 0)

saved = persisted_origin_case(client, CLONE)
ctx, rows = _origin_preview_context(client, CID, CLONE, saved)
alloc = allocate_whole_case_preview(client, ctx["case"], ctx, rows, _origin_min_gap_days(client))
r = case_shortfall_rollup(alloc)
from collections import Counter
kinds = Counter(f["kind"] for f in r["folded_rac"])
print(f"rollup: material_count(thiếu tồn)={r['material_count']}  folded_rac={r['folded_rac_count']}  kinds={dict(kinds)}", flush=True)
for f in r["folded_rac"][:8]:
    print(f"  RÁC[{f['kind']}] {f['material_code']} · {f['count']} SP {f['products']}", flush=True)
print(f"SEED_OK — http://127.0.0.1:8001/clients/{CID}/co-case/{CLONE}/origin", flush=True)
