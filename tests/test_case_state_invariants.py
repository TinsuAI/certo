"""Invariants of the CO case state, checked ACROSS routes.

Why this file exists. On 2026-08-20 three defects shipped past a full branch
review and 1,168 passing tests, because every one of them lives *between*
routes rather than inside one:

- `/evaluate` (the route the BOM version picker auto-submits) rebuilds every
  product from BOM with `preserve_origin_products=False`, dropping
  `material_overrides` on ALL sheets. A substitution then survives one
  `calculate-all` but not `substitute → evaluate → calculate-all`.
- The same route reports "Đã tính lại theo dữ liệu đang sửa" without
  allocating, and marks no sheet stale.
- `save_client_config_route` reset config sections a partial POST did not
  carry.

At the time, 4 of 119 test files touched two routes and none touched three;
`/evaluate` last changed 2026-06-02, so a branch-scoped review could not see
it. Route-scoped tests and diff-scoped reviews are both blind to this class by
construction. These tests are state-scoped instead: seed a real case, run a
route, and assert the invariants still hold.

Three parts:
1. `INVARIANTS` — the properties, each citing the incident that motivated it.
2. `ROUTES` × invariants — one cell per (route, invariant) pair.
3. A seeded random walk over route sequences nobody would enumerate by hand.

Known-bad cells are marked `xfail(strict=True)`, not fixed: strict xfail turns
the marker into a failure the day someone fixes the route, so the matrix cannot
drift out of date silently.

WHAT THIS FOUND, first real run (2026-08-20): `load-bom` on one sheet persists a
case containing ONLY that sheet. The others vanish from `products` while
`origin_product_order` still lists them, and the origin page renders a single
tab. Confirmed independently against the running app on demo-furniture. Any
whole-case operation rebuilds them, which is exactly why it survived this long.

KNOWN GAPS — this file is a diagnostic tool, not yet a gate:

1. `/evaluate` does NOT drop overrides here, though the same sequence took the
   count 1 → 0 against the running app. The submit is faithful (402 fields,
   `persisted_case_id` present, HTTP 200), so the difference is in the world, not
   the request. Until that is explained the harness cannot be trusted to catch
   the defect it was written for.
2. The world is not isolated between runs: conftest isolates the DB schema in
   DB-mode only, and file-mode source data persists in `data/`. Re-running may
   accumulate uploads.
"""
from __future__ import annotations

import hashlib
import html
import random
import re
from dataclasses import dataclass, field
from io import BytesIO
from typing import Callable

import pytest
from fastapi.testclient import TestClient
from openpyxl import Workbook, load_workbook

from app.main import app

CLIENT = "growatt"
XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
INVOICE = "INV-INVARIANT"
_BCCT_COLUMNS = [
    "coverage_period", "direction", "declaration_no", "declaration_date", "customs_office",
    "declaration_type", "line_no", "item_code", "description", "hs_code", "quantity", "unit",
    "customs_value", "currency", "invoice_ref", "xuat_xu", "ten_doi_tac",
]


# --------------------------------------------------------------------------- #
# The world: real source data, real routes, no fakes                          #
# --------------------------------------------------------------------------- #
def _bcct_workbook(rows: list[dict]) -> bytes:
    workbook = Workbook()
    worksheet = workbook.active
    worksheet.title = "BCCT"
    worksheet.append(_BCCT_COLUMNS)
    for row in rows:
        worksheet.append([row.get(key, "") for key in _BCCT_COLUMNS])
    stream = BytesIO()
    workbook.save(stream)
    return stream.getvalue()


def _import_row(code: str, declaration_no: str, quantity: str = "1000") -> dict:
    return {
        "direction": "import", "declaration_type": "E11", "declaration_no": declaration_no,
        "line_no": "1", "item_code": code, "description": code, "hs_code": "8542.39",
        "quantity": quantity, "unit": "PCE", "customs_value": "5000", "currency": "VND",
    }


def _export_row(code: str, line_no: str, quantity: str) -> dict:
    return {
        "direction": "export", "declaration_type": "E42", "declaration_no": "XK-INVARIANT",
        "line_no": line_no, "item_code": code, "description": code, "hs_code": "850440",
        "quantity": quantity, "unit": "PCS", "customs_value": "1000", "currency": "VND",
        "invoice_ref": INVOICE,
    }


