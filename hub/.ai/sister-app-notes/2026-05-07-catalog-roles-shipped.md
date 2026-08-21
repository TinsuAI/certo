# Catalog roles refactor — shipped

**Date:** 2026-05-07
**For:** CO + BCQT
**Data Hub commits:** TBD (mig 033 view + resolver wire + API expose + catalog UI)
**Brief:** `.ai/features/2026-05-07-catalog-roles-refactor/brief.md` (rev 5)

## What shipped

`hub.materials.category` (declared, single value, agency intent) is no longer
the only signal a code's role. New SQL view `hub.v_material_roles` derives
per-code observation signals from the data graph (BCCT direction patterns +
BOM membership). Both surfaced in API responses.

Affects:
- `GET /v1/hub/materials` — additive fields per item
- `GET /v1/hub/materials/{customs_code}` — additive fields
- `GET /v1/hub/bcct.product_identity` (top-level + per-candidate) — additive fields
- `GET /v1/hub/bcct/invoice-matches.product_identity` — same shape

## Response shape

### Per material item (`/v1/hub/materials*`)

```jsonc
{
  "customs_code": "PV01.0104300",
  "internal_code": "PV01.0104300",
  "name": "...",
  "category": "btp_sx",            // declared (existing)
  "category_override": null,        // existing
  "btp_sourcing": "self_produced_only",  // Phase 3a (existing)

  // NEW — atomic signals (boolean) per (client_id, customs_code):
  "has_imports":         false,
  "has_exports":         true,
  "is_consumed_in_bom":  true,
  "has_own_bom":         true,

  // NEW — derived array of observed roles {tp, btp_sx, nvl}:
  "observed_roles":      ["tp", "btp_sx"],

  // NEW — boolean flags:
  "is_multi_role":              true,    // len(observed_roles) >= 2
  "declared_observed_conflict": false    // see "Conflict semantics" below
}
```

### Per BCCT product_identity (top-level)

```jsonc
{
  "resolution_status": "resolved",
  "resolved_code": "PV01.0117500",
  "bom_product_code": "PV01.0117500",
  "product_kind": "tp",            // declared (single value)

  // NEW (top-level, full set):
  "observed_roles":      ["tp"],
  "has_imports":         false,
  "has_exports":         true,
  "is_consumed_in_bom":  false,
  "has_own_bom":         true,
  "is_multi_role":       false,
  "btp_sourcing":        null,
  "declared_observed_conflict": false
}
```

### Per candidate (inside `product_identity.candidates[]`)

Per D6, per-candidate gets MINIMAL field set (atomic signals NOT propagated):

```jsonc
{
  "product_code": "PV01.0117500",
  "source": "goods_name_embedded_code",
  "confidence": "high",
  "reason": "...",
  "product_kind": "tp",
  "observed_roles": ["tp"],         // NEW
  "bom_artifact_count": 3,
  "latest_flatten_status": "flattened"
}
```

## Derivation rules (D4 of the brief — rev 2 after mig 034)

**Rules in production (current):**

```
'tp'      ⟸ has_exports
'btp_sx'  ⟸ is_consumed_in_bom AND has_own_bom
'nvl'     ⟸ has_nvl_import AND NOT has_own_bom
```

**`has_nvl_import` is a new atomic signal** (mig 034) — true when at least one
BCCT import row has `declaration_type` in the canonical NVL set per
QĐ 1357/QĐ-TCHQ:

| declaration_type | Name | Why NVL |
|---|---|---|
| E11 | Nhập NVL của DNCX từ nước ngoài | Pure NVL import for DNCX |
| E15 | Nhập NVL của DNCX từ nội địa | Pure NVL import (domestic) |
| E21 | Nhập NVL gia công cho NN | Material for processing-for-foreign |
| E23 | Nhập NVL gia công từ HĐ khác | Material transferred from other processing |
| E31 | Nhập NVL sản xuất xuất khẩu | NVL for SXXK |
| E33 | Nhập NVL vào kho bảo thuế | NVL into bonded warehouse |

**Excluded from auto-NVL** (require operator confirm via declared category):
- E13: Nhập hàng hóa khác vào DNCX (mixed: NVL + máy móc + CCDC)
- E41: Nhập SP thuê gia công NN (TP, not NVL)
- A-series: commercial / domestic SX (could be anything)
- G-series: tạm nhập (temporary)
- H, C: special cases

**Old rule (pre-mig-034) was too strict** — required `is_consumed_in_bom`
in addition. That meant NVL imports waiting for BOM upload of the consuming
TP would not yet be classified. Relaxed because BCCT import declaration
+ canonical declaration_type carries enough domain signal.

