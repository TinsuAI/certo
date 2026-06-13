"""Per-client SAP Material Group → declarability map (mig 078).

The (client_id, material_group) row drives hub.v_material_classification:
`is_declarable=false` marks a group as rác (drawing/document/label). Editing a
row updates the view's `customs_relevance` live; re-tagging the stored
bom_artifact_rows.excluded_at needs the `material_group_backfill` job
(scripts/backfill_johnson_material_group.py --exclusions-only).

`item_category` is the physical-nature descriptor; declarability is the
`is_declarable` boolean (the view keys on it, not on item_category).
"""
from __future__ import annotations

from app.database import connect

# Physical-nature descriptors. Mirrors the seed comment in mig 078 + the
# item_category values used across hub.v_material_classification reasons.
ITEM_CATEGORIES = (
    "drawing", "document", "label", "packaging", "metal", "hardware",
    "plastic", "consumable", "assembly_set", "finished", "other",
)


def list_map(client_id: str) -> list[dict]:
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "select material_group, item_category, is_declarable, source, "
            "       notes, created_at "
            "from hub.client_material_group_map "
            "where client_id = %s order by material_group",
            (client_id,),
        )
        cols = [d[0] for d in cur.description]
        return [dict(zip(cols, r)) for r in cur.fetchall()]


def upsert(*, client_id: str, material_group: str, item_category: str,
           is_declarable: bool, notes: str | None = None,
           source: str = "staff_form") -> None:
    """Insert or update one map row. `material_group` is uppercased + trimmed;
    `item_category` must be one of ITEM_CATEGORIES."""
    material_group = (material_group or "").strip().upper()
    if not material_group:
        raise ValueError("material_group is required")
    if item_category not in ITEM_CATEGORIES:
        raise ValueError(f"invalid item_category: {item_category!r}")
    notes = (notes or "").strip() or None
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "insert into hub.client_material_group_map "
            "  (client_id, material_group, item_category, is_declarable, "
            "   source, notes) "
            "values (%s, %s, %s, %s, %s, %s) "
            "on conflict (client_id, material_group) do update set "
            "  item_category = excluded.item_category, "
            "  is_declarable = excluded.is_declarable, "
            "  source = excluded.source, "
            "  notes = excluded.notes",
            (client_id, material_group, item_category, is_declarable,
             source, notes),
        )


def delete(*, client_id: str, material_group: str) -> None:
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "delete from hub.client_material_group_map "
            "where client_id = %s and material_group = %s",
            (client_id, (material_group or "").strip().upper()),
        )
