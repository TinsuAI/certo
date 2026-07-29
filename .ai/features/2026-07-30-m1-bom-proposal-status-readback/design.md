# M1 sub-bug 1 — BOM proposal status readback (adopt-on-approve)

Status: design (no app code changed)
Branch: `agent/m1-status-readback-design`
Backlog: `.ai/BACKLOG.md` § M1 (sub-bug 1, downgraded 2026-07-17 — CO-side wiring only)

## Problem

After an operator saves a modified BOM ("Lưu BOM mới"), CO POSTs
`…/origin/sheet/{code}/propose-bom` (`app/routers/co_case.py:2845`), Data Hub
returns `{proposal_id, status, ...}`, and CO stores the status once into
`case["origin_sheet_states"][code]["proposed_status"]`
(`app/routers/co_case.py:2897`). On every later render,
`attach_origin_sheet_states` only ECHOES that stored value onto the product dict
(`app/web/co_case_context.py:1361-1367`) and the template prints it
(`app/templates/co_case.html:1287`). CO never reads the proposal back from Data
Hub. When a Data Hub reviewer approves the proposal (`pending` → `approved`), CO
stays stuck showing `pending`.

The read method already exists — `DataHubClient.get_bom_proposal(proposal_id)`
(`app/data_hub_client.py:440`, `GET /v1/hub/proposals/{proposal_id}`) — with 0
callers. This is CO-side wiring only.

## Data Hub contract (verified, sufficient — no API request needed)

Verified against the Data Hub source, not assumed:

- `GET /v1/hub/proposals/{proposal_id}` (`data-hub/app/routes/api.py:1743`)
  returns the full `hub.bom_change_requests` row:
  `proposal_id, client_id, product_code, actor, intent, parent_artifact_id,
  context, status, decided_at, decided_by, decision_reason, failed_conditions,
  materialized_artifact_id, normalized_hash, created_at`.
- Status vocabulary (`data-hub/app/stores/bom.py`): `pending`, `approved`,
  `rejected`, `withdrawn`. CO's own placeholder `"submitted"` is written only
  when Data Hub omits `status`; in practice Data Hub always returns a real status
  (`submit_proposal` lands `pending` in manual mode, `approved`/`rejected` in
  auto/hybrid).
- `materialized_artifact_id` is the new BOM artifact id created on approve
  (`approve_proposal` → `create_artifact`, `data-hub/app/stores/bom.py:1263-1294`).
  It is populated ONLY when `status == "approved"`; null otherwise.
- Auth: `_require_token` + `_require_can_view_client(claims, proposal.client_id)`
  — read scope (`hub:read`), Bearer service token. The proposal's own
  `client_id` scopes the read; the caller does NOT pass a `client_id`, so CO's
  existing `get_bom_proposal(proposal_id)` signature is correct.
- The endpoint is already in the guardrail approved set
  (`tests/test_data_hub_policy.py:23`) and `HUB_PROPOSAL_PATH` is already defined
  (`app/data_hub_client.py:24`).

`get_bom_proposal` returns the raw JSON dict (`app/data_hub_client.py:441`), so it
already surfaces `status` + `materialized_artifact_id`. Everything the
adopt-on-approve flow needs is in the current response.

**Decision: no `.ai/api-requests/` artifact.** The 2026-07-17 backlog downgrade
is confirmed by the Data Hub source. The pre-2026-07-17 note that assumed a
missing endpoint is superseded. Do not invent a gap.

## Where the read fires — `co_case_step` GET only

Fire the readback in the origin tab GET handler `co_case_step`
(`app/routers/co_case.py:1095`), guarded on `step == "origin"`. Do NOT fire it in:

- `co_case_context` (`app/web/co_case_context.py:3489`) — it is the shared entry
  point for the GET render AND ~20 POST partial handlers (save, calculate, lock,
  reopen, reorder, override, column9-mode, substitute, etc.; callers at
  `app/routers/co_case.py:297, 1203, 1243, 1664, 1669, 2018, 2028, 2128, 2135,
  2230, 2254, 2288, 2304, 3230, 3383, 3407, 3423`). Firing here would add a Data
  Hub round-trip and a possible `update_case_record` write to every mutating
  partial and to non-origin steps (shipment/documents/exports/review). A save or
  lock POST must not silently write proposal-status changes as a side effect.