_SEEDED = False


@pytest.fixture
def world() -> TestClient:
    """A seeded client. The upload pair costs ~40s, so it runs once per module
    behind `_SEEDED` rather than once per test.

    The fixture is function-scoped on purpose: conftest's autouse
    `isolate_data_hub_runtime_config` is function-scoped, and it is what sets
    `CO_ALLOW_LOCAL_SOURCE`. A module-scoped fixture runs outside it and every
    source read 404s.

    The BOM template round-trips through `/bom/upload` (it ships pre-filled), and
    the BCCT carries import stock for every material in it plus two export lines
    so the case has two sheets: the minimum for any downstream-cascade invariant.
    """
    global _SEEDED
    client = TestClient(app)
    if _SEEDED:
        return client
    template = client.get(f"/clients/{CLIENT}/bom/template.xlsx")
    assert template.status_code == 200, template.text[:200]
    uploaded = client.post(
        f"/clients/{CLIENT}/bom/upload",
        data={"upload_mode": "direct_bom"},
        files={"file": ("bom.xlsx", template.content, XLSX)},
    )
    assert uploaded.status_code == 200, uploaded.text[:200]
    rows = [_import_row(f"DEMO-NPL-00{n}", f"NK-INVARIANT-{n}") for n in (1, 2, 3, 4)]
    rows += [_export_row("PV00.0048500", "1", "3"), _export_row("PV01.0117600", "2", "2")]
    ingested = client.post(
        f"/clients/{CLIENT}/bcct/upload",
        files={"file": ("bcct.xlsx", _bcct_workbook(rows), XLSX)},
    )
    assert ingested.status_code == 200, ingested.text[:200]
    _SEEDED = True
    return client


def _origin(case_id: str) -> str:
    return f"/clients/{CLIENT}/co-case/{case_id}/origin"


_TEMPLATE_CASE_ID = ""


def make_case(client: TestClient, case_code: str) -> str:
    """An independent case with two sheets, BOM loaded and calculated — the
    resting state an operator is in before they touch anything.

    Built from scratch once, then CLONED per test. Building it costs ~40s
    because every `load-bom` re-renders the whole case page, and a matrix of a
    dozen cells at that price puts the module past the whole suite's runtime.
    The clone goes through `update_case_record`, whose whitelist carries exactly
    the origin state (`products`, `origin_sheet_states`, `origin_product_order`,
    the `bom_*` picks, the snapshots), so a clone is a real persisted case and
    not a fixture shortcut.
    """
    global _TEMPLATE_CASE_ID
    if _TEMPLATE_CASE_ID:
        return _clone_case(_TEMPLATE_CASE_ID, case_code)
    _TEMPLATE_CASE_ID = _build_case(client, "INV-TEMPLATE")
    return _clone_case(_TEMPLATE_CASE_ID, case_code)


def _clone_case(template_case_id: str, case_code: str) -> str:
    from app.co_case_store import create_case_record, get_case_record, update_case_record
    from app.web.client_context import resolve_client

    client_record = resolve_client(CLIENT)
    created = create_case_record(client_record, {
        "title": case_code, "case_code": case_code,
        "destination_market": "Ấn Độ", "invoice_no": INVOICE,
    })
    payload = dict(get_case_record(client_record, template_case_id))
    payload["persisted_case_id"] = created["case_id"]
    payload.pop("case_code", None)
    update_case_record(client_record, payload)
    return created["case_id"]


def _build_case(client: TestClient, case_code: str) -> str:
    created = client.post(
        f"/clients/{CLIENT}/co-case/create",
        data={"title": case_code, "case_code": case_code,
              "destination_market": "Ấn Độ", "invoice_no": INVOICE},
        follow_redirects=False,
    )
    assert created.status_code == 303, created.text[:200]
    case_id = created.headers["location"].rstrip("/").split("/")[-1]
    client.get(f"{_origin(case_id)}")
    for code in sheet_codes(client, case_id):
        client.post(f"{_origin(case_id)}/sheet/{code}/load-bom", data={})
    calculated = client.post(f"{_origin(case_id)}/calculate-all", json={})
    assert calculated.status_code == 200, calculated.text[:200]
    return case_id


