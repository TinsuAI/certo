#!/usr/bin/env python
"""Backfill SAP Material Group + non-declarable ("rác") row exclusion for an
existing client's BOM data (migration 078).

Parses the client's SAP technical-BOM workbooks for the per-code
`Material Group` + `Phantom` flag (both intrinsic to the code), then:
  B. UPDATE materials.material_group + catalog_candidates.material_group
  C. merge material_group + phantom into bom_artifact_rows.payload
  D. set excluded_at/exclusion_reason on rows whose material_group maps to
     is_declarable=false (drawing/document/label) OR whose phantom flag is set
  E. one bom_audit_events row per newly-affected artifact

Idempotent (guarded; re-run = 0 changes), scoped to one client, dry-run by
default. The (client_id, material_group) -> declarability map must already be
seeded in hub.client_material_group_map (migration 078).

Usage:
    uv run python scripts/backfill_johnson_material_group.py            # dry-run
    uv run python scripts/backfill_johnson_material_group.py --apply
    uv run python scripts/backfill_johnson_material_group.py --client johnson-vn \
        --source-dir "data/source_inventory/johnson-vn/2026-05-07-updated/Johnson/TECHNICAL BOM - JOHNSON"

Run against the native/local-socket data_hub instance (see
reference_dev_db_topology), then sync.
"""
from __future__ import annotations

import argparse
import glob
import os
import sys

from app.database import connect

DEFAULT_CLIENT = "johnson-vn"
DEFAULT_SOURCE_DIR = (
    "data/source_inventory/johnson-vn/2026-05-07-updated/"
    "Johnson/TECHNICAL BOM - JOHNSON"
)
ACTOR = "backfill_material_group"

# Column header prefixes (lowercased) — tolerant of SAP export variants.
_COLS = {
    "level": "level",
    "component": "component number",
    "desc": "object desc",
    "mg": "material group",
    "phantom": "phantom",
}


def _colmap(header: list[str]) -> dict[str, int]:
    out: dict[str, int] = {}
    norm = [str(h or "").strip().lower() for h in header]
    for key, prefix in _COLS.items():
        for i, h in enumerate(norm):
            if h.startswith(prefix):
                out[key] = i
                break
    return out


def parse_code_info(source_dir: str) -> dict[str, dict]:
    """Parse every workbook → {code: {material_group, phantom}}.

    Material Group is intrinsic per code; abort on any conflict.
    """
    import openpyxl

    files = sorted(
        glob.glob(os.path.join(source_dir, "*.XLSX"))
        + glob.glob(os.path.join(source_dir, "*.xlsx"))
    )
    if not files:
        sys.exit(f"No .xlsx files under {source_dir!r}")

    info: dict[str, dict] = {}
    conflicts: list[str] = []
    for f in files:
        try:
            wb = openpyxl.load_workbook(f, read_only=True, data_only=True)
            rows = list(wb.worksheets[0].iter_rows(values_only=True))
            wb.close()
        except Exception as e:  # noqa: BLE001
            print(f"  WARN skip {os.path.basename(f)}: {e}")
            continue
        if not rows or len(rows) < 2:
            continue
        cm = _colmap([str(c or "") for c in rows[0]])
        if "component" not in cm or "mg" not in cm:
            print(f"  WARN no MG/component cols: {os.path.basename(f)}")
            continue
        for r in rows[1:]:
            if not r or cm["component"] >= len(r):
                continue
            code = r[cm["component"]]
            if code in (None, ""):
                continue
            code = str(code).strip()
            mg = (str(r[cm["mg"]]).strip()
                  if cm.get("mg") is not None and cm["mg"] < len(r)
                  and r[cm["mg"]] not in (None, "") else None)
            phantom = (
                cm.get("phantom") is not None and cm["phantom"] < len(r)
                and str(r[cm["phantom"]] or "").strip().upper() == "X"
            )
            if not mg:
                continue
            if code not in info:
                info[code] = {"material_group": mg, "phantom": phantom}
            else:
                if info[code]["material_group"] != mg:
                    conflicts.append(
                        f"{code}: {info[code]['material_group']} vs {mg}")
                # phantom: sticky-true (a code phantom anywhere is phantom)
                info[code]["phantom"] = info[code]["phantom"] or phantom

    if conflicts:
        for c in conflicts[:20]:
            print(f"  CONFLICT {c}")
        sys.exit(f"ABORT: {len(conflicts)} material_group conflicts; "
                 "Material Group must be consistent per code.")
    return info


