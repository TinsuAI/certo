"""Catalog (hub.materials) provenance helpers.

Post-mig-042: provenance signals are now first-class columns on `materials`.

- `materials.source` enum: client_declared / bcct_observed / bom_observed / system
- `materials.hq_registered` boolean
- `materials.observed_count`, observed_first_at, observed_last_at,
  observed_directions[] — derived live via `v_material_roles` view
  (never stored on materials per memory `feedback_no_derived_in_source.md`).

Audit-only keys still in `materials.provenance` jsonb:
- `btp_inferred` — Phase 3 BTP roster bootstrap audit.
- `registered_with_hq` sub-keys (first_seen, source_upload_id) — registration audit detail.

The `seen_in_bcct` jsonb key (which used to cache stale counts) was dropped
in mig 042 — its data is now provided live by v_material_roles.
"""
from __future__ import annotations

from typing import Iterable


_DERIVE_FROM_BCCT_SQL = """
    insert into hub.materials
      (client_id, material_code, name, category, status, source, provenance)
    select %s, customs_code,
           max(goods_name),
           'nvl',
           'active',
           'bcct_observed',
           '{}'::jsonb
    from hub.bcct_rows
    where client_id = %s
      and customs_code is not null and customs_code <> ''
      and customs_code = any(%s)
    group by customs_code
    on conflict (client_id, material_code) do update set
      -- Re-running derive on already-existing rows: keep their source/status.
      -- Observation stats (count, first_seen, last_seen) come from v_material_roles
      -- view live; no jsonb merge needed anymore.
      updated_at = now()
"""


def derive_from_bcct(cur, *, client_id: str, customs_codes: Iterable[str]) -> int:
    """Auto-derive catalog rows from a batch of just-applied BCCT codes.

    Called inside the same transaction as `_apply_bcct_rows` so the
    insert/update can read the freshly-inserted rows.

    Default category for auto-derived rows = 'nvl'. Staff can re-categorize
    in the catalog UI later. New rows get `source='bcct_observed'`,
    `status='active'`. Observation stats come from `v_material_roles` view.

    Returns the number of distinct customs_codes processed (for logging).
    """
    codes = [c.strip() for c in customs_codes if c and isinstance(c, str) and c.strip()]
    if not codes:
        return 0
    cur.execute(_DERIVE_FROM_BCCT_SQL, (client_id, client_id, codes))
    return len(set(codes))


def unregistered_seen_count(cur, *, client_id: str) -> int:
    """Count of material_codes that appear on declarations but haven't
    been registered with HQ. Drives the catalog audit alarm.

    Post-mig-042: source='bcct_observed' replaces `provenance ? 'seen_in_bcct'`.
    `hq_registered=true` replaces `provenance ? 'registered_with_hq'`.
    """
    cur.execute(
        """
        select count(*) from hub.materials
        where client_id = %s
          and source = 'bcct_observed'
          and (hq_registered is null or hq_registered = false)
        """,
        (client_id,),
    )
    (n,) = cur.fetchone()
    return n


def bom_unresolved_material_count(cur, *, client_id: str) -> int:
    """Count BOM material_codes (from alive versions) that don't resolve
    to any catalog row, even via the BQD (`code_mappings`) translation
    layer.

    Resolution path:
      BOM.material_code
        ↓ direct: matches materials.material_code (catalog membership)
        ↓ via BQD: matches code_mappings.internal_code (DNCX side)

    A code that fails BOTH is genuinely unregistered. For clients
    that use supplier-internal codes in BOM (common — Growatt does this),
    these are EXPECTED holes rather than compliance violations: surface
    the count so staff can decide register-vs-ignore per code, but do
    not auto-derive (would fake HQ provenance).

    BCCT-side gap is tracked separately via `unregistered_seen_count`.

    Note (mig 042): legacy `materials.internal_code` lookup branch was
    removed when that column was dropped (vestigial — held identical
    values to customs_code in 100% of rows).
    """
    cur.execute(
        """
        with bom_codes as (
          select distinct bvr.material_code
          from hub.bom_artifact_rows bvr
          join hub.bom_artifacts bv on bv.artifact_id = bvr.artifact_id
          where bv.client_id = %s and bv.tombstoned_at is null
        )
        select count(*) from bom_codes bc
        where not exists (
          select 1 from hub.materials m
          where m.client_id = %s and m.material_code = bc.material_code
        )
        and not exists (
          select 1 from hub.code_mappings cm
          where cm.client_id = %s and cm.internal_code = bc.material_code
        )
        """,
        (client_id, client_id, client_id),
    )
    (n,) = cur.fetchone()
    return n