def payload_of(client: TestClient, case_id: str) -> dict:
    response = client.get(f"{_origin(case_id)}/calculation-payload")
    assert response.status_code == 200, response.text[:200]
    return response.json()


def sheet_codes(client: TestClient, case_id: str) -> list[str]:
    return list(payload_of(client, case_id).get("origin_product_order") or [])


def snapshot(client: TestClient, case_id: str) -> dict[str, dict]:
    """Per-sheet state, reduced to what the invariants judge.

    `rows` hashes the material rows so "unchanged" is decidable without holding
    the whole sheet; `codes` stays readable so a failure names the material.
    """
    data = payload_of(client, case_id)
    states = data.get("origin_sheet_states") or {}
    out: dict[str, dict] = {}
    for product in data.get("products", []):
        code = str(product.get("code") or "")
        state = states.get(code) if isinstance(states.get(code), dict) else {}
        materials = [m for m in (product.get("materials") or []) if not m.get("deleted")]
        out[code] = {
            "status": state.get("status") or "",
            "calc_seq": int(state.get("calc_seq") or 0),
            "overrides": len(state.get("material_overrides") or {}),
            "codes": [str(m.get("material_code") or "") for m in materials],
            "rows": hashlib.sha256(
                repr([(m.get("material_code"), m.get("quantity"), m.get("unit_value"),
                       m.get("allocation_status")) for m in materials]).encode()
            ).hexdigest()[:16],
        }
    return out


def submit_case_form(client: TestClient, case_id: str):
    """POST the whole `#co-case` form to `/evaluate`, exactly as the UI does.

    The BOM version picker has no submit button of its own: `co_case.html:3049`
    listens for `change` and calls `select.form.requestSubmit()`, and that form
    (`co_case.html:1137`) wraps the entire workspace. So changing one sheet's BOM
    version submits every field of every sheet. Reproducing that here is the only
    way `/evaluate` is reachable in-process.
    """
    page = client.get(f"{_origin(case_id)}")
    assert page.status_code == 200, page.text[:200]
    markup = page.text
    # Anchor on the id, not on "the first form that posts to /clients/…" — the
    # export-bang-ke form (co_case.html:873) comes first in the document and
    # matching it submits the wrong fields to the wrong place.
    opened = re.search(r'<form[^>]*id="co-case"[^>]*>', markup)
    assert opened, "co-case form not found on the origin page"
    action = re.search(r'action="([^"]+)"', opened.group(0))
    assert action and action.group(1).endswith("/evaluate"), opened.group(0)[:160]
    start = opened.end()
    region = markup[start:markup.find("</form>", start)]
    fields: list[tuple[str, str]] = []
    for name, value in re.findall(r'<input[^>]*name="([^"]+)"[^>]*value="([^"]*)"', region):
        fields.append((name, html.unescape(value)))
    for name, body in re.findall(r'<select[^>]*name="([^"]+)"[^>]*>(.*?)</select>', region, re.S):
        chosen = re.search(r'<option value="([^"]*)"[^>]*selected', body)
        if chosen:
            fields.append((name, html.unescape(chosen.group(1))))
    return client.post(f"/clients/{CLIENT}/evaluate", data=fields, follow_redirects=False)


# --------------------------------------------------------------------------- #
# 1. The invariants                                                            #
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class Invariant:
    key: str
    why: str
    check: Callable[[dict, dict, object, dict], list[str]]


def _substitution_survives(before: dict, after: dict, response, ctx: dict) -> list[str]:
    """A substitution recorded on a sheet survives every route except a
    deliberate `load-bom` on that same sheet.

    Incident: `substitute → (any full-form submit) → calculate-all` silently
    restored the original material. The override count is what
    `allocate_whole_case_preview` branches on, so losing it means the next
    whole-case calculation rebuilds the sheet from BOM.
    """
    problems = []
    for code, was in before.items():
        if not was["overrides"]:
            continue
        now = after.get(code)
        if now is None:
            problems.append(f"{code}: sheet disappeared")
        elif now["overrides"] < was["overrides"]:
            problems.append(
                f"{code}: material_overrides {was['overrides']} → {now['overrides']}"
            )
    return problems


