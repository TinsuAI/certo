"""Flatten orchestrator. Pure: takes parsed BOM + injected lookups,
returns a FlattenResult that the stores layer materializes.

Algorithm (TP-by-TP):
  1. Build set of same-upload graph_keys so explode can prefer same-upload BTP.
  2. For each graph_key in parsed:
       Resolve a single FlattenedVersion via DFS, multiplying qty along the
       path; convert UOM at each hop into the canonical from catalog.
       - leaf  → emit FlattenedRow.
       - explode → recurse into child rows; same-upload BTP wins over DB BTP.
       - unresolved → emit UnresolvedNode; branch contributes nothing to qty.
       - dual_source → emit BOTH the purchased-leaf row AND an exploded
         sub-version draft, then fan out: parent gets one variant per
         dual-source decision combo. For MVP we emit two parent variants
         per dual-source occurrence (purchased_btp_as_leaf vs
         self_produced_btp_exploded). If multiple dual-sources occur in
         one TP we still emit only the two pure-strategy variants
         (mixed_confirmed left to staff via decision).
  3. Decisions are accumulated globally (deduped by decision_type+target+evidence).
  4. Cycle detection prevents infinite recursion; cycle-affected branches
     surface as UnresolvedNode(reason='cycle_detected').
"""
from __future__ import annotations

import dataclasses
import secrets
from decimal import Decimal
from typing import Iterable

from app.flatten.classify import classify_component
from app.flatten.types import (
    BomKey, ClassificationResult, Decision, FlattenContext, FlattenResult,
    FlattenedRow, FlattenedVersion, ParsedBom, ParsedRow, UnresolvedNode,
)
from app.flatten.uom import convert_qty


def _decision_id() -> str:
    return "dec_" + secrets.token_urlsafe(10)


def _key_from_rows(product_code: str, rows: list[ParsedRow]) -> BomKey:
    if not rows:
        return BomKey(product_code=product_code)
    first = rows[0]
    return BomKey(
        product_code=product_code,
        bom_code=str(first.get("bom_code") or ""),
        bom_variant_id=str(first.get("bom_variant_id") or "default"),
    )


def _qty_decimal(v) -> Decimal:
    if v is None or v == "":
        return Decimal(0)
    if isinstance(v, Decimal):
        return v
    return Decimal(str(v))


def flatten(parsed: ParsedBom, ctx: FlattenContext) -> FlattenResult:
    """Entry point. See module docstring."""
    same_upload_keys: set[tuple] = set()
    for pc, rows in parsed.items():
        same_upload_keys.add(_key_from_rows(pc, rows).as_tuple())

    # Spec §8: parsed dict IS the same upload — consult it before falling
    # back to whatever ctx.same_upload_btp brings (additional same-upload
    # sources). This wrapper makes the precedence automatic.
    parsed_lookup_original = ctx.same_upload_btp

    def wrapped_same_upload(material_code: str, bom_code: str,
                            bom_variant_id: str) -> list[ParsedRow] | None:
        rows = parsed.get(material_code)
        if rows:
            first = rows[0]
            row_bom_code = str(first.get("bom_code") or "")
            row_variant = str(first.get("bom_variant_id") or "default")
            # Strict variant equality (per /rev finding C3): treat
            # `default` as a real variant, never a wildcard. Caller
            # passing "" means "no variant requested" → match anything;
            # caller passing a specific variant must match exactly.
            bom_code_match = (bom_code == "" or bom_code == row_bom_code)
            variant_match = (bom_variant_id == "" or bom_variant_id == row_variant)
            if bom_code_match and variant_match:
                return rows
        return parsed_lookup_original(material_code, bom_code, bom_variant_id)

    ctx = dataclasses.replace(ctx, same_upload_btp=wrapped_same_upload)

    versions: list[FlattenedVersion] = []
    decisions_by_id: dict[str, Decision] = {}

    def emit_decision(d: Decision) -> str:
        # Dedup by (type, target_key, target_strategy, chosen_action).
        sig = (
            d.decision_type,
            d.target_key.as_tuple() if d.target_key else None,
            d.target_strategy,
            d.chosen_action,
        )
        for did, existing in decisions_by_id.items():
            esig = (
                existing.decision_type,
                existing.target_key.as_tuple() if existing.target_key else None,
                existing.target_strategy,
                existing.chosen_action,
            )
            if esig == sig:
                return did
        new_id = _decision_id()
        decisions_by_id[new_id] = d
        return new_id

    for product_code, rows in parsed.items():
        if not rows:
            continue
        key = _key_from_rows(product_code, rows)
        # For each TP/BTP we generate at least one variant. Dual-source
        # forks happen inside _flatten_one.
        produced = _flatten_one(
            key=key, rows=rows, ctx=ctx,
            same_upload_keys=same_upload_keys,
            parsed=parsed, emit_decision=emit_decision,
        )
        versions.extend(produced)

    return FlattenResult(versions=versions,
                         decisions=list(decisions_by_id.values()))


