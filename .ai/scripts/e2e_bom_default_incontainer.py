"""In-container e2e for Slice A (#14) — per-client default BOM pick, DB-mode.

WHY in-container: validates the DEPLOYED image's DB-mode store path
(co_bom_product_default) + read-time precedence, which the file-mode JSON unit
tests don't cover. Fully isolated on a throwaway client_id (touches no real
client/BOM data); self-cleaning.

WHAT: (1) route helper persist_bom_picks_as_defaults writes a pick through to
co_bom_product_default; (2) the diff-guard skips a stale echo of an old case so
it can't clobber a newer default; (3) selected_bom_rows_by_product auto-reads
the client default from the DB and picks it OVER the aggregate composition
default (the auto-reuse promise).

HOW (nightly only — never seed prod):
    cat .ai/scripts/e2e_bom_default_incontainer.py | \
      ssh tinsu 'docker exec -i -e BOM_DEFAULT_CONFIG_ROOT=/tmp/e2e-bomdef \
                 nightly-co-app-1 python -'
  Expect tail: CLEANUP_OK then E2E_PASS.
  -e BOM_DEFAULT_CONFIG_ROOT redirects the JSON mirror off the real config dir
  (DB stays authoritative).
"""
import sys

from app import bom_default_store
from app.routers.co_case import persist_bom_picks_as_defaults
from app.web.co_case_context import selected_bom_rows_by_product
from app.database import connect, database_url

CLIENT = "__e2e_slicea"


def B(m):
    print("==== " + str(m) + " ====", flush=True)


def _cleanup():
    with connect() as c, c.cursor() as cur:
        cur.execute("delete from co_bom_product_default where client_id = %s", (CLIENT,))


assert database_url(), "expected DB-mode (BARRY_DATABASE_URL must be set)"
_cleanup()
ok = False
try:
    # 1) write-through via the actual route helper → co_bom_product_default
    persist_bom_picks_as_defaults(
        {"id": CLIENT},
        {"products": [{"code": "P1", "bom_product_artifact_id": "art-v3"}]},
        prior_overrides={},
    )
    d1 = bom_default_store.get_defaults(CLIENT)
    B(f"after write-through (DB): {d1}")

    # 2) diff-guard: a newer pick exists; re-saving an OLD case (echo art-v3,
    # prior==incoming) must NOT clobber the newer default.
    bom_default_store.set_default(CLIENT, "P1", "art-v5")
    persist_bom_picks_as_defaults(
        {"id": CLIENT},
        {"products": [{"code": "P1", "bom_product_artifact_id": "art-v3"}]},
        prior_overrides={"P1": "art-v3"},
    )
    d2 = bom_default_store.get_default(CLIENT, "P1")
    B(f"after stale-echo (must stay art-v5): {d2}")

    # 3) precedence: a fresh case (no case override) auto-reuses the client
    # default (art-v5 → NVL-NEW) over the aggregate composition default (art-v3).
    rows_old = [{"product_code": "P1", "product_version_id": "art-v3", "material_code": "NVL-OLD", "qty_per": "1"}]
    rows_new = [{"product_code": "P1", "product_version_id": "art-v5", "material_code": "NVL-NEW", "qty_per": "1"}]
    workspace = {
        "latest_version": {"version_id": "agg", "product_versions": [{"product_code": "P1", "product_version_id": "art-v3"}]},
        "versions": [{
            "version_id": "agg",
            "rows": rows_old,
            "product_versions": [{"product_code": "P1", "product_version_id": "art-v3"}],  # composition default = art-v3
        }],
        "latest_rows": [],
        "product_versions": [
            {"product_code": "P1", "product_version_id": "art-v3", "rows": rows_old},
            {"product_code": "P1", "product_version_id": "art-v5", "rows": rows_new},
        ],
        "product_version_options_by_code": {"P1": [
            {"product_code": "P1", "product_version_id": "art-v3", "rows": rows_old},
            {"product_code": "P1", "product_version_id": "art-v5", "rows": rows_new},
        ]},
    }
    case = {"client_id": CLIENT, "products": [{"code": "P1", "bom_product_code": "P1"}]}  # no case override
    mat = selected_bom_rows_by_product(case, workspace)["P1"][0]["material_code"]
    B(f"precedence picked: {mat} (expect NVL-NEW from default art-v5)")

    ok = (d1 == {"P1": "art-v3"} and d2 == "art-v5" and mat == "NVL-NEW")
finally:
    try:
        _cleanup()
    except Exception as e:
        print("cleanup err:", repr(e), flush=True)
    with connect() as c, c.cursor() as cur:
        cur.execute("select count(*) from co_bom_product_default where client_id = %s", (CLIENT,))
        left = cur.fetchone()[0]
    print("CLEANUP_OK" if left == 0 else "CLEANUP_MISMATCH", flush=True)

print("E2E_PASS" if ok else "E2E_FAIL", flush=True)
sys.exit(0 if ok else 1)