def _downstream_not_silently_stale(before: dict, after: dict, response, ctx: dict) -> list[str]:
    """When a route changes sheet N, no later unlocked sheet may stay `calculated`
    on numbers that were never recomputed.

    Stock is allocated sequentially down `origin_product_order`, so changing sheet
    N changes what is left for N+1… The violation is decidable from snapshots:
    Decided by `calc_seq`, the stamp `set_origin_sheet_status(..., calculated=True)`
    bumps every time a sheet's numbers are recomputed. Inferring it from unchanged
    bytes does not work: a sheet recomputed to identical numbers looks exactly
    like one nobody touched. `origin_codes_to_recalculate` (`co_case.py:690`)
    cites the real case — johnson-vn VNG26030079, one substitute on sheet 1 left
    sheets 2-5 stale while the aggregate reported "đủ tồn cho tất cả SP".
    """
    order = ctx["order"]
    changed = [c for c in order if c in before and c in after and before[c]["rows"] != after[c]["rows"]]
    if not changed:
        return []
    first = min(order.index(c) for c in changed)
    problems = []
    for code in order[first + 1:]:
        was, now = before.get(code), after.get(code)
        if not was or not now or now["status"] == "locked":
            continue
        recalculated = now["calc_seq"] > was["calc_seq"]
        marked_stale = now["status"] != was["status"]
        if not recalculated and not marked_stale:
            problems.append(
                f"{code}: neither recalculated (calc_seq {was['calc_seq']}) nor marked stale "
                f"after {order[first]} changed"
            )
    return problems


def _locked_sheet_frozen(before: dict, after: dict, response, ctx: dict) -> list[str]:
    """A locked sheet is what was filed, and the ledger holds `co_stock_claims`
    against exactly its allocation lines. Only `reopen` may move it.
    """
    problems = []
    for code, was in before.items():
        if was["status"] != "locked":
            continue
        now = after.get(code)
        if now is None:
            problems.append(f"{code}: locked sheet disappeared")
        elif now["rows"] != was["rows"] or now["status"] != "locked":
            problems.append(f"{code}: locked sheet changed ({was['status']}→{now['status']})")
    return problems


def _declined_route_changes_nothing(before: dict, after: dict, response, ctx: dict) -> list[str]:
    """A route that refuses the request must leave the case exactly as it was.

    Generalised from the config bug: a rejected or no-op write that still
    rewrites state is how partial input silently resets stored values.
    """
    status = getattr(response, "status_code", 200)
    if status < 400:
        return []
    return [f"{code}: changed on a declined request (HTTP {status})"
            for code in before if code in after and before[code] != after[code]]


INVARIANTS = [
    Invariant("substitution_survives", _substitution_survives.__doc__, _substitution_survives),
    Invariant("downstream_not_silently_stale", _downstream_not_silently_stale.__doc__,
              _downstream_not_silently_stale),
    Invariant("locked_sheet_frozen", _locked_sheet_frozen.__doc__, _locked_sheet_frozen),
    Invariant("declined_route_changes_nothing", _declined_route_changes_nothing.__doc__,
              _declined_route_changes_nothing),
]


def violations(before: dict, after: dict, response, ctx: dict) -> list[str]:
    found = []
    for invariant in INVARIANTS:
        for problem in invariant.check(before, after, response, ctx):
            found.append(f"[{invariant.key}] {problem}")
    return found


def test_every_invariant_states_its_incident():
    # The registry is deliverable 1: an invariant with no recorded reason gets
    # deleted by the next person who finds it inconvenient.
    for invariant in INVARIANTS:
        assert invariant.why and len(invariant.why.strip()) > 80, invariant.key


# --------------------------------------------------------------------------- #
# 2. Route × invariant matrix                                                  #
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class Route:
    name: str
    run: Callable[[TestClient, str, dict], object]
    needs_substitution: bool = True
    walkable: bool = True
    marks: tuple = field(default=())


