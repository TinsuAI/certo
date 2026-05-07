"""Catalog (hub.materials) provenance helpers.

Three sources are tracked:
- registered_with_hq: agency-declared codes (catalog Excel upload).
- seen_in_bcct: codes that show up on customs declarations. May lag
  HQ registration — these are operational reality, not yet canonical.
- user_added: free-form manual catalog entries (deferred — not in MVP).

Each is a top-level key in materials.provenance jsonb. Presence = signal.
Multiple keys can co-exist on a row (canonical happy path: registered AND
seen on declarations).
"""
from __future__ import annotations

from typing import Iterable


_DERIVE_FROM_BCCT_SQL = """
    insert into hub.materials
      (client_id, customs_code, internal_code, name, category, status, provenance)
    select %s, customs_code,
           customs_code,                  -- internal_code defaults to customs_code
                                          -- so BQD lookups don't break for
                                          -- auto-derived rows; staff can
                                          -- override later in catalog UI.
           max(goods_name),
           'nvl',
           'active',
           jsonb_build_object('seen_in_bcct',
             jsonb_build_object(
               'first_seen', to_char(min(registration_date), 'YYYY-MM-DD'),
               'last_seen',  to_char(max(registration_date), 'YYYY-MM-DD'),
               'decl_count', count(distinct declaration_no)::int))
    from hub.bcct_rows
    where client_id = %s
      and customs_code is not null and customs_code <> ''
      and customs_code = any(%s)
    group by customs_code
    on conflict (client_id, customs_code) do update set
      -- Merge new seen_in_bcct (with refreshed last_seen + decl_count) onto
      -- whatever provenance keys are already there (registered_with_hq, etc).
      provenance = hub.materials.provenance ||
                   jsonb_build_object('seen_in_bcct',
                     excluded.provenance->'seen_in_bcct'),
      updated_at = now()
"""


def derive_from_bcct(cur, *, client_id: str, customs_codes: Iterable[str]) -> int:
    """Auto-derive catalog rows from a batch of just-applied BCCT codes.

    Called inside the same transaction as `_apply_bcct_rows` so the
    insert/update can read the freshly-inserted rows (must run AFTER the
    BCCT insert, before the connection closes).

    Default category for auto-derived rows = 'nvl'. Staff can re-categorize
    in the catalog UI later. Provenance signal is independent of category.

    Returns the number of distinct customs_codes processed (for logging).
    """
    codes = [c.strip() for c in customs_codes if c and isinstance(c, str) and c.strip()]
    if not codes:
        return 0
    cur.execute(_DERIVE_FROM_BCCT_SQL, (client_id, client_id, codes))
    return len(set(codes))


def unregistered_seen_count(cur, *, client_id: str) -> int:
    """Count of customs_codes that appear on declarations but haven't
    been registered with HQ. Drives the catalog audit alarm."""
    cur.execute(
        """
        select count(*) from hub.materials
        where client_id = %s
          and provenance ? 'seen_in_bcct'
          and not (provenance ? 'registered_with_hq')
        """,
        (client_id,),
    )
    (n,) = cur.fetchone()
    return n


def bom_unresolved_material_count(cur, *, client_id: str) -> int:
    """Count BOM material_codes (from alive versions) that don't resolve
    to any catalog row, even via the BQD (`code_mappings`) translation
    layer.

    Resolution path the agency workflow expects:
      BOM.material_code (typically internal_code)
        ↓ direct: matches materials.customs_code (identity-mode clients)
        ↓ direct: matches materials.internal_code
        ↓ via BQD: matches code_mappings.internal_code → customs_code
                   → materials.customs_code

    A code that fails ALL three is genuinely unregistered. For clients
    that use supplier-internal codes in BOM (common — Growatt does this),
    these are EXPECTED holes rather than compliance violations: surface
    the count so staff can decide register-vs-ignore per code, but do
    not auto-derive (would fake HQ provenance).

    BCCT-side gap is tracked separately via `unregistered_seen_count`.
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
          where m.client_id = %s and m.customs_code = bc.material_code
        )
        and not exists (
          select 1 from hub.materials m
          where m.client_id = %s and m.internal_code = bc.material_code
        )
        and not exists (
          select 1 from hub.code_mappings cm
          where cm.client_id = %s and cm.internal_code = bc.material_code
        )
        """,
        (client_id, client_id, client_id, client_id),
    )
    (n,) = cur.fetchone()
    return n
