"""Component classification. Decision order per spec §6.

Per spec §7 the engine, not the classifier, decides whether to emit dual
variants. The classifier returns `dual_source=True` when both BCCT-import
evidence and a child BOM exist; the engine then materialises both
variants AND surfaces the dual-source decision for staff confirmation.

Classifier output is order-driven and side-effect-free:

  1. Explicit purchased / imported / 'do not explode' → leaf  (explicit=True)
  2. Explicit self-produced                          → explode (explicit=True)
  3. BCCT import + no child BOM in same/db          → leaf
  4. BCCT import + child BOM exists                  → leaf, dual_source=True
  5. Child BOM in same upload                       → explode
  6. Child BOM in current DB                        → explode
  7. Catalog active imported NVL                    → leaf
  8. Otherwise                                      → unresolved
"""
from __future__ import annotations

from hub.app.flatten.types import (
    BomKey, ClassificationResult, FlattenContext, ParsedRow,
)


def classify_component(
    row: ParsedRow,
    *,
    parent_key: BomKey,
    ctx: FlattenContext,
    same_upload_keys: set[tuple],
) -> ClassificationResult:
    material_code = (row.get("material_code") or "").strip()
    if not material_code:
        return ClassificationResult(
            action="unresolved",
            evidence="classification_unknown",
            detail={"why": "no material_code"},
        )

    # 1 & 2. Explicit row context wins.
    explicit = ctx.explicit_context(row)
    if explicit in ("purchased", "imported", "do_not_explode"):
        return ClassificationResult(
            action="leaf", evidence="explicit_purchased",
            detail={"explicit": explicit}, explicit=True,
        )
    if explicit == "self_produced":
        return ClassificationResult(
            action="explode", evidence="explicit_self_produced",
            detail={"explicit": explicit}, explicit=True,
        )

    has_bcct = bool(ctx.bcct_import(material_code))

    bom_code = str(row.get("bom_code") or "")
    bom_variant_id = str(row.get("bom_variant_id") or "default")
    same_upload_rows = ctx.same_upload_btp(material_code, bom_code, bom_variant_id)
    db_btp_rows = ctx.current_db_btp(material_code, bom_code, bom_variant_id)
    has_child = bool(same_upload_rows) or bool(db_btp_rows)

    # 3 & 4. BCCT import evidence — leaf, with dual-source flag if child
    # BOM also exists.
    if has_bcct:
        return ClassificationResult(
            action="leaf",
            evidence="bcct_import",
            detail={"client_id": ctx.client_id, "material_code": material_code,
                    "child_bom_present": has_child},
            dual_source=has_child,
        )

    # 5. Same-upload child BOM.
    if same_upload_rows:
        return ClassificationResult(
            action="explode",
            evidence="child_bom_same_upload",
            detail={"material_code": material_code,
                    "bom_code": bom_code, "bom_variant_id": bom_variant_id},
        )

    # 6. Current DB child BOM.
    if db_btp_rows:
        return ClassificationResult(
            action="explode",
            evidence="child_bom_current_db",
            detail={"material_code": material_code,
                    "bom_code": bom_code, "bom_variant_id": bom_variant_id},
        )

    # 7. Catalog active imported NVL leaf.
    cat = ctx.catalog(material_code)
    if cat and cat.status == "active" and cat.category == "nvl":
        return ClassificationResult(
            action="leaf",
            evidence="catalog_imported_nvl",
            detail={"category": cat.category, "status": cat.status},
        )

    # 8. Unresolved.
    return ClassificationResult(
        action="unresolved",
        evidence="unresolved_missing_child_bom",
        detail={"material_code": material_code,
                "bom_code": bom_code, "bom_variant_id": bom_variant_id},
    )