def _run_calculate_all(client, case_id, ctx):
    return client.post(f"{_origin(case_id)}/calculate-all", json={})


def _run_load_bom_first_sheet(client, case_id, ctx):
    return client.post(f"{_origin(case_id)}/sheet/{ctx['order'][0]}/load-bom", data={})


def _run_load_bom_last_sheet(client, case_id, ctx):
    return client.post(f"{_origin(case_id)}/sheet/{ctx['order'][-1]}/load-bom", data={})


def _run_bulk_substitute(client, case_id, ctx):
    codes = ctx["snapshot"][ctx["order"][0]]["codes"]
    if len(codes) < 2:
        pytest.skip("sheet 1 needs two materials to substitute one for the other")
    return client.post(f"{_origin(case_id)}/bulk-substitute", json={
        "substitutions": [{"product_code": ctx["order"][0],
                           "material_code": codes[0], "substitute_code": codes[1]}],
        "expected_revision": ctx["revision"],
    })


def _run_bulk_delete_rac(client, case_id, ctx):
    return client.post(f"{_origin(case_id)}/bulk-delete-rac",
                       json={"expected_revision": ctx["revision"]})


def _run_column9_mode(client, case_id, ctx):
    return client.post(f"{_origin(case_id)}/column9-mode", json={"mode": "country"})


def _run_case_criteria(client, case_id, ctx):
    return client.post(f"{_origin(case_id)}/case-criteria",
                       json={"criteria_text": "CTH", "chosen_by": "invariant-test"})


def _run_evaluate(client, case_id, ctx):
    return submit_case_form(client, case_id)


def _run_lock_first_sheet(client, case_id, ctx):
    return client.post(f"{_origin(case_id)}/sheet/{ctx['order'][0]}/lock", data={})


def _run_reopen_first_sheet(client, case_id, ctx):
    return client.post(f"{_origin(case_id)}/sheet/{ctx['order'][0]}/reopen", data={})


ROUTES = [
    Route("calculate-all", _run_calculate_all),
    Route(
        "bulk-substitute", _run_bulk_substitute, needs_substitution=False,
        marks=(pytest.mark.xfail(
            strict=True,
            reason="Does not cascade: substituting on sheet 1 leaves later sheets neither "
                   "recalculated nor marked stale. Proven by calc_seq on the running app — "
                   "calculate-all moved CHAIR01 1 / TABLE01 2, then bulk-substitute on CHAIR01 "
                   "moved it to 3 while TABLE01 stayed at 2. The route does call "
                   "mark_origin_sheets_stale + origin_codes_to_recalculate (co_case.py:2056), so "
                   "the machinery is wired but does not fire. Found 2026-08-20; not fixed here.",
        ),),
    ),
    Route("bulk-delete-rac", _run_bulk_delete_rac),
    Route("column9-mode", _run_column9_mode),
    Route("case-criteria", _run_case_criteria),
    Route(
        "load-bom (last sheet)", _run_load_bom_last_sheet,
        marks=(pytest.mark.xfail(
            strict=True,
            reason="load-bom on ONE sheet persists a case containing only that sheet: the other "
                   "sheets vanish from `products` while origin_product_order still lists them, and "
                   "the origin page renders a single tab. Reproduced in-process AND on the live app "
                   "(demo-furniture: CHAIR01 disappeared after load-bom on TABLE01). Any whole-case "
                   "operation rebuilds them, which is why it stayed hidden. Found 2026-08-20 by this "
                   "harness; not fixed here.",
        ),),
    ),
    Route("lock (first sheet)", _run_lock_first_sheet, walkable=False),
    Route("reopen (first sheet)", _run_reopen_first_sheet, walkable=False),
    # No xfail marker: in this seeded world `/evaluate` does NOT drop overrides,
    # even with a faithful 402-field submit carrying persisted_case_id. On the
    # live app the same sequence took the count 1 → 0. The discrepancy is
    # unexplained (see KNOWN GAPS) — marking it xfail(strict) would assert a
    # protection that does not exist here.
    Route("evaluate (whole-form submit)", _run_evaluate, walkable=False),
]