def _flatten_one(
    *, key: BomKey, rows: list[ParsedRow], ctx: FlattenContext,
    same_upload_keys: set[tuple], parsed: ParsedBom,
    emit_decision,
) -> list[FlattenedVersion]:
    """Produce 1 or 2 FlattenedVersion drafts for a single graph_key.

    Two are produced ONLY when at least one component has dual_source=True
    AND `chose_explode` and `chose_leaf` both yield differing row sets.
    For simplicity in MVP, dual_source produces exactly two variants per TP
    that contains any dual_source occurrence:
      - purchased_btp_as_leaf  (every dual_source treated as leaf)
      - self_produced_btp_exploded (every dual_source treated as explode)
    Future enhancement: per-component variant fan-out via mixed_confirmed.
    """
    # Pass 1: classify each row to know whether dual_source occurs.
    classifications: list[tuple[ParsedRow, ClassificationResult]] = []
    has_dual = False
    for row in rows:
        cls = classify_component(
            row, parent_key=key, ctx=ctx, same_upload_keys=same_upload_keys,
        )
        if cls.dual_source:
            has_dual = True
        classifications.append((row, cls))

    if not has_dual:
        return [_resolve_version(
            key=key, rows=rows, classifications=classifications,
            ctx=ctx, same_upload_keys=same_upload_keys,
            parsed=parsed, dual_treatment=None,
            emit_decision=emit_decision,
        )]

    # Dual-source fan-out: emit both variants.
    # Spec §7: "Do not overwrite or merge these variants. Store separate
    # versions/variants with explicit flatten_strategy and provenance.
    # Preview must show the dual-source branch and require staff to
    # confirm which variant(s) to publish."
    purchased = _resolve_version(
        key=key, rows=rows, classifications=classifications,
        ctx=ctx, same_upload_keys=same_upload_keys,
        parsed=parsed, dual_treatment="leaf",
        emit_decision=emit_decision,
    )
    exploded = _resolve_version(
        key=key, rows=rows, classifications=classifications,
        ctx=ctx, same_upload_keys=same_upload_keys,
        parsed=parsed, dual_treatment="explode",
        emit_decision=emit_decision,
    )
    # One dual_source_variant decision per dual-source component;
    # staff_confirmation_required.
    for row, cls in classifications:
        if not cls.dual_source:
            continue
        emit_decision(Decision(
            decision_type="dual_source_variant",
            chosen_action="publish_both",   # default offer; staff may choose
            alternatives=[
                {"strategy": "purchased_btp_as_leaf"},
                {"strategy": "self_produced_btp_exploded"},
                {"strategy": "publish_both"},
            ],
            evidence={
                "component": row.get("material_code"),
                "classification_evidence": cls.evidence,
                "detail": cls.detail,
            },
            status="pending",
            staff_confirmation_required=True,
            target_key=key,
        ))
    # Also emit a `bcct_import_vs_child_bom` decision (spec §11) since
    # BCCT-import-vs-child-BOM is the canonical dual_source case.
    for row, cls in classifications:
        if not cls.dual_source or cls.evidence != "bcct_import":
            continue
        emit_decision(Decision(
            decision_type="bcct_import_vs_child_bom",
            chosen_action="prefer_purchased",
            alternatives=[
                {"action": "prefer_purchased"},
                {"action": "prefer_self_produced"},
                {"action": "publish_both"},
            ],
            evidence={
                "component": row.get("material_code"),
                "client_id": ctx.client_id,
            },
            status="pending",
            staff_confirmation_required=True,
            target_key=key,
        ))
    return [purchased, exploded]


