# Parallel agent run — decisions & open questions (2026-07-30)

Durable record of the decisions and open questions surfaced by the ~25 `agent/*`
branch run (fixes + design docs + reviews). This is a factual record, not a
re-derivation. Each item lists the source branch and a verification status:

- **verified** — the one-line claim was checked against code in this worktree.
- **reported-not-verified** — recorded as stated by the run; not independently checked here.

Branches referenced below live on the shared repo. One (`agent/sec-secure-cookie`)
was referenced by the run but is **not present** in this worktree's branch list
(noted inline).

---

## RD1 — Form picker in step 1

**Decision: DROP the step-1 form picker; keep only `destination_market`.**
`co_form_type` has zero calc/export consumers — it is derived from the market
(`recommended_form_lane`) and only persisted/displayed.

- Branch: `agent/rd1-form-step-design`
- Status: **verified.** `co_form_type` appears only in persistence
  (`app/workflow_state_store.py`), the IO field list (`app/workbook_io.py`),
  store defaults (`app/co_case_store.py`, `app/client_registry.py`,
  `app/demo_data.py`, `app/web/client_context.py`), and display templates
  (`app/templates/co_case.html`). No match in any calc/export/bảng-kê module.
  The template hidden field is set from `recommended_form_lane.display_name`
  (derived from market), and `co_case.html:2890` comments "Form is derived from
  market (no step-1 picker)".

## M1 — BOM proposal status read-back

**No new Data Hub API request needed.** `get_bom_proposal` +
`GET /v1/hub/proposals/{proposal_id}` already return proposal status (and
`materialized_artifact_id`). The read fires in the `co_case_step` GET, origin
step only.

- Branch: `agent/m1-status-readback-design` (companion: `agent/m1-propose-bom`)
- Status: **verified (endpoint) / reported-not-verified (payload field).**
  `app/data_hub_client.py:440 get_bom_proposal(proposal_id)` hits
  `HUB_PROPOSAL_PATH = "/v1/hub/proposals/{proposal_id}"` and that path is in the
  approved-endpoint set of `tests/test_data_hub_policy.py` — so consuming it needs
  no new API request. `materialized_artifact_id` is a Data Hub response field and
  has **no consumer yet in `app/`** (grep: 0 hits); that the DH response carries it
  is reported-not-verified from this repo.

## M1 sub-bug 2 — double-POST on propose

**Client re-POST guard shipped, but the SERVER route has no idempotency check.**
Follow-up work to add server-side idempotency.

- Branch: `agent/m1-server-idempotency`
- Status: reported-not-verified.

## B6 — FX conversion fix regression

**The shipped B6 fix regressed the common VND row inside a foreign-currency
export.** Corrected so legacy VND rows still convert.

