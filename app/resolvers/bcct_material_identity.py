"""BCCT canonical product/material identity resolver.

Brief: .ai/features/2026-05-07-bcct-product-identity/brief.md
(amended 2026-05-07: generalized from BOM-only → full materials catalog
to serve BCQT NVL/import use cases too).

Resolves which Data Hub canonical material/product (any kind: TP, BTP,
NVL, CCDC) a given BCCT line refers to. Returns the contract shape
consumed by CO via `/v1/hub/bcct` and `/v1/hub/bcct/invoice-matches`
(additive `material_identity` field).

Output shape:
  - `resolved_code`     : canonical hub.materials.customs_code (new — any kind)
  - `bom_product_code`  : alias of resolved_code, ONLY set when the resolved
                          material has alive BOM artifact (preserves CO's
                          original "load BOM if non-null" logic)
  - `product_kind`      : tp | btp_sx | btp_nm | nvl | ccdc | unknown
  - `bom_artifact_count`: candidates carry this so consumers can tell
                          BOM-backed codes apart from leaf NVL.

Stages (D2):
  1. structured_field         — customs_code exists in hub.materials (master registry)
  2. goods_name_embedded_code — client adapter parses paren codes; validate vs materials
  3. reviewed_line_mapping    — operator-reviewed mapping in bcct_material_identity_review
  4. code_mapping_candidate   — code_mappings rows produce CANDIDATES ONLY (never resolves)
  5. missing                  — no evidence

`ResolverContext` carries memoized per-request state (Q5):
  material_catalog:    dict[customs_code, dict]   — full per-client materials roster
  code_mappings:       dict[str, list[dict]]      — keyed by customs_code AND internal_code
  reviewed:            dict[(decl, line, txkey)]  — latest reviewed mapping per line_key
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.parsers.bcct_adapters import adapter_for_client, resolve as resolve_adapter


# Material categories that a resolved BCCT line may map to. `unknown`
# covers materials with NULL category (rare; should be classified
# during catalog cleanup).
_KNOWN_KINDS = frozenset({"tp", "btp_sx", "btp_nm", "nvl", "ccdc"})


@dataclass
class ResolverContext:
    client_id: str
    # Per-client material roster. Key = customs_code. Value =
    # {category, internal_code, name, has_bom, n_artifacts,
    #  latest_flatten_status}. `has_bom` signals whether
    # `bom_product_code` alias should be populated.
    material_catalog: dict[str, dict] = field(default_factory=dict)
    code_mappings: dict[str, list[dict]] = field(default_factory=dict)
    reviewed: dict[tuple, dict] = field(default_factory=dict)
    adapter_name: str | None = None
    candidate_limit: int = 5

    code_resolution_mode: str | None = None

    @property
    def known_codes(self) -> set:
        """All canonical codes for this client (materials.customs_code)."""
        return set(self.material_catalog.keys())

    @classmethod
    def from_db(cls, client_id: str, cur, *,
                adapter_name: str | None = None,
                candidate_limit: int = 5) -> "ResolverContext":
        """Build a context by querying Postgres once per request (Q5).

        `cur` is an open psycopg cursor. Caller owns the connection.
        Loads:
          - alive bom_artifacts for client → product_codes + per-code meta
          - code_mappings for client → keyed by both customs_code and internal_code
          - latest reviewed_line_mapping per (decl, line, txkey)

        Resolver code never opens its own cursor. All DB reads happen here
        so a hot endpoint loop calls `from_db()` once and resolves N rows
        in pure Python.
        """
        # Adapter dispatch reads code_resolution_mode from clients.
        cur.execute(
            "select code_resolution_mode from hub.clients where client_id = %s",
            (client_id,),
        )
        mode_row = cur.fetchone()
        code_resolution_mode = mode_row[0] if mode_row else None

        # Materials catalog — master registry per client (NVL+BTP+TP+CCDC).
        # LEFT JOIN bom_artifacts (for n_artifacts/flatten_status) +
        # v_material_roles (for atomic signals + observed_roles + conflict).
        # Single pass yields everything resolver and consumers need.
        cur.execute(
            """
            select m.customs_code,
                   m.internal_code,
                   m.name,
                   coalesce(m.category_override, m.category) as category,
                   m.btp_sourcing,
                   coalesce(b.n_artifacts, 0) as n_artifacts,
                   coalesce(b.has_flattened, 0) as has_flattened,
                   coalesce(vmr.has_imports, false) as has_imports,
                   coalesce(vmr.has_exports, false) as has_exports,
                   coalesce(vmr.is_consumed_in_bom, false) as is_consumed_in_bom,
                   coalesce(vmr.has_own_bom, false) as has_own_bom,
                   coalesce(vmr.observed_roles, '{}'::text[]) as observed_roles,
                   coalesce(vmr.is_multi_role, false) as is_multi_role,
                   coalesce(vmr.declared_observed_conflict, false) as declared_observed_conflict
            from hub.materials m
            left join (
                select product_code,
                       count(*) as n_artifacts,
                       max(case when flatten_status = 'flattened'
                                then 1 else 0 end) as has_flattened
                from hub.bom_artifacts
                where client_id = %s and tombstoned_at is null
                group by product_code
            ) b on b.product_code = m.customs_code
            left join hub.v_material_roles vmr
                   on vmr.client_id = m.client_id
                  and vmr.customs_code = m.customs_code
            where m.client_id = %s
            """,
            (client_id, client_id),
        )
        material_catalog: dict[str, dict] = {}
        for (code, internal, name, category, btp_sourcing,
             n_art, has_flat,
             has_imp, has_exp, consumed, has_own,
             observed_roles, is_multi, conflict) in cur.fetchall():
            material_catalog[code] = {
                "internal_code": internal,
                "name": name,
                "category": category,
                "btp_sourcing": btp_sourcing,
                "n_artifacts": int(n_art),
                "has_bom": int(n_art) > 0,
                "latest_flatten_status": (
                    "flattened" if has_flat else
                    ("non_flattened" if int(n_art) > 0 else None)
                ),
                # Catalog-roles refactor (mig 033) — atomic signals + derived.
                "has_imports": bool(has_imp),
                "has_exports": bool(has_exp),
                "is_consumed_in_bom": bool(consumed),
                "has_own_bom": bool(has_own),
                "observed_roles": list(observed_roles or []),
                "is_multi_role": bool(is_multi),
                "declared_observed_conflict": bool(conflict),
            }

        # Backfill BOM-only products: codes that exist as bom_artifacts.product_code
        # but have no entry in hub.materials (data gap — should be addressed by a
        # bootstrap script eventually). Without this, the BCCT goods_name resolver
        # misses paren codes that have BOMs but no registered material entry —
        # exactly the spec golden case (BIENTAN.17 → PV01.0117500 where
        # PV01.0117500 has BOMs but isn't in materials registry).
        cur.execute(
            """
            select b.product_code,
                   count(*) as n_artifacts,
                   max(case when b.flatten_status = 'flattened'
                            then 1 else 0 end) as has_flattened
            from hub.bom_artifacts b
            where b.client_id = %s
              and b.tombstoned_at is null
              and not exists (
                select 1 from hub.materials m
                where m.client_id = %s and m.customs_code = b.product_code
              )
            group by b.product_code
            """,
            (client_id, client_id),
        )
        for code, n_art, has_flat in cur.fetchall():
            if code in material_catalog:
                continue
            material_catalog[code] = {
                "internal_code": code,
                "name": None,
                # Default category for BOM-only products is 'tp' — matches
                # app/stores/bom.py coalesce(m.category, 'tp') convention.
                "category": "tp",
                "btp_sourcing": None,
                "n_artifacts": int(n_art),
                "has_bom": True,
                "latest_flatten_status": (
                    "flattened" if has_flat else "non_flattened"
                ),
                # No v_material_roles row for these codes (view only includes
                # materials catalog entries). Atomic signals default false;
                # has_own_bom is true by definition. observed_roles synthesized
                # to ['tp'] since BOM ownership = TP-like role.
                "has_imports": False,
                "has_exports": False,
                "is_consumed_in_bom": False,
                "has_own_bom": True,
                "observed_roles": ["tp"],
                "is_multi_role": False,
                "declared_observed_conflict": False,
            }

        # Code mappings keyed by both customs_code and internal_code so the
        # resolver can look up either side.
        cur.execute(
            "select internal_code, customs_code, category, notes "
            "from hub.code_mappings where client_id = %s",
            (client_id,),
        )
        mappings: dict[str, list[dict]] = {}
        for internal, customs, category, notes in cur.fetchall():
            entry = {
                "internal_code": internal,
                "customs_code": customs,
                "category": category,
                "notes": notes,
            }
            mappings.setdefault(internal, []).append(entry)
            mappings.setdefault(customs, []).append(entry)

        # Latest reviewed mapping per line_key.
        cur.execute(
            """
            select declaration_no, line_no, transaction_key,
                   bom_product_code, status, reviewed_by, reviewed_at
            from hub.bcct_material_identity_review r1
            where client_id = %s
              and reviewed_at = (
                select max(reviewed_at) from hub.bcct_material_identity_review r2
                where r2.client_id = r1.client_id
                  and r2.transaction_key = r1.transaction_key
                  and r2.line_no = r1.line_no
              )
            """,
            (client_id,),
        )
        reviewed: dict[tuple, dict] = {}
        for decl, line, txkey, code, status, by, at in cur.fetchall():
            reviewed[(decl, line, txkey)] = {
                "bom_product_code": code,
                "status": status,
                "reviewed_by": by,
                "reviewed_at": at.isoformat() if at else None,
            }

        return cls(
            client_id=client_id,
            material_catalog=material_catalog,
            code_mappings=mappings,
            reviewed=reviewed,
            adapter_name=adapter_name,
            candidate_limit=candidate_limit,
            code_resolution_mode=code_resolution_mode,
        )


def _adapter_for(ctx: ResolverContext):
    if ctx.adapter_name:
        a = resolve_adapter(ctx.adapter_name)
        if a is not None:
            return a
    return adapter_for_client(ctx.client_id, ctx.code_resolution_mode)


def _line_key(row: dict, ctx: ResolverContext) -> dict:
    return {
        "client_id": ctx.client_id,
        "declaration_no": row.get("declaration_no") or "",
        "line_no": row.get("line_no") or "",
        "transaction_key": row.get("transaction_key") or "",
    }


def _kind_for(code: str, ctx: ResolverContext) -> str:
    """Return product_kind for a resolved code (tp/btp_sx/btp_nm/nvl/ccdc/unknown)."""
    meta = ctx.material_catalog.get(code) or {}
    cat = (meta.get("category") or "").lower()
    return cat if cat in _KNOWN_KINDS else "unknown"


def _bom_alias(code: str | None, ctx: ResolverContext) -> str | None:
    """Conditional alias: `bom_product_code` is the resolved code only
    when the material has alive BOM. Preserves CO's existing logic
    `if bom_product_code: load_bom_rows(...)` — non-BOM resolutions
    leave it None so CO doesn't try to load BOM for an NVL leaf."""
    if not code:
        return None
    meta = ctx.material_catalog.get(code) or {}
    return code if meta.get("has_bom") else None