- `attach_origin_sheet_states` (`app/web/co_case_context.py:1239`) — it is a pure
  transform called from ~15 sites including POST paths, has no `client`/token in
  scope, and does no I/O. Doing network reads there would break its contract and
  fan the read out to every save/calculate.

The origin tab (`/clients/{cid}/co-case/{case_id}/origin`) is always served by
`co_case_step` with `step == "origin"`; the base detail route `co_case_detail`
(`app/routers/co_case.py:1076`) renders `shipment`, never origin. So gating on
`co_case_step` + `step == "origin"` covers exactly the render that shows the
proposal status and nothing else.

## Terminal-status policy

Per sheet in `case["origin_sheet_states"]`, poll only when there is a
`proposed_proposal_id` AND the stored `proposed_status` is non-terminal.

- Non-terminal (poll): `pending`, `submitted`, `""` (empty with a proposal_id).
- Terminal (stop polling): `approved`, `rejected`, `withdrawn`.

On transition:

- `approved` → adopt the approved artifact: set
  `proposed_status = "approved"` and
  `proposed_artifact_id = materialized_artifact_id` (so the "Đã propose" note and
  the sheet's proposed-artifact reference point at the real approved artifact).
  **Do NOT re-bind the locked sheet's `bom_product_artifact_id` to the new
  artifact.** The sheet is `locked`; its RVC/VNM was computed and submitted
  against the parent BOM. Silently swapping the bound artifact would change a
  chốt sheet's calculation basis. Adoption here means "reflect the approved
  status + record the approved artifact id for display/dossier", not "recompute
  the locked bảng kê". (If a future requirement wants an explicit "rebuild sheet
  on the approved BOM" action, that is a separate, operator-initiated flow.)
- `rejected` / `withdrawn` → set `proposed_status` to that value; leave
  `proposed_artifact_id` as-is (there is no materialized artifact). The template
  shows the terminal status; the operator can decide to re-propose.

A terminal status is never re-polled, so an approved/rejected sheet costs zero
Data Hub calls on subsequent renders.

## Persistence write-back + in-request context update

1. Build `context = co_case_context(client_id, case_id, "origin", …)` as today.
   Its `context["case"]` already carries the OLD echoed `proposed_status` on each
   product (via `attach_origin_sheet_states` inside `co_case_light_context`).
2. Run the readback over `context["case"]["origin_sheet_states"]`. Collect the
   changed `{code: {proposed_status, proposed_artifact_id}}`.
3. If anything changed: apply the deltas onto
   `context["case"]["origin_sheet_states"]`, then call
   `update_case_record(client, context["case"])` to persist (same store write the
   propose-bom handler already uses at `app/routers/co_case.py:2900`).
4. If anything changed: re-run
   `context["case"] = attach_origin_sheet_states(context["case"])` so the product
   dicts re-echo the fresh `origin_sheet_proposed_status` /
   `origin_sheet_proposed_artifact_id` — the SAME render then shows the new
   status, no second request needed. `attach_origin_sheet_states` is idempotent
   and reads `proposed_*` straight from `origin_sheet_states`
   (`app/web/co_case_context.py:1359-1367`), so re-running it after the delta is
   the minimal correct re-derivation.
5. If nothing changed: do NOT call `update_case_record` — avoid a needless write
   (and a needless `updated_at` bump) on every origin render.

`update_case_record` persists `origin_sheet_states` (it is in the write
whitelist, `app/co_case_store.py:180`). Its close-state gate
(`app/co_case_store.py:160-165`) rejects writes on completed cases — a closed
case's origin render must not attempt the write-back; skip both the poll and the
write-back when the case is completed (the proposal outcome is no longer
actionable on a closed case). On reopen the status is picked up on the next
origin render.

## Error isolation (Data Hub downtime must not break the page)

- Wrap each `get_bom_proposal` call in `try/except Exception` inside the readback
  loop; on any failure (timeout, 5xx, 404 on a purged/unknown proposal, missing
  scope) skip that sheet and keep its stored status. This mirrors the existing
  defensive pattern in `declaration_file_counts`
  (`app/data_hub_client.py:1021-1034`) and `co_stock_summary`
  (`app/web/co_case_context.py:3557-3560`).
- The readback never raises out of `co_case_step`; the origin tab always renders
  with the last-known statuses when Data Hub is unreachable.
- File-store / offline mode: `PortfolioService.get_bom_proposal` returns `{}`
  (see delegate below), so the loop treats every sheet as "no update" and the
  page behaves exactly as today.

## Adapter delegates to add

### `DataHubPortfolioService` (Data Hub backend) — `app/data_hub_client.py`, next to `submit_bom_proposal` (~line 765)

```python
def get_bom_proposal(self, proposal_id: str) -> dict:
    if not hasattr(self.data_hub, "get_bom_proposal"):
        return {}
    return self.data_hub.get_bom_proposal(proposal_id) or {}
```

Mirrors the `hasattr`-guarded delegation of `submit_bom_proposal`
(`app/data_hub_client.py:765-786`). No `client_id` argument — the Data Hub
endpoint scopes by the proposal's own `client_id`. `DataHubClient.get_bom_proposal`
already exists (`app/data_hub_client.py:440`); it needs no change.

### `PortfolioService` (file-store / offline backend) — `app/portfolio.py`, next to `submit_bom_proposal` (~line 193)

```python
def get_bom_proposal(self, proposal_id: str) -> dict:
    # File-store / offline: no Data Hub proposal store. Return empty so the
    # readback treats it as "no update" and keeps the stored status.
    return {}
```

Unlike `submit_bom_proposal` (which raises 503 because proposing requires Data
Hub), the READ degrades to a no-op `{}` — a render must never fail just because
the backend can't answer a status poll.

Both delegates are reachable through the `portfolio_service` proxy
(`app/portfolio.py:289`) that dispatches to whichever backend is active.

## Router orchestration function

Add one helper in `app/routers/co_case.py` (it already imports `portfolio_service`,
`update_case_record`, `attach_origin_sheet_states`, and defines
`persisted_origin_case`):

```python
_TERMINAL_PROPOSAL_STATUSES = frozenset({"approved", "rejected", "withdrawn"})

def refresh_origin_proposal_statuses(client: dict, case: dict) -> tuple[dict, bool]:
    """Poll Data Hub for each non-terminal sheet proposal; adopt approved
    artifacts. Returns (case, changed). Never raises on Data Hub failure."""
    states = case.get("origin_sheet_states") or {}
    changed = False
    for code, state in states.items():
        if not isinstance(state, dict):
            continue
        proposal_id = str(state.get("proposed_proposal_id") or "").strip()
        status = str(state.get("proposed_status") or "").strip()
        if not proposal_id or status in _TERMINAL_PROPOSAL_STATUSES:
            continue
        try:
            proposal = portfolio_service.get_bom_proposal(proposal_id) or {}
        except Exception:  # noqa: BLE001
            continue
        new_status = str(proposal.get("status") or "").strip()
        if not new_status or new_status == status:
            continue
        state["proposed_status"] = new_status
        if new_status == "approved":
            adopted = str(proposal.get("materialized_artifact_id") or "").strip()
            if adopted:
                state["proposed_artifact_id"] = adopted
        changed = True
    return case, changed
```

Call it from `co_case_step` when `step == "origin"` and the case is not completed,
persisting + re-echoing only on change:

```python
if step == "origin":
    client = resolve_client(client_id)
    case = context["case"]
    record = get_case_record(client, case_id) if case.get("persisted_case_id") else None
    if record is not None and not co_case_is_completed(record):
        case, changed = refresh_origin_proposal_statuses(client, case)
        if changed:
            update_case_record(client, case)
            context["case"] = attach_origin_sheet_states(case)
```

(`co_case_is_completed` and `get_case_record` are already imported into
`app/web/co_case_context.py`; import them into the router, or reuse the
`get_case_record` + completed check pattern already present in the `review`
branch at `app/routers/co_case.py:1101-1113`.)

## Sequence

1. `GET /clients/{cid}/co-case/{case_id}/origin` → `co_case_step(step="origin")`.
2. `co_case_context(...)` builds the render; product dicts carry the stored
   `origin_sheet_proposed_status` (possibly stale `pending`).
3. `refresh_origin_proposal_statuses(client, context["case"])`:
   - for each sheet with `proposed_proposal_id` and non-terminal status:
     `portfolio_service.get_bom_proposal(pid)` (try/except → skip on error);
   - `pending → approved`: record `approved` + adopt `materialized_artifact_id`;
     `pending → rejected/withdrawn`: record terminal status.
4. If any changed: `update_case_record(client, case)` then
   `context["case"] = attach_origin_sheet_states(case)` so the fresh status shows
   on this render.
5. `TemplateResponse` renders — `co_case.html:1287` now prints the real status.

## Touch-points (file:line)

- `app/data_hub_client.py:440` — `DataHubClient.get_bom_proposal` (exists; no change).
- `app/data_hub_client.py:~765` — add `DataHubPortfolioService.get_bom_proposal` delegate.
- `app/portfolio.py:~193` — add `PortfolioService.get_bom_proposal` no-op delegate.
- `app/routers/co_case.py:1095` — `co_case_step`: fire the readback when `step == "origin"`.
- `app/routers/co_case.py` — add `refresh_origin_proposal_statuses` helper + `_TERMINAL_PROPOSAL_STATUSES`.
- `app/routers/co_case.py:2897` — the one-shot `proposed_status` write (unchanged; the readback supersedes it on later renders).
- `app/web/co_case_context.py:1359-1367` — `attach_origin_sheet_states` echo (unchanged; re-run after the delta to re-echo).
- `app/co_case_store.py:180` — `update_case_record` persists `origin_sheet_states` (write path, unchanged).
- `app/templates/co_case.html:1287` — renders `origin_sheet_proposed_status` (unchanged).

## Test list

Adapter delegate tests (`tests/test_data_hub_integration.py` style, MockTransport):
- `DataHubPortfolioService.get_bom_proposal("prop-1")` delegates to
  `DataHubClient.get_bom_proposal` and returns the full row, including
  `materialized_artifact_id` and `status` (extend the existing mock at
  `tests/test_data_hub_integration.py:863` to return
  `{"proposal_id": "prop-1", "status": "approved",
  "materialized_artifact_id": "bv_NEW"}`).
- `DataHubPortfolioService.get_bom_proposal` returns `{}` when the underlying
  `DataHubClient` lacks the method (hasattr guard).
- `PortfolioService.get_bom_proposal("prop-1")` (file-store) returns `{}` and does
  not raise.

GET-refresh test (`tests/test_co_demo.py` style, monkeypatch `portfolio_service`):
- Seed a locked sheet with `proposed_status="pending"`,
  `proposed_proposal_id="prop-1"`. Stub `portfolio_service.get_bom_proposal` →
  `{"status": "approved", "materialized_artifact_id": "bv_NEW"}`. GET the origin
  tab → rendered HTML shows `approved` and the adopted artifact `bv_NEW`; reload
  the persisted record and assert `origin_sheet_states["<code>"]["proposed_status"]
  == "approved"` and `proposed_artifact_id == "bv_NEW"`.

Terminal-status transition tests:
- `pending → approved` adopts `materialized_artifact_id` into
  `proposed_artifact_id`.
- `pending → rejected` sets `proposed_status="rejected"` and does NOT change
  `proposed_artifact_id`.
- An already-`approved` sheet is not re-polled: assert `get_bom_proposal` is not
  called (spy/counter) when the stored status is terminal.
- No-op guard: `pending → pending` (unchanged) does NOT call `update_case_record`
  (spy on the store write).

Data Hub error isolation test:
- Stub `portfolio_service.get_bom_proposal` to raise `RuntimeError`. GET the
  origin tab → HTTP 200, the page shows the stored `pending`, and
  `update_case_record` is not called.

Guardrail (already green, assert still green): `tests/test_data_hub_policy.py`
— the endpoint is in the approved set (`:23`) and the only raw `/v1/hub` literal
stays in `app/data_hub_client.py`; the new delegates and router loop touch no raw
endpoint string.

## Out of scope

Sub-bug 2 (the "Đã propose ✓" button re-POSTs because `initOriginProposeBom`,
`app/templates/co_case.html:5687`, only sets/clears `disabled`) is a separate JS
fix and is not part of this readback design.