def run(client: str, source_dir: str, apply: bool) -> int:
    print(f"== Backfill material_group — client={client} apply={apply} ==")
    print(f"Phase A: parsing {source_dir} ...")
    info = parse_code_info(source_dir)
    print(f"  {len(info)} distinct codes with a Material Group "
          f"({sum(1 for v in info.values() if v['phantom'])} phantom).")

    items = [(c, v["material_group"], v["phantom"]) for c, v in info.items()]

    with connect() as conn:
        with conn.cursor() as cur:
            # Verify the client map is seeded (else everything would be 'review'
            # and nothing would be excluded — fail loudly rather than no-op).
            cur.execute(
                "select count(*) from hub.client_material_group_map "
                "where client_id=%s", (client,))
            n_map = cur.fetchone()[0]
            if n_map == 0:
                sys.exit(f"ABORT: hub.client_material_group_map empty for "
                         f"{client}; seed it first (migration 078).")
            print(f"  client_material_group_map rows: {n_map}")

            cur.execute(
                "create temp table _mg (code text primary key, "
                "material_group text not null, phantom boolean not null) "
                "on commit drop")
            cur.executemany(
                "insert into _mg (code, material_group, phantom) "
                "values (%s, %s, %s)", items)

            # Phase B — materials + catalog_candidates (idempotent guard).
            cur.execute(
                "update hub.materials m set material_group = g.material_group "
                "from _mg g where m.client_id=%s and m.material_code=g.code "
                "and m.material_group is distinct from g.material_group",
                (client,))
            print(f"Phase B: materials.material_group updated: {cur.rowcount}")
            cur.execute(
                "update hub.catalog_candidates c "
                "set material_group = g.material_group "
                "from _mg g where c.client_id=%s and c.code=g.code "
                "and c.material_group is distinct from g.material_group",
                (client,))
            print(f"         catalog_candidates.material_group updated: "
                  f"{cur.rowcount}")

            # Phase C — merge into bom_artifact_rows.payload (johnson artifacts
            # only; guard on material_group so re-run is a no-op).
            cur.execute(
                "update hub.bom_artifact_rows r "
                "set payload = r.payload "
                "  || jsonb_build_object('material_group', g.material_group, "
                "                        'phantom', g.phantom) "
                "from _mg g, hub.bom_artifacts a "
                "where a.artifact_id = r.artifact_id and a.client_id=%s "
                "  and r.material_code = g.code "
                "  and coalesce(r.payload->>'material_group','') "
                "      is distinct from g.material_group",
                (client,))
            print(f"Phase C: bom_artifact_rows.payload updated: {cur.rowcount}")

            # Phase D — materialize the exclusion FROM the canonical view
            # (hub.v_material_classification). Set + clear so the backfill is
            # re-runnable and map/view edits propagate (a code reclassified out
            # of 'excluded_non_material' gets un-excluded on the next run). The
            # view's import-aware logic means imported materials are never
            # excluded here (mig 079).
            # D1 — exclude (and (re)label) rows the view marks
            # excluded_non_material. Re-labels stale reasons so the row's reason
            # always reflects its current item_category (idempotent).
            cur.execute(
                "update hub.bom_artifact_rows r "
                "set excluded_at = coalesce(r.excluded_at, now()), "
                "    exclusion_reason = 'rac:' || v.item_category "
                "from hub.bom_artifacts a, hub.v_material_classification v "
                "where r.artifact_id = a.artifact_id and a.client_id=%s "
                "  and v.client_id = a.client_id and v.material_code = r.material_code "
                "  and v.customs_relevance = 'excluded_non_material' "
                "  and (r.excluded_at is null "
                "       or r.exclusion_reason is distinct from 'rac:' || v.item_category)",
                (client,))
            print(f"Phase D1: rows excluded/relabeled (excluded_non_material): {cur.rowcount}")

            # D2 — exclude (and (re)label) phantom rows that are NOT already an
            # excluded_non_material type (independent axis; not in the view).
            cur.execute(
                "update hub.bom_artifact_rows r "
                "set excluded_at = coalesce(r.excluded_at, now()), "
                "    exclusion_reason = 'rac:phantom' "
                "from hub.bom_artifacts a "
                "where r.artifact_id = a.artifact_id and a.client_id=%s "
                "  and (r.payload->>'phantom') = 'true' "
                "  and (r.excluded_at is null "
                "       or r.exclusion_reason is distinct from 'rac:phantom') "
                # Skip phantoms that are excluded_non_material (D1 labels those)
                # AND skip imported phantoms ('declarable' — import wins over the
                # phantom structural flag; an imported unit is a real material).
                "  and not exists ("
                "    select 1 from hub.v_material_classification v "
                "    where v.client_id = a.client_id and v.material_code = r.material_code "
                "      and v.customs_relevance in ('excluded_non_material','declarable'))",
                (client,))
            print(f"Phase D2: rows excluded/relabeled (phantom): {cur.rowcount}")

            # D3 — CLEAR stale exclusions: rows previously excluded that the view
            # no longer marks excluded_non_material AND are not phantom. This is
            # what makes a map/view edit (e.g. RD07 un-rác, or import-aware
            # rescue) actually propagate to already-materialized rows.
            # A row stays excluded iff excluded_non_material OR (phantom AND not
            # imported). Clear everything else — including imported phantoms
            # (now 'declarable') and RD07 sets/drawings (now declarable_unmatched).
            cur.execute(
                "update hub.bom_artifact_rows r "
                "set excluded_at = null, exclusion_reason = null "
                "from hub.bom_artifacts a "
                "where r.artifact_id = a.artifact_id and a.client_id=%s "
                "  and r.excluded_at is not null "
                "  and not exists ("
                "    select 1 from hub.v_material_classification v "
                "    where v.client_id = a.client_id and v.material_code = r.material_code "
                "      and v.customs_relevance = 'excluded_non_material') "
                "  and ( (r.payload->>'phantom') is distinct from 'true' "
                "        or exists ("
                "          select 1 from hub.v_material_classification v "
                "          where v.client_id = a.client_id and v.material_code = r.material_code "
                "            and v.customs_relevance = 'declarable') )",
                (client,))
            print(f"Phase D3: stale exclusions cleared: {cur.rowcount}")

            # Phase E — one audit event per artifact not yet audited.
            cur.execute(
                "insert into hub.bom_audit_events "
                "  (client_id, product_code, artifact_id, event_type, actor, details) "
                "select a.client_id, a.product_code, r.artifact_id, "
                "       'rows.excluded', %s, "
                "       jsonb_build_object('n_excluded', count(*), "
                "         'reasons', jsonb_agg(distinct r.exclusion_reason)) "
                "from hub.bom_artifact_rows r "
                "join hub.bom_artifacts a on a.artifact_id = r.artifact_id "
                "where a.client_id=%s and r.excluded_at is not null "
                "  and not exists (select 1 from hub.bom_audit_events e "
                "                  where e.artifact_id = r.artifact_id "
                "                    and e.event_type='rows.excluded') "
                "group by a.client_id, a.product_code, r.artifact_id",
                (ACTOR, client))
            print(f"Phase E: audit events inserted: {cur.rowcount}")

            # Reporting: exclusion split by item_category, live vs tombstoned.
            cur.execute(
                "select coalesce(r.exclusion_reason,'(none)'), "
                "       (a.tombstoned_at is null) as live, count(*) "
                "from hub.bom_artifact_rows r "
                "join hub.bom_artifacts a on a.artifact_id=r.artifact_id "
                "where a.client_id=%s and r.excluded_at is not null "
                "group by 1,2 order by 1,2", (client,))
            print("  excluded rows by reason (reason | live | n):")
            for reason, live, n in cur.fetchall():
                print(f"    {reason:24} live={live!s:5} {n}")

        if apply:
            conn.commit()
            print("== COMMITTED ==")
        else:
            conn.rollback()
            print("== DRY-RUN (rolled back; re-run with --apply) ==")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n", 1)[0])
    ap.add_argument("--client", default=DEFAULT_CLIENT)
    ap.add_argument("--source-dir", default=DEFAULT_SOURCE_DIR)
    ap.add_argument("--apply", action="store_true",
                    help="write changes (default: dry-run)")
    args = ap.parse_args()
    return run(args.client, args.source_dir, args.apply)


if __name__ == "__main__":
    raise SystemExit(main())