def _resolve_version(
    *, key: BomKey, rows: list[ParsedRow],
    classifications: list[tuple[ParsedRow, ClassificationResult]],
    ctx: FlattenContext, same_upload_keys: set[tuple],
    parsed: ParsedBom, dual_treatment: str | None,
    emit_decision,
) -> FlattenedVersion:
    """Compute one FlattenedVersion. dual_treatment in {None, 'leaf', 'explode'}
    governs how dual_source components are resolved.
    """
    out_rows: list[FlattenedRow] = []
    unresolved: list[UnresolvedNode] = []
    btp_used: list[dict] = []

    has_unresolved = False
    has_explode = False
    has_dual_used = False

    for row, cls in classifications:
        action = cls.action
        if cls.dual_source and dual_treatment is not None:
            action = "leaf" if dual_treatment == "leaf" else "explode"
            has_dual_used = True

        material_code = (row.get("material_code") or "").strip()
        path_root = key.product_code

        if action == "unresolved":
            has_unresolved = True
            unresolved.append(UnresolvedNode(
                node_path=f"{path_root}>{material_code}",
                material_code=material_code,
                reason="missing_child_bom" if cls.evidence == "unresolved_missing_child_bom"
                       else "classification_unknown",
                evidence={"classification_evidence": cls.evidence,
                          "detail": cls.detail},
            ))
            continue

        if action == "leaf":
            row_qty = _qty_decimal(row.get("qty_per_unit"))
            row_uom = row.get("uom")
            cat = ctx.catalog(material_code)
            canon_uom = cat.unit if cat and cat.unit else row_uom
            converted, conv_match, conv_err = convert_qty(
                row_qty, row_uom, canon_uom,
                material_code=material_code, lookup=ctx.uom,
            )
            if conv_err == "uom_conversion_missing":
                has_unresolved = True
                unresolved.append(UnresolvedNode(
                    node_path=f"{path_root}>{material_code}",
                    material_code=material_code,
                    reason="uom_conversion_missing",
                    evidence={"from_uom": row_uom, "to_uom": canon_uom},
                ))
                continue
            if conv_err == "canonical_uom_missing":
                emit_decision(Decision(
                    decision_type="catalog_canonical_uom_missing",
                    chosen_action="proceed_with_source_uom",
                    alternatives=[{"action": "proceed_with_source_uom"},
                                  {"action": "block"}],
                    evidence={"material_code": material_code,
                              "source_uom": row_uom},
                    status="pending",
                    staff_confirmation_required=True,
                    target_key=key,
                ))
            if conv_match and conv_match.source == "global":
                emit_decision(Decision(
                    decision_type="global_uom_conversion",
                    chosen_action="apply_global",
                    alternatives=[{"action": "apply_global"},
                                  {"action": "block_until_client_specific"}],
                    evidence={"material_code": material_code,
                              "from_uom": row_uom, "to_uom": canon_uom,
                              "factor": str(conv_match.factor)},
                    status="pending",
                    staff_confirmation_required=True,
                    target_key=key,
                ))
            elif conv_match and conv_match.source in ("client_wide",) \
                    and conv_match.factor != Decimal(1):
                emit_decision(Decision(
                    decision_type="non_alias_uom_conversion",
                    chosen_action="apply",
                    alternatives=[{"action": "apply"}, {"action": "block"}],
                    evidence={"material_code": material_code,
                              "from_uom": row_uom, "to_uom": canon_uom,
                              "factor": str(conv_match.factor),
                              "source": conv_match.source},
                    status="pending",
                    staff_confirmation_required=True,
                    target_key=key,
                ))
            out_rows.append(FlattenedRow(
                material_code=material_code,
                qty=converted if converted is not None else row_qty,
                uom=canon_uom or row_uom or "",
                node_path=f"{path_root}>{material_code}",
                classification_evidence=cls.evidence,
                classification_evidence_detail=cls.detail,
                conversion_evidence=conv_match.as_evidence() if conv_match else None,
                original_qty=row_qty,
                original_uom=row_uom,
            ))
            continue

        # action == 'explode'
        has_explode = True
        # Same-upload first, DB second.
        bom_code = str(row.get("bom_code") or "")
        bom_variant_id = str(row.get("bom_variant_id") or "default")
        child_rows = ctx.same_upload_btp(material_code, bom_code, bom_variant_id)
        used_db_btp = False
        if not child_rows:
            child_rows = ctx.current_db_btp(material_code, bom_code, bom_variant_id)
            used_db_btp = bool(child_rows)
        if not child_rows:
            has_unresolved = True
            unresolved.append(UnresolvedNode(
                node_path=f"{path_root}>{material_code}",
                material_code=material_code,
                reason="missing_child_bom",
                evidence={"classification_evidence": cls.evidence},
            ))
            continue

        if used_db_btp:
            emit_decision(Decision(
                decision_type="use_db_btp_no_same_upload",
                chosen_action="use_db_btp",
                alternatives=[{"action": "use_db_btp"}, {"action": "block"}],
                evidence={"material_code": material_code,
                          "bom_code": bom_code, "bom_variant_id": bom_variant_id},
                status="pending",
                staff_confirmation_required=True,
                target_key=key,
            ))
            btp_used.append({"material_code": material_code,
                             "source": "current_db",
                             "bom_code": bom_code,
                             "bom_variant_id": bom_variant_id})
        else:
            btp_used.append({"material_code": material_code,
                             "source": "same_upload",
                             "bom_code": bom_code,
                             "bom_variant_id": bom_variant_id})

        # Recurse with multiplied quantity.
        parent_qty = _qty_decimal(row.get("qty_per_unit"))
        parent_uom = row.get("uom")
        # The child's own canonical UOM dictates what its leaves' uom is.
        child_unresolved, child_rows_out = _explode(
            child_key=BomKey(product_code=material_code,
                             bom_code=bom_code, bom_variant_id=bom_variant_id),
            child_rows=child_rows,
            parent_qty=parent_qty,
            parent_path=f"{path_root}>{material_code}",
            ctx=ctx, same_upload_keys=same_upload_keys, parsed=parsed,
            visiting={key.product_code},
            emit_decision=emit_decision,
        )
        if child_unresolved:
            has_unresolved = True
        unresolved.extend(child_unresolved)
        out_rows.extend(child_rows_out)

    # Determine version metadata.
    if has_unresolved:
        flatten_status = "non_flattened"
        source_bom_kind = "technical_non_flattened"
    elif has_explode:
        flatten_status = "flattened"
        source_bom_kind = "technical_flattened"
    else:
        # All leaves, no explosion. Either manual_flat shape (caller may
        # short-circuit) or trivially flat technical.
        flatten_status = "flattened"
        source_bom_kind = "technical_flattened"

    # Per /rev finding C2: preserve the dual-treatment strategy even
    # when has_unresolved. Otherwise the strategy would become
    # `no_strategy`, the publish_filter's dual_source_variant gate
    # (which checks `flatten_strategy in (purchased_btp_as_leaf,
    # self_produced_btp_exploded)`) would skip these variants entirely,
    # and staff could publish dual variants without confirming the
    # dual-source decision.
    if dual_treatment == "leaf":
        flatten_strategy = "purchased_btp_as_leaf"
    elif dual_treatment == "explode":
        flatten_strategy = "self_produced_btp_exploded"
    elif has_explode:
        flatten_strategy = "technical_exploded"
    else:
        flatten_strategy = "technical_exploded"

    # Only collapse to no_strategy when no dual treatment was attempted.
    # Dual variants keep their strategy so they remain identifiable.
    if has_unresolved and dual_treatment is None:
        flatten_strategy = "no_strategy"

    requires_decision_ids: list[str] = []
    if flatten_status == "non_flattened":
        did = emit_decision(Decision(
            decision_type="non_flattened_publish",
            chosen_action="block_publish",
            alternatives=[{"action": "block_publish"},
                          {"action": "publish_with_review_required"}],
            evidence={"unresolved_count": len(unresolved),
                      "reasons": sorted({u.reason for u in unresolved})},
            status="pending",
            staff_confirmation_required=True,
            target_key=key,
            target_strategy=flatten_strategy,
        ))
        requires_decision_ids.append(did)

    return FlattenedVersion(
        key=key,
        source_bom_kind=source_bom_kind,
        flatten_status=flatten_status,
        flatten_strategy=flatten_strategy,
        rows=out_rows,
        unresolved=unresolved,
        lineage={"btp_versions_used": btp_used} if btp_used else {},
        requires_decision_ids=requires_decision_ids,
    )