_TOPLEVEL_ROLE_KEYS = (
    "has_imports", "has_exports", "is_consumed_in_bom", "has_own_bom",
    "observed_roles", "is_multi_role", "btp_sourcing",
    "declared_observed_conflict",
)


def _toplevel_role_fields(code: str | None, ctx: ResolverContext) -> dict:
    """Pull atomic-signals + observed_roles + multi-role + sourcing + conflict
    from the catalog meta. Returns shape-stable defaults when code is unknown
    (caller-friendly: missing rows still get all keys present).
    """
    meta = ctx.material_catalog.get(code) if code else None
    if not meta:
        return {
            "has_imports": False,
            "has_exports": False,
            "is_consumed_in_bom": False,
            "has_own_bom": False,
            "observed_roles": [],
            "is_multi_role": False,
            "btp_sourcing": None,
            "declared_observed_conflict": False,
        }
    return {k: meta.get(k) for k in _TOPLEVEL_ROLE_KEYS}


def _empty_result(row: dict, ctx: ResolverContext, *, status: str,
                  resolution_source: str, candidates: list[dict],
                  evidence: dict | None = None,
                  selected_candidate_code: str | None = None,
                  confidence: str | None = None,
                  review_status: str = "needs_review") -> dict:
    adapter = _adapter_for(ctx)
    out = {
        "resolution_status": status,
        "resolved_code": None,
        "bom_product_code": None,
        "product_kind": None,
        "selected_candidate_code": selected_candidate_code,
        "display_code": row.get("internal_code") or row.get("customs_code") or "",
        "declared_customs_code": row.get("customs_code") or "",
        "declared_internal_code": row.get("internal_code") or "",
        "line_key": _line_key(row, ctx),
        "resolution_source": resolution_source,
        "confidence": confidence,
        "review_status": review_status,
        "parser_adapter": adapter.name,
        "parser_version": adapter.parser_version,
        "evidence": evidence or {},
        "candidates": candidates[: ctx.candidate_limit],
    }
    out.update(_toplevel_role_fields(None, ctx))
    return out