# `load-bom` on sheet 1 is the ONE route allowed to drop that sheet's overrides —
# "Nạp lại cấu trúc = reset về BOM artifact" (co_case.py:2445). Kept out of the
# matrix rather than xfailed: it is correct behaviour, not a known defect.
_LOAD_BOM_FIRST = Route("load-bom (first sheet)", _run_load_bom_first_sheet)


def _context(client: TestClient, case_id: str) -> dict:
    data = payload_of(client, case_id)
    return {
        "order": list(data.get("origin_product_order") or []),
        "revision": data.get("revision") or "",
        "snapshot": snapshot(client, case_id),
    }


def _seed_substitution(client: TestClient, case_id: str) -> None:
    ctx = _context(client, case_id)
    codes = ctx["snapshot"][ctx["order"][0]]["codes"]
    if len(codes) < 2:
        pytest.skip("seeded case needs two materials on sheet 1")
    applied = client.post(f"{_origin(case_id)}/bulk-substitute", json={
        "substitutions": [{"product_code": ctx["order"][0],
                           "material_code": codes[0], "substitute_code": codes[1]}],
        "expected_revision": ctx["revision"],
    })
    assert applied.status_code == 200, applied.text[:200]
    assert snapshot(client, case_id)[ctx["order"][0]]["overrides"] >= 1


@pytest.mark.parametrize(
    "route",
    [pytest.param(r, id=r.name, marks=r.marks) for r in ROUTES],
)
def test_route_preserves_invariants(world: TestClient, route: Route):
    case_id = make_case(world, f"INV-{abs(hash(route.name)) % 100000}")
    if route.needs_substitution:
        _seed_substitution(world, case_id)
    ctx = _context(world, case_id)
    before = ctx["snapshot"]
    response = route.run(world, case_id, ctx)
    after = snapshot(world, case_id)
    problems = violations(before, after, response, ctx)
    assert not problems, f"{route.name}:\n  " + "\n  ".join(problems)


@pytest.mark.xfail(
    strict=True,
    reason="Blocked by the same defect as the matrix cell: load-bom drops the OTHER sheets from the "
           "case, so the assertion that they keep their overrides raises KeyError instead.",
)
def test_load_bom_on_a_sheet_may_drop_that_sheets_overrides(world: TestClient):
    # The documented exception, pinned so it stays deliberate: Nạp BOM resets the
    # sheet to the BOM artifact, and only that sheet.
    case_id = make_case(world, "INV-LOADBOM")
    _seed_substitution(world, case_id)
    ctx = _context(world, case_id)
    before = ctx["snapshot"]
    _LOAD_BOM_FIRST.run(world, case_id, ctx)
    after = snapshot(world, case_id)
    first, rest = ctx["order"][0], ctx["order"][1:]
    assert after[first]["overrides"] == 0
    for code in rest:
        assert after[code]["overrides"] == before[code]["overrides"], code


# --------------------------------------------------------------------------- #
# 3. Random walk over route sequences                                          #
# --------------------------------------------------------------------------- #
# Fixed seeds, never `random.random()` — conftest keeps the suite deterministic
# so a failure reproduces. `lock`/`reopen` are excluded: their claims hit the
# shared per-client ledger, so one walk's lock changes the next walk's available
# stock. They are covered as matrix cells instead.
_WALKABLE = [r for r in ROUTES if r.walkable]


@pytest.mark.parametrize("seed", [11, 29, 47])
def test_random_route_walk_preserves_invariants(world: TestClient, seed: int):
    rng = random.Random(seed)
    case_id = make_case(world, f"INV-WALK-{seed}")
    _seed_substitution(world, case_id)
    trail: list[str] = []
    for _ in range(6):
        route = rng.choice(_WALKABLE)
        ctx = _context(world, case_id)
        before = ctx["snapshot"]
        response = route.run(world, case_id, ctx)
        after = snapshot(world, case_id)
        trail.append(f"{route.name} → HTTP {getattr(response, 'status_code', '?')}")
        problems = violations(before, after, response, ctx)
        assert not problems, (
            "walk seed %d\n  %s\nviolations:\n  %s"
            % (seed, "\n  ".join(trail), "\n  ".join(problems))
        )