def _explode(
    *, child_key: BomKey, child_rows: list[ParsedRow],
    parent_qty: Decimal, parent_path: str,
    ctx: FlattenContext, same_upload_keys: set[tuple], parsed: ParsedBom,
    visiting: set[str], emit_decision,
) -> tuple[list[UnresolvedNode], list[FlattenedRow]]:
    """Recurse one level deeper. Returns (unresolved, flattened_rows).

    Cycle guard: if child_key.product_code is in `visiting`, emit a single
    UnresolvedNode(reason='cycle_detected') and bail. No further recursion.
    """
    if child_key.product_code in visiting:
        return [UnresolvedNode(
            node_path=f"{parent_path}",
            material_code=child_key.product_code,
            reason="cycle_detected",
            evidence={"path": parent_path},
        )], []

    new_visiting = visiting | {child_key.product_code}
    out_rows: list[FlattenedRow] = []
    unresolved: list[UnresolvedNode] = []

    for grandchild in child_rows:
        gc_mat = (grandchild.get("material_code") or "").strip()
        if not gc_mat:
            continue
        cls = classify_component(
            grandchild, parent_key=child_key, ctx=ctx,
            same_upload_keys=same_upload_keys,
        )
        gc_qty = _qty_decimal(grandchild.get("qty_per_unit"))
        gc_uom = grandchild.get("uom")

        # Per /rev finding I3: dual-source signal at any depth must
        # surface as a staff-confirm decision (spec §7+§11). The TP-level
        # fan-out in _flatten_one only handles top-level dual-source;
        # nested dual-source occurrences need their own emit here. The
        # default action stays "leaf" (matching classify.py rule 4) so
        # the nested branch resolves deterministically — but staff is
        # told via the decision that they may want to revisit.
        if cls.dual_source:
            emit_decision(Decision(
                decision_type="dual_source_variant",
                chosen_action="publish_both",
                alternatives=[
                    {"strategy": "purchased_btp_as_leaf"},
                    {"strategy": "self_produced_btp_exploded"},
                    {"strategy": "publish_both"},
                ],
                evidence={
                    "component": gc_mat,
                    "depth": "nested_in_explode",
                    "parent_path": parent_path,
                    "classification_evidence": cls.evidence,
                },
                status="pending",
                staff_confirmation_required=True,
                target_key=child_key,
            ))
            if cls.evidence == "bcct_import":
                emit_decision(Decision(
                    decision_type="bcct_import_vs_child_bom",
                    chosen_action="prefer_purchased",
                    alternatives=[
                        {"action": "prefer_purchased"},
                        {"action": "prefer_self_produced"},
                        {"action": "publish_both"},
                    ],
                    evidence={"component": gc_mat,
                              "depth": "nested_in_explode",
                              "client_id": ctx.client_id},
                    status="pending",
                    staff_confirmation_required=True,
                    target_key=child_key,
                ))

        if cls.action == "leaf" or (cls.dual_source and cls.action == "leaf"):
            cat = ctx.catalog(gc_mat)
            canon_uom = cat.unit if cat and cat.unit else gc_uom
            converted, conv_match, conv_err = convert_qty(
                gc_qty, gc_uom, canon_uom,
                material_code=gc_mat, lookup=ctx.uom,
            )
            if conv_err == "uom_conversion_missing":
                unresolved.append(UnresolvedNode(
                    node_path=f"{parent_path}>{gc_mat}",
                    material_code=gc_mat,
                    reason="uom_conversion_missing",
                    evidence={"from_uom": gc_uom, "to_uom": canon_uom},
                ))
                continue
            qty_out = (converted if converted is not None else gc_qty) * parent_qty
            out_rows.append(FlattenedRow(
                material_code=gc_mat,
                qty=qty_out,
                uom=canon_uom or gc_uom or "",
                node_path=f"{parent_path}>{gc_mat}",
                classification_evidence=cls.evidence,
                classification_evidence_detail=cls.detail,
                conversion_evidence=conv_match.as_evidence() if conv_match else None,
                original_qty=gc_qty,
                original_uom=gc_uom,
            ))
            continue

        if cls.action == "explode":
            bom_code = str(grandchild.get("bom_code") or "")
            bom_variant_id = str(grandchild.get("bom_variant_id") or "default")
            deeper_rows = ctx.same_upload_btp(gc_mat, bom_code, bom_variant_id)
            if not deeper_rows:
                deeper_rows = ctx.current_db_btp(gc_mat, bom_code, bom_variant_id)
            if not deeper_rows:
                unresolved.append(UnresolvedNode(
                    node_path=f"{parent_path}>{gc_mat}",
                    material_code=gc_mat,
                    reason="missing_child_bom",
                ))
                continue
            sub_unr, sub_rows = _explode(
                child_key=BomKey(product_code=gc_mat,
                                 bom_code=bom_code, bom_variant_id=bom_variant_id),
                child_rows=deeper_rows,
                parent_qty=gc_qty * parent_qty,
                parent_path=f"{parent_path}>{gc_mat}",
                ctx=ctx, same_upload_keys=same_upload_keys, parsed=parsed,
                visiting=new_visiting,
                emit_decision=emit_decision,
            )
            unresolved.extend(sub_unr)
            out_rows.extend(sub_rows)
            continue

        # unresolved
        unresolved.append(UnresolvedNode(
            node_path=f"{parent_path}>{gc_mat}",
            material_code=gc_mat,
            reason="missing_child_bom" if cls.evidence == "unresolved_missing_child_bom"
                   else "classification_unknown",
            evidence={"classification_evidence": cls.evidence},
        ))

    return unresolved, out_rows