def _resolved(row: dict, ctx: ResolverContext, *, code: str,
              resolution_source: str, evidence: dict, candidates: list[dict],
              confidence: str = "high",
              review_status: str = "system_resolved") -> dict:
    adapter = _adapter_for(ctx)
    out = {
        "resolution_status": "resolved",
        "resolved_code": code,
        "bom_product_code": _bom_alias(code, ctx),
        "product_kind": _kind_for(code, ctx),
        "selected_candidate_code": code,
        "display_code": row.get("internal_code") or row.get("customs_code") or "",
        "declared_customs_code": row.get("customs_code") or "",
        "declared_internal_code": row.get("internal_code") or "",
        "line_key": _line_key(row, ctx),
        "resolution_source": resolution_source,
        "confidence": confidence,
        "review_status": review_status,
        "parser_adapter": adapter.name,
        "parser_version": adapter.parser_version,
        "evidence": evidence,
        "candidates": candidates[: ctx.candidate_limit],
    }
    out.update(_toplevel_role_fields(code, ctx))
    return out


def _make_candidate(code: str, source: str, *, confidence: str, reason: str,
                    ctx: ResolverContext) -> dict:
    """Build a candidate dict per D6 — minimal field set:
    product_code, source, confidence, reason, product_kind, observed_roles,
    bom_artifact_count, latest_flatten_status. Atomic signals + conflict
    + sourcing live at top-level only (NOT propagated to candidates)."""
    meta = ctx.material_catalog.get(code) or {}
    out = {
        "product_code": code,
        "source": source,
        "confidence": confidence,
        "reason": reason,
        "product_kind": _kind_for(code, ctx),
        "observed_roles": list(meta.get("observed_roles") or []),
    }
    if "n_artifacts" in meta:
        out["bom_artifact_count"] = meta["n_artifacts"]
    if meta.get("latest_flatten_status"):
        out["latest_flatten_status"] = meta["latest_flatten_status"]
    return out