- Branch: `agent/b6-fix-regression` (tip `10b46a5` — "gate `_vnd` fallback on VND
  rows so legacy VND still converts"). Related: `agent/b6-fx-double-rate`.
- Status: reported-not-verified (branch + commit subject confirm the fix exists;
  regression behaviour not re-run here).

## Fix F — cold-start over-claim — OPEN DECISION

Two positions, unresolved:
- **Fix as shipped:** hard-block sheet lock when there is no CO stock snapshot
  (branch tip `67997c7` — "block sheet lock at cold start when no CO stock
  snapshot").
- **Critic:** prefers validate-on-the-fly to avoid an onboarding dead-end (a new
  client with no snapshot cannot lock anything).

- Branch: `agent/fix-f-coldstart-overclaim`
- Status: reported-not-verified. **Needs a decision** (hard-block vs. validate-on-the-fly).

## Phase-2 batch flow — premise was STALE

The "batch flow is gated off" premise is **stale** — the batch flow was already
re-enabled in `5851d19` ("feat(origin): batch 'Tính tồn tất cả (SP)' — calculate
+ persist all sheets"). Only `preview-stock-all` is dead code.
Recommendation: keep the batch flow + add a pre-flight summary.

- Branch: `agent/phase2-batch-preflight-design`
- Status: **verified.** `5851d19` exists with that subject; `preview-stock-all`
  exists as a route in `app/routers/co_case.py:1747` (dry-run, no-save).

## FX1 — Form X market pair

**The corpus says Mẫu X = Vietnam → Cambodia (17/2011/TT-BCT), NOT Vietnam-Laos**
as `.ai/BACKLOG.md` assumed. Needs client confirmation before wiring PSR /
thresholds.

- Branch: `agent/fx1-form-x-scaffold`
- Status: **SUPERSEDED 2026-08-21 — reject the branch.** No client confirmation needed: the
  agency workbook (`tru-lui-co-template.xlsm`, sheet `FORM X`) settles it. That sheet is
  VCCI-certified, cites `05/2018/TT-BCT` (Form B's circular), carries a 30% origin criterion,
  and has consignor and consignee both in Đồng Nai — a domestic on-the-spot delivery, not a
  Cambodia export. The corpus reading of `17/2011/TT-BCT` is correct about *a* Mẫu X, but it is
  a different form sharing the letter. Full evidence in `.ai/BACKLOG.md` under FX1.
  This section's premise that the backlog "assumed Vietnam-Laos" is also wrong — it never did.

## D1 — delta-vs-full refresh parity

**Parity HOLDS** — no drift found between delta refresh and full refresh in the
materializer.

- Branch: `agent/d1-parity-harness` (tip `b3ae4d4` — "D1 delta-vs-full parity
  harness for the materializer"). Related: `agent/d1-refresh-reason`.
- Status: reported-not-verified (harness exists; parity result not re-run here).

## Security — red-team findings

1. **Secure cookie flag defaults OFF (fail-open).**
   - Status: **verified.** `app/co_auth.py:396,408` set the session cookie
     `secure=data_hub_link_settings().force_https_cookie`;
     `force_https_cookie = env_flag(CO_FORCE_HTTPS_COOKIE)`
     (`app/data_hub_settings.py:78`), and `env_flag(None)` returns `False`
     (`app/data_hub_settings.py:97`). Unset env → cookie sent without `Secure`.
   - Fix branch `agent/sec-secure-cookie` was referenced by the run but is
     **not present in this worktree's branch list** (reported-not-verified that
     the fix branch exists).
2. **`should_guard_path` is a fail-open allowlist** — it returns `True` only for
   an explicit set of prefixes (`/`, `/clients`, `/portfolio`, `/user`,
   `/whats-new`, `/settings`, …); anything not listed is unguarded.
   `/customs-exchange-rates` is **not** in the allowlist.
   - Status: **verified.** `app/co_auth.py:182 should_guard_path`;
     `/customs-exchange-rates` route at `app/routers/customs_fx.py:51` is outside
     the allowlist.
3. **DH guardrail test is substring-only (evadable, no current evasion).**
   `tests/test_data_hub_policy.py` flags a file only if the literal `"/v1/hub"`
   substring appears — a call built by string concatenation would slip past.
   - Status: **verified.** The test does `if "/v1/hub" in path.read_text(...)`.
     No current evasion in the tree.

## Test gap

The highest-risk paths — over-claim, claims-blocking-removal, delta-vs-full — run
**only in DB-mode** and are skipped by the file-mode, CI-style suite.

- Branch: `agent/test-gap-analysis` (related: `agent/test-harden-belts`)
- Status: reported-not-verified.

## Merge order (from QA audit)

All agent branches are **textually clean pairwise** (no overlapping hunks). Land:
1. `agent/t1-test-db-isolation` first (tip `8bef7ab` — "isolate DB-mode tests into
   a disposable co_test schema").
2. Then the disjoint singletons.
3. Then the `co_case.py` / `co_stock_ledger` / `co_case_context` clusters.
4. Run the full suite after the `co_case.py` trio.

- Status: reported-not-verified (ordering is the audit's recommendation).

---

## Open questions

- **Fix F:** hard-block lock at cold start vs. validate-on-the-fly. Onboarding a
  new client with no snapshot currently cannot lock.
- **FX1:** confirm Mẫu X market pair with the client (corpus: Vietnam→Cambodia;
  backlog assumed Vietnam-Laos) before PSR/thresholds.
- **M1:** does the DH `GET /v1/hub/proposals/{id}` response actually carry
  `materialized_artifact_id`? No CO consumer exists yet to prove it.

## What to do next

1. Decide Fix F (hard-block vs. validate-on-the-fly), then keep/replace
   `agent/fix-f-coldstart-overclaim`.
2. Get client confirmation on the Form X market pair; correct `.ai/BACKLOG.md`
   (Vietnam-Laos → Vietnam-Cambodia) before building `agent/fx1-form-x-scaffold`.
3. Land `agent/sec-secure-cookie` once located (branch not in this worktree) — the
   secure-cookie fail-open is code-verified and worth shipping. Consider adding
   `/customs-exchange-rates` to the `should_guard_path` allowlist and tightening
   the DH guardrail test beyond substring matching.
4. Add server-side idempotency for BOM propose (`agent/m1-server-idempotency`).
5. Close the DB-mode-only test gap so over-claim / claims-blocking-removal /
   delta-full run in the file-mode CI suite (`agent/test-gap-analysis`,
   `agent/test-harden-belts`).
6. Merge in the QA-audit order: `agent/t1-test-db-isolation` → disjoint singletons
   → `co_case.py` / `co_stock_ledger` / `co_case_context` clusters; run the full
   suite after the `co_case.py` trio.