The atomic signal `has_imports` (any direction='import') is also still
exposed — broader than `has_nvl_import`. UI/consumer use `has_imports`
for "↓ nhập" hint when a code has activity but doesn't fire any role
(e.g. only A11 commercial imports).

A code can hold multiple roles. Walk-through (post-mig-034):

| Pattern | observed_roles |
|---|---|
| Pure TP (exp + own_bom) | `["tp"]` |
| Rework TP (exp + consumed + own_bom, e.g. cải chế) | `["tp", "btp_sx"]` |
| BTP self-produced (consumed + own_bom) | `["btp_sx"]` |
| BTP purchased no-bom (NVL-type-imp + consumed) | `["nvl"]` ← collapses with Pure NVL |
| Pure NVL (NVL-type-imp, with or without consume) | `["nvl"]` |
| Imported-only (NVL-type-imp, no other signal) | `["nvl"]` ← post-mig-034 |
| Imported-only (non-NVL-type, e.g. A11 commercial) | `[]` (operator confirms) |
| Re-export trader (NVL-type-imp + exp) | `["tp", "nvl"]` ← post-mig-034 multi-role |
| Trader-also-consumer (NVL-type-imp + exp + consumed) | `["tp", "nvl"]` |

**Important — structural collapse:** BTP-purchased-without-own-BOM and
Pure NVL look IDENTICAL in observed_roles (both `["nvl"]`). The
distinguisher is `btp_sourcing`:

- `btp_sourcing IS NULL` (or `'self_produced_only'`) → likely pure NVL.
- `btp_sourcing IN ('purchased_only', 'dual_source')` → BTP purchased.

**Caveat (Phase 3a chicken-and-egg):** the Phase 3a classifier that sets
`btp_sourcing` only iterates over codes already declared `category='btp_sx'`.
A code mistakenly declared `nvl` that's structurally a purchased BTP will
keep `btp_sourcing = NULL` — `observed_roles=['nvl']` + `btp_sourcing IS NULL`
is NOT a guarantee of pure NVL. If your consumer needs absolute certainty,
fix the declared category first.

## Conflict semantics (D8)

`declared_observed_conflict` fires when:
- ≥1 observed role exists, AND
- declared category is in `{tp, btp_sx, nvl, ccdc}`, AND
- declared = `ccdc` OR declared NOT IN observed_roles.

Examples:

| declared | observed_roles | Conflict | Why |
|---|---|---|---|
| tp | `[]` | ❌ | Orphan, not yet transacted |
| tp | `["btp_sx"]` | ✓ | Declared TP but only consumed |
| tp | `["tp", "btp_sx"]` | ❌ | Rework, declared still in observed |
| nvl | `["nvl"]` | ❌ | Match |
| nvl | `["tp"]` | ✓ | Re-export trader misdeclared |
| ccdc | `["nvl"]` | ✓ | CCDC shouldn't show observable role |
| btp_nm | any | ❌ | Distinguished only by btp_sourcing, not observation |

UI surfaces conflicts as a warning chip. Don't auto-correct.

## `is_multi_role` rule changed (R4)

- **Before:** hardcoded `category=='btp_sx' AND has_exports` (rework only).
- **Now:** `len(observed_roles) >= 2`.

On Growatt + Johnson today, both rules flag the same set (1 rework code on
Growatt). Generalization adds future coverage of `["tp", "nvl"]` (trader-
also-consumer) which the old rule missed.

## Known-lossy states

The 3-role enum collapses 4 structurally-weird patterns into either `[]`
or single-role outputs. Documented in brief D4. Affects:

- consumed but not imported, no own BOM (phantom child) → `[]`
- imported + own BOM, never consumed (pre-production setup) → `[]`
- exported + consumed, no source (phantom source) → `["tp"]` (consumption signal lost)
- exported + imported + own BOM, never consumed (rare) → `["tp"]` (imp signal lost)

These are integrity-error or transitional states. Consumers needing full
graph picture should query atomic signals directly, not just `observed_roles[]`.

## Update model

- `hub.v_material_roles` is a **plain SQL view**, recomputed each query.
  Catalog endpoints (`/v1/hub/materials*`) → realtime, always fresh.
- BCCT `product_identity.observed_roles[]` is **persisted** in the existing
  `hub.bcct_rows.product_identity` jsonb column at ingest time (consistent
  with BCCT identity feature D9 snapshot semantics). Lazy-fill at read for
  legacy NULL rows. Backfill via `scripts/resolve_bcct_product_identity.py
  --recompute` if needed.