def resolve_material_identity(row: dict, *, ctx: ResolverContext) -> dict:
    """Run the 5-stage resolver against a single BCCT row.

    Returns a `material_identity` dict matching the CO contract shape.
    Pure function given the context — no DB access here.
    """
    customs = (row.get("customs_code") or "").strip()
    catalog = ctx.material_catalog

    # ── Stage 1: structured field ─────────────────────────────────
    if customs and customs in catalog:
        candidate = _make_candidate(
            customs, "structured_field",
            confidence="high",
            reason="customs_code matches a BOM product directly.",
            ctx=ctx,
        )
        return _resolved(
            row, ctx, code=customs,
            resolution_source="structured_field",
            evidence={
                "source_field": "customs_code",
                "source_text": customs,
                "matched_text": customs,
                "match_rule": "customs_code_exists_in_bom_products",
            },
            candidates=[candidate],
        )

    # ── Stage 2: goods_name_embedded_code (client adapter) ────────
    adapter = _adapter_for(ctx)
    extractions = adapter.parse_candidates(row)
    paren_validated: list[tuple[dict, dict]] = []  # (extraction, candidate)
    for ext in extractions:
        code = ext["product_code"]
        if code in catalog:
            paren_validated.append((
                ext,
                _make_candidate(
                    code, "goods_name_embedded_code",
                    confidence="high",
                    reason="Parsed from goods_name and matching BOM artifacts exist.",
                    ctx=ctx,
                ),
            ))

    if len(paren_validated) == 1:
        ext, cand = paren_validated[0]
        return _resolved(
            row, ctx, code=ext["product_code"],
            resolution_source="goods_name_embedded_code",
            evidence={
                "source_field": ext["source_field"],
                "source_text": (row.get("goods_name") or ""),
                "matched_text": ext["matched_text"],
                "match_rule": ext["match_rule"],
            },
            candidates=[cand],
        )

    if len(paren_validated) > 1:
        # Tie-break (Q4): rank by bom_artifact_count desc, then
        # latest_flatten_status='flattened' first. The resolution stays
        # `ambiguous` though — best candidate goes to selected_candidate_code.
        ranked = sorted(
            paren_validated,
            key=lambda pair: (
                -(pair[1].get("bom_artifact_count") or 0),
                0 if pair[1].get("latest_flatten_status") == "flattened" else 1,
                pair[1]["product_code"],
            ),
        )
        best_ext, best_cand = ranked[0]
        return _empty_result(
            row, ctx,
            status="ambiguous",
            resolution_source="goods_name_embedded_code",
            candidates=[c for _, c in ranked],
            evidence={
                "source_field": "goods_name",
                "source_text": (row.get("goods_name") or ""),
                "matched_text": best_ext["matched_text"],
                "match_rule": "multiple_paren_codes_found_in_bom_products",
            },
            selected_candidate_code=best_ext["product_code"],
        )

    # ── Stage 3: reviewed_line_mapping ────────────────────────────
    rk = (
        row.get("declaration_no") or "",
        row.get("line_no") or "",
        row.get("transaction_key") or "",
    )
    reviewed = ctx.reviewed.get(rk)
    if reviewed and reviewed.get("status") == "reviewed" and reviewed.get("bom_product_code"):
        code = reviewed["bom_product_code"]
        # Guard: a reviewed code that no longer has alive BOM artifacts
        # must NOT return `resolved` — CO would fail to load the BOM.
        # Downgrade to `unverified` with the reviewed candidate so the
        # operator can pick a replacement.
        if code in catalog:
            candidate = _make_candidate(
                code, "reviewed_line_mapping",
                confidence="high",
                reason="Operator-reviewed mapping for this BCCT line.",
                ctx=ctx,
            )
            return _resolved(
                row, ctx, code=code,
                resolution_source="reviewed_line_mapping",
                evidence={
                    "source_field": "bcct_material_identity_review",
                    "source_text": code,
                    "matched_text": code,
                    "match_rule": "reviewed_line_mapping",
                    "reviewed_by": reviewed.get("reviewed_by"),
                    "reviewed_at": reviewed.get("reviewed_at"),
                },
                candidates=[candidate],
                review_status="reviewed",
            )
        # Reviewed code missing from current BOM → unverified.
        stale_candidate = _make_candidate(
            code, "reviewed_line_mapping",
            confidence="low",
            reason="Operator-reviewed mapping but no alive BOM artifact for this code.",
            ctx=ctx,
        )
        return _empty_result(
            row, ctx,
            status="unverified",
            resolution_source="reviewed_line_mapping",
            candidates=[stale_candidate],
            evidence={
                "source_field": "bcct_material_identity_review",
                "source_text": code,
                "matched_text": code,
                "match_rule": "reviewed_code_no_alive_bom",
                "reviewed_by": reviewed.get("reviewed_by"),
                "reviewed_at": reviewed.get("reviewed_at"),
            },
            selected_candidate_code=code,
            confidence="low",
            review_status="reviewed",
        )

    # If a reviewed entry exists but is rejected, treat as missing
    # for now (no candidate). Distinction vs status='reviewed' lets
    # operators block bad auto-resolution explicitly.
    if reviewed and reviewed.get("status") == "rejected":
        return _empty_result(
            row, ctx,
            status="missing",
            resolution_source="none",
            candidates=[],
            evidence={
                "source_field": "bcct_material_identity_review",
                "match_rule": "reviewed_rejected",
            },
        )

    # ── Stage 4: code_mapping_candidate (candidates only) ─────────
    mapped: list[dict] = []
    seen_codes: set[str] = set()
    for key in (customs, row.get("internal_code") or ""):
        if not key:
            continue
        for entry in ctx.code_mappings.get(key, []):
            for cand_code in (entry.get("internal_code"), entry.get("customs_code")):
                if not cand_code or cand_code in seen_codes:
                    continue
                if cand_code not in catalog:
                    continue
                seen_codes.add(cand_code)
                mapped.append(
                    _make_candidate(
                        cand_code, "code_mapping_candidate",
                        confidence="low",
                        reason="Code-mappings produced a candidate; many-to-many — not auto-resolved.",
                        ctx=ctx,
                    ),
                )

    if mapped:
        # Deterministic ordering by bom_artifact_count desc, then code.
        mapped.sort(
            key=lambda c: (
                -(c.get("bom_artifact_count") or 0),
                c["product_code"],
            ),
        )
        # Many-to-many → unverified (one candidate) or ambiguous (multiple).
        status = "ambiguous" if len(mapped) > 1 else "unverified"
        return _empty_result(
            row, ctx,
            status=status,
            resolution_source="code_mapping_candidate",
            candidates=mapped,
            evidence={
                "source_field": "code_mappings",
                "match_rule": "code_mapping_candidate",
            },
            selected_candidate_code=mapped[0]["product_code"],
            confidence="low",
        )

    # Adapter parsed candidates but none validated — unverified, not missing.
    if extractions:
        unverified_cands = [
            _make_candidate(
                ext["product_code"], "goods_name_embedded_code",
                confidence="low",
                reason="Parsed from goods_name but no matching BOM artifact for this client.",
                ctx=ctx,
            )
            for ext in extractions
        ]
        return _empty_result(
            row, ctx,
            status="unverified",
            resolution_source="goods_name_embedded_code",
            candidates=unverified_cands,
            evidence={
                "source_field": "goods_name",
                "source_text": (row.get("goods_name") or ""),
                "matched_text": extractions[0]["matched_text"],
                "match_rule": "parsed_code_no_bom_artifact",
            },
            selected_candidate_code=extractions[0]["product_code"],
            confidence="low",
        )

    # ── Stage 5: missing ──────────────────────────────────────────
    return _empty_result(
        row, ctx,
        status="missing",
        resolution_source="none",
        candidates=[],
    )