## Consumer guidance

### CO (origin sheet calculation)

Existing logic on `bom_product_code` keeps working — it's a conditional
alias: set when `product_kind='tp'` (or any kind with `has_own_bom=true`).

Add an optional check: if `is_multi_role=true` for a TP, surface a warning
to the operator ("this code may be rework — confirm origin context before
locking sheet").

```python
if pid["resolution_status"] == "resolved" and pid["product_kind"] == "tp":
    if pid["is_multi_role"]:
        warn("multi-role TP — verify rework context")
    bom = data_hub.list_bom_artifacts(pid["bom_product_code"])
    # ... origin sheet calc
```

### BCQT (settlement quantity allocation)

Use `observed_roles[]` + `direction` + `btp_sourcing` together:

```python
def role_for_line(pid, direction):
    """Infer per-BCCT-line role from product_identity + direction."""
    obs = set(pid["observed_roles"])
    sourcing = pid["btp_sourcing"]

    # Export rows: line role = 'tp' production (regardless of obs roles).
    if direction == "export":
        return "tp_production"

    # Import rows: differentiate NVL consumption vs BTP-purchased input.
    if direction == "import":
        if sourcing in ("purchased_only", "dual_source"):
            return "btp_purchased_input"
        # No btp_sourcing signal — fall back to observed.
        if "btp_sx" in obs:
            return "btp_consumed_input"
        return "nvl_consumption"

    return "unknown"
```

Replace BCQT's homegrown `internal_code` parser entirely:
- Drop goods_name regex copies in BCQT codebase.
- Read `pid["resolved_code"]` for canonical material identity per BCCT line.
- Read `pid["product_kind"]` + `pid["observed_roles"]` + `pid["btp_sourcing"]`
  + `direction` for role inference per line.

## Auth

`hub:read` scope. Same auth pattern as other read endpoints — service
token or user JWT.

## Idempotency / cache TTL

- Catalog endpoints: realtime view, no cache TTL on Data Hub side.
  Consumer cache TTL: ≤30s OK (data is per-client per-customs-code,
  rarely changes during active session).
- BCCT `product_identity`: persisted snapshot. Same query against
  unchanged BCCT/material/BOM data returns identical result. Re-resolve
  triggered by ingest or backfill script.

## Migration steps for sister apps

### CO

1. Update `app/data_hub_client.py` to surface new top-level fields on
   `list_bcct()` + `invoice_matches()` items. Just preserve unknown JSON
   keys; no special parsing needed.
2. (Optional) Add `is_multi_role` check before loading BOM — operator
   warning UI.
3. (Optional) Add `declared_observed_conflict` check — log to integrity
   dashboard for staff review.

No removal of existing CO logic — `bom_product_code` alias works as before.

### BCQT

1. Add `data_hub_client.py` consumer for the role fields.
2. Implement `role_for_line()` helper above.
3. In settlement quantity-allocation pass: index BCCT rows by
   `resolved_code` and use `role_for_line()` to bucket consumption type.
4. Deprecate any goods_name regex parsing in BCQT codebase.
5. Tests: pin BCQT settlement output unchanged after migration (parity
   check vs current homegrown parser).

## Known gaps / out of scope

- Operator override write API for `bcct_product_identity_review` deferred
  to future PR.
- Phase 3a `btp_sourcing` scope expansion (covering declared-nvl codes that
  are structurally purchased BTPs) — backlog.
- Materialized view promotion if catalog endpoint p95 > 500ms — backlog.
- Lazy re-validation of persisted `resolved` rows on BOM tombstone —
  backlog (R2 of BCCT identity brief).
- For non-DNCX clients (regular SX domestic / commercial trade), A12
  may carry NVL semantics — current `has_nvl_import` filter is
  DNCX/DNSXXK-tuned (E-series only). Per-client declaration_type
  whitelist override → backlog.

## Real-data resolution rate (post mig 034 + BOM-only fallback)

Growatt (23,080 BCCT rows): 22,333 resolved (96.8%), 735 missing,
10 unverified, 2 ambiguous.

Counts vs the original commit-4 contract:
- +133 resolved (BOM-only fallback restored 17 paren-extracted codes
  like `PV01.0117500` that have BOMs but no materials registry entry).
- +228 NVL observed (mig 034 relax: codes with E11/E15 imports are now
  classified without waiting for BOM consumption signal).

## Contact

Issues / questions on the contract: file a note back to
`~/workspace/client/data-hub/.ai/sister-app-notes/` with a date-prefixed
filename, or ping in shared Slack.
