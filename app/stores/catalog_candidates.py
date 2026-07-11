"""Catalog candidates store — DB ops for Mã chờ duyệt.

Brief: .ai/features/2026-05-09-ma-cho-duyet/brief.md

`refresh_candidates(client_id)` rebuilds observation stats from BCCT + BOM +
code_mappings, anti-joins materials, and UPSERTs into `catalog_candidates`.
Status (pending/accepted/rejected) is sticky across refresh — only stats get
rebuilt, never status.

`accept_candidate / reject_candidate / unreject_candidate` are the state
machine transitions. Accept also runs bidirectional auto-mapping per D5.
"""
from __future__ import annotations

from collections import defaultdict
from typing import Iterable

from app.database import connect
from app.parsers.catalog_candidates import (
    _is_missing_hq,
    candidates_from_bcct_row,
    candidates_from_bom_codes,
    candidates_from_code_mapping_pairs,
)
from app.parsers.client_parser_rules import load_rules
from app.stores.provenance import customs_code_placeholders


def _has_dual_system(client_id: str) -> bool:
    """Client has dual NB/HQ code systems if it has parser rules OR
    code_mappings rows."""
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "select 1 from hub.client_parser_rules "
            "where client_id=%s and output_field='internal_code' and enabled "
            "limit 1",
            (client_id,),
        )
        if cur.fetchone():
            return True
        cur.execute(
            "select 1 from hub.code_mappings where client_id=%s limit 1",
            (client_id,),
        )
        return cur.fetchone() is not None


def _materials_codes(client_id: str) -> set[str]:
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "select material_code from hub.materials where client_id=%s",
            (client_id,),
        )
        return {r[0] for r in cur.fetchall()}


# Aggregated per-(code, kind) state across all sources.
class _Stat:
    __slots__ = ("sources", "observed_count", "first_seen", "last_seen",
                 "sample_text", "import_count", "export_count",
                 "decl_set", "bom_role", "bom_sample", "co_occurrences",
                 "hs_counts", "uom_counts", "origin_counts")

    def __init__(self):
        self.sources: set[str] = set()
        self.observed_count: int = 0
        self.first_seen = None
        self.last_seen = None
        self.sample_text: str | None = None
        self.import_count: int = 0
        self.export_count: int = 0
        self.decl_set: set[str] = set()
        self.bom_role: str | None = None  # 'tp_root' | 'btp_sx' | 'nvl_leaf'
        self.bom_sample: str | None = None  # e.g. "trong artifact X (parent)"
        self.co_occurrences: set[str] = set()  # paired NB/HQ codes
        # Frequency tallies → most-common picked at UPSERT time.
        self.hs_counts: dict[str, int] = {}
        self.uom_counts: dict[str, int] = {}
        self.origin_counts: dict[str, int] = {}

    def add_bcct(self, regdate, goods_name, direction, decl_no,
                 hs_code=None, uom=None, origin=None):
        self.sources.add("bcct")
        self.observed_count += 1
        if regdate is not None:
            if self.first_seen is None or regdate < self.first_seen:
                self.first_seen = regdate
            if self.last_seen is None or regdate > self.last_seen:
                self.last_seen = regdate
        if not self.sample_text and goods_name:
            self.sample_text = (goods_name or "")[:300]
        if direction == "import":
            self.import_count += 1
        elif direction == "export":
            self.export_count += 1
        if decl_no:
            self.decl_set.add(decl_no)
        if hs_code:
            self.hs_counts[hs_code] = self.hs_counts.get(hs_code, 0) + 1
        if uom:
            self.uom_counts[uom] = self.uom_counts.get(uom, 0) + 1
        if origin:
            self.origin_counts[origin] = self.origin_counts.get(origin, 0) + 1

    def add_bom(self, role: str | None = None, sample: str | None = None,
                edge_count: int = 1, uom: str | None = None):
        self.sources.add("bom")
        self.observed_count += edge_count
        if role and self.bom_role is None:
            self.bom_role = role
        if sample and self.bom_sample is None:
            self.bom_sample = sample
        if uom:
            self.uom_counts[uom] = self.uom_counts.get(uom, 0) + edge_count

    def add_bqd(self):
        self.sources.add("bqd")

    def add_cooccurrence(self, paired: str):
        self.co_occurrences.add(paired)


def _most_common(counts: dict[str, int]) -> str | None:
    if not counts:
        return None
    return max(counts.items(), key=lambda kv: (kv[1], kv[0]))[0]


def _normalize_uom_counts(counts: dict[str, int]) -> dict[str, int]:
    """Collapse alias counts into canonical buckets. PCS+PIECE+ST → pcs."""
    from app.stores.uom_standards import resolve_canonical
    out: dict[str, int] = {}
    for raw, n in counts.items():
        c = resolve_canonical(raw) or (raw or "").strip().lower()
        if not c:
            continue
        out[c] = out.get(c, 0) + n
    return out


def _infer_production_source(stat: _Stat) -> str | None:
    """Guess production_source from BCCT direction signal.

    import-only → 'nk' (nhập khẩu)
    export-only → 'sx' (sản xuất, agency tự sản)
    both → 'mixed'
    none (BOM/BQD only) → None (let staff decide)
    """
    has_imp = stat.import_count > 0
    has_exp = stat.export_count > 0
    if has_imp and has_exp:
        return "mixed"
    if has_imp:
        return "nk"
    if has_exp:
        return "sx"
    return None


def _suggest_category(stat: _Stat) -> tuple[str | None, bool]:
    """Returns (suggested_category, multi_direction).

    Priority: BCCT direction signal > BOM-tree role.
    """
    has_imp = stat.import_count > 0
    has_exp = stat.export_count > 0
    if has_imp and has_exp:
        return ("nvl", True)
    if has_imp:
        return ("nvl", False)
    if has_exp:
        return ("tp", False)
    # No BCCT direction signal → fall back to BOM role (with caveats).
    # tp_root: confident — code IS an artifact's product_code.
    # btp_sx: confident — appears as parent + not a TP root.
    # nvl_leaf: NOT confident enough — shallow BOMs stop at BTP, so a "leaf"
    #   could be a purchased BTP (btp_nm), not raw material. Leave None and
    #   let staff classify (memory: project_bom_3_shapes.md).
    if stat.bom_role == "tp_root":
        return ("tp", False)
    if stat.bom_role == "btp_sx":
        return ("btp_sx", False)
    return (None, False)


def _bom_role_classification(client_id: str) -> dict[str, tuple[str, str, int]]:
    """Map each BOM code → (role, sample_label, edge_count).

    role ∈ {'tp_root', 'btp_sx', 'nvl_leaf'}.
    edge_count = số lần code xuất hiện trong bom_edges (as parent or child).
    """
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "select distinct product_code from hub.bom_artifacts "
            "where client_id=%s and tombstoned_at is null",
            (client_id,),
        )
        tp_roots = {r[0] for r in cur.fetchall()}
        cur.execute(
            """
            select e.parent_code as code, count(*) as n from hub.bom_edges e
              join hub.bom_artifacts a on a.artifact_id=e.artifact_id
             where a.client_id=%s and a.tombstoned_at is null
            group by e.parent_code
            """,
            (client_id,),
        )
        parent_counts = dict(cur.fetchall())
        cur.execute(
            """
            select e.child_code as code, count(*) as n from hub.bom_edges e
              join hub.bom_artifacts a on a.artifact_id=e.artifact_id
             where a.client_id=%s and a.tombstoned_at is null
            group by e.child_code
            """,
            (client_id,),
        )
        child_counts = dict(cur.fetchall())

    parents = set(parent_counts)
    children = set(child_counts)
    out: dict[str, tuple[str, str, int]] = {}
    for code in tp_roots | parents | children:
        edges = parent_counts.get(code, 0) + child_counts.get(code, 0)
        if code in tp_roots:
            out[code] = ("tp_root", "TP root trong BOM", edges)
        elif code in parents:
            out[code] = ("btp_sx", "Parent giữa cây (BTP_SX)", edges)
        else:
            out[code] = ("nvl_leaf", "Leaf trong BOM", edges)
    return out


def refresh_candidates(client_id: str) -> int:
    """Rebuild candidate observation stats from sources; UPSERT into
    catalog_candidates. Status sticky.

    Returns the number of candidate rows after refresh (anti-joined
    against materials).
    """
    has_dual = _has_dual_system(client_id)
    rules = load_rules(client_id=client_id, output_field="internal_code")
    materials = _materials_codes(client_id)

    # Aggregate per (code, kind)
    agg: dict[tuple[str, str], _Stat] = defaultdict(_Stat)

    # ── Source 1+2: BCCT (per-row classification) ──
    with connect() as conn, conn.cursor() as cur:
        placeholders = customs_code_placeholders(cur, client_id=client_id)
        cur.execute(
            "select customs_code, goods_name, direction, registration_date, "
            "       declaration_no, hs_code, unit, origin "
            "from hub.bcct_rows where client_id=%s",
            (client_id,),
        )
        for (customs_code, goods_name, direction, regdate, decl_no,
             hs_code, unit, origin) in cur.fetchall():
            row = {"customs_code": customs_code, "goods_name": goods_name}
            row_candidates = candidates_from_bcct_row(
                row, rules=rules, has_dual_system=has_dual,
                placeholders=placeholders,
            )
            hq_codes_in_row = [c for c, k in row_candidates if k == "hq"]
            nb_codes_in_row = [c for c, k in row_candidates if k == "nb"]
            for code, kind in row_candidates:
                if code in materials:
                    continue
                agg[(code, kind)].add_bcct(
                    regdate, goods_name, direction, decl_no,
                    hs_code=hs_code, uom=unit, origin=origin,
                )
                if kind == "hq":
                    for nb in nb_codes_in_row:
                        agg[(code, kind)].add_cooccurrence(nb)
                elif kind == "nb":
                    for hq in hq_codes_in_row:
                        agg[(code, kind)].add_cooccurrence(hq)

    # ── Source 3: BOM edges ──
    bom_role_map = _bom_role_classification(client_id)
    # Most-common UoM per code (from bom_edges.uom, parent or child side)
    bom_uom_map: dict[str, str] = {}
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            """
            with code_uom as (
              select e.child_code as code, e.uom from hub.bom_edges e
                join hub.bom_artifacts a on a.artifact_id=e.artifact_id
               where a.client_id=%s and a.tombstoned_at is null
                 and e.uom is not null and e.uom <> ''
            )
            select code, uom from (
              select code, uom, count(*) as n,
                     row_number() over (partition by code order by count(*) desc) as rn
              from code_uom group by code, uom
            ) t where rn = 1
            """,
            (client_id,),
        )
        bom_uom_map = dict(cur.fetchall())
    bom_codes = list(bom_role_map.keys())
    for code, kind in candidates_from_bom_codes(bom_codes, has_dual_system=has_dual):
        if code in materials:
            continue
        role, sample, edges = bom_role_map.get(code, (None, None, 1))
        agg[(code, kind)].add_bom(
            role=role, sample=sample, edge_count=edges,
            uom=bom_uom_map.get(code),
        )

    # ── Source 4: code_mappings (BQD) ──
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "select distinct customs_code, internal_code from hub.code_mappings "
            "where client_id=%s",
            (client_id,),
        )
        pairs = list(cur.fetchall())
    for code, kind in candidates_from_code_mapping_pairs(pairs):
        if code in materials:
            continue
        agg[(code, kind)].add_bqd()

    # ── Post-aggregation: collapse multi-kind same-string candidates ──
    # If string X appears with multiple kinds AND no kind has co-occurrences
    # (i.e., never paired with a DIFFERENT code in BCCT), then X represents
    # one canonical concept → collapse to 'unified'.
    _collapse_unaffiliated_kinds(agg)

    # ── Cross-ref: pull sample_text from BCCT for codes with empty sample ──
    _backfill_sample_from_bcct(client_id, agg)

    # BOM-only candidates won't have a BCCT goods_name. Fall back to
    # bom_edges.payload->>'description' (parser-extracted from the source
    # XLSX; e.g. SAP "Object description" for Johnson).
    _backfill_sample_from_bom(client_id, agg)

    # ── UPSERT ──
    with connect() as conn, conn.cursor() as cur:
        for (code, kind), stat in agg.items():
            suggested, multi_dir = _suggest_category(stat)
            hs_code = _most_common(stat.hs_counts)
            # Normalize UoM aliases (PCS/PIECES/ST → pcs) before picking
            # most-common — staff Accept gets canonical, not raw alias.
            uom = _most_common(_normalize_uom_counts(stat.uom_counts))
            origin = _most_common(stat.origin_counts)
            inferred_prod = _infer_production_source(stat)
            cur.execute(
                """
                insert into hub.catalog_candidates
                  (client_id, code, code_kind, sources, observed_count,
                   first_seen, last_seen, sample_text, suggested_category,
                   multi_direction, import_count, export_count, decl_count,
                   bom_role, bom_sample, co_occurrence_count,
                   hs_code, hs_alternates_count, uom, origin,
                   inferred_production_source,
                   status, updated_at)
                values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                        %s, %s, %s, %s, %s, %s, %s, %s, 'pending', now())
                on conflict (client_id, code, code_kind) do update set
                  sources = excluded.sources,
                  observed_count = excluded.observed_count,
                  first_seen = excluded.first_seen,
                  last_seen = excluded.last_seen,
                  sample_text = excluded.sample_text,
                  suggested_category = excluded.suggested_category,
                  multi_direction = excluded.multi_direction,
                  import_count = excluded.import_count,
                  export_count = excluded.export_count,
                  decl_count = excluded.decl_count,
                  bom_role = excluded.bom_role,
                  bom_sample = excluded.bom_sample,
                  co_occurrence_count = excluded.co_occurrence_count,
                  hs_code = excluded.hs_code,
                  hs_alternates_count = excluded.hs_alternates_count,
                  uom = excluded.uom,
                  origin = excluded.origin,
                  inferred_production_source = excluded.inferred_production_source,
                  updated_at = now()
                  -- status, decided_*, decision_reason: STICKY, never overwritten
                """,
                (
                    client_id, code, kind,
                    sorted(stat.sources),
                    stat.observed_count,
                    stat.first_seen, stat.last_seen,
                    stat.sample_text, suggested, multi_dir,
                    stat.import_count, stat.export_count,
                    len(stat.decl_set),
                    stat.bom_role, stat.bom_sample,
                    len(stat.co_occurrences),
                    hs_code, len(stat.hs_counts),
                    uom, origin, inferred_prod,
                ),
            )
        # Drop pending candidates that no longer match any source (e.g. BCCT
        # row deleted, code disappeared). Rejected/accepted stay for history.
        if agg:
            codes = [k[0] for k in agg.keys()]
            kinds = [k[1] for k in agg.keys()]
            cur.execute(
                "delete from hub.catalog_candidates c "
                "where c.client_id=%s and c.status='pending' "
                "  and not exists ("
                "    select 1 from unnest(%s::text[], %s::text[]) as t(code, kind) "
                "    where t.code = c.code and t.kind = c.code_kind"
                "  )",
                (client_id, codes, kinds),
            )
        else:
            cur.execute(
                "delete from hub.catalog_candidates "
                "where client_id=%s and status='pending'",
                (client_id,),
            )

    return len(agg)


def refresh_candidates_after_ingest(client_id: str) -> None:
    """Post-ingest hook (#32): rebuild the review queue after new source
    rows land (BCCT / BOM / BQD). Never bubbles — a failed refresh must
    not fail the upload that triggered it; the page's "Làm mới" button
    re-runs it on demand."""
    import logging
    try:
        refresh_candidates(client_id)
    except Exception:
        logging.getLogger(__name__).exception(
            "catalog candidates refresh after ingest failed for %s", client_id,
        )


# ── Post-aggregation helpers ──────────────────────────────────────────────


def _collapse_unaffiliated_kinds(agg: dict[tuple[str, str], _Stat]) -> None:
    """Mutate `agg` in place: collapse multi-kind same-string candidates to
    'unified' when none of the kinds carry a co-occurrence with a DIFFERENT
    string code in BCCT.

    Reasoning: if string X never appears in a BCCT row alongside a paired NB
    (`Y` extracted via parser_rules where Y != X), then X is one canonical
    concept across all sources. The per-source classification (BCCT→'hq',
    BOM→'nb', BQD→'unified') was an artifact of source-specific defaults.
    """
    by_code: dict[str, list[str]] = {}
    for (code, kind) in agg.keys():
        by_code.setdefault(code, []).append(kind)

    for code, kinds in by_code.items():
        if len(kinds) <= 1:
            continue
        # Has any (code, kind) entry recorded a co-occurrence with another
        # string? co_occurrences sets contain paired strings != code.
        has_pairing = any(
            agg[(code, k)].co_occurrences for k in kinds
        )
        if has_pairing:
            # Real bucket-style HQ. Keep separate kinds.
            continue

        # Collapse: merge all kind-stats into 'unified'.
        merged = _Stat()
        for k in kinds:
            stat = agg.pop((code, k))
            merged.sources.update(stat.sources)
            merged.observed_count += stat.observed_count
            merged.import_count += stat.import_count
            merged.export_count += stat.export_count
            merged.decl_set.update(stat.decl_set)
            merged.co_occurrences.update(stat.co_occurrences)
            if stat.first_seen and (
                merged.first_seen is None or stat.first_seen < merged.first_seen
            ):
                merged.first_seen = stat.first_seen
            if stat.last_seen and (
                merged.last_seen is None or stat.last_seen > merged.last_seen
            ):
                merged.last_seen = stat.last_seen
            if not merged.sample_text and stat.sample_text:
                merged.sample_text = stat.sample_text
            if not merged.bom_role and stat.bom_role:
                merged.bom_role = stat.bom_role
            if not merged.bom_sample and stat.bom_sample:
                merged.bom_sample = stat.bom_sample
        agg[(code, "unified")] = merged


def _backfill_sample_from_bcct(
    client_id: str, agg: dict[tuple[str, str], _Stat],
) -> None:
    """For candidates with empty sample_text, look up bcct_rows.goods_name
    where customs_code = candidate.code. Use the most recent goods_name."""
    needs_sample = [
        code for (code, kind), stat in agg.items() if not stat.sample_text
    ]
    if not needs_sample:
        return
    needs_sample = list(set(needs_sample))
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            """
            select distinct on (customs_code)
                   customs_code, goods_name
            from hub.bcct_rows
            where client_id=%s and customs_code = any(%s)
              and goods_name is not null and goods_name <> ''
            order by customs_code, registration_date desc nulls last
            """,
            (client_id, needs_sample),
        )
        lookup = {cc: gn for cc, gn in cur.fetchall()}
    for (code, kind), stat in agg.items():
        if not stat.sample_text and code in lookup:
            stat.sample_text = (lookup[code] or "")[:300]


def _backfill_sample_from_bom(
    client_id: str, agg: dict[tuple[str, str], _Stat],
) -> None:
    """For candidates with empty sample_text, fall back to
    bom_edges.payload->>'description' where the candidate code matches
    child_code or parent_code in any alive artifact. Picks the most
    recently-published artifact's description for that code.
    """
    needs_sample = list({
        code for (code, kind), stat in agg.items() if not stat.sample_text
    })
    if not needs_sample:
        return
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            """
            with hits as (
              select e.child_code as code,
                     e.payload->>'description' as description,
                     a.published_at
                from hub.bom_edges e
                join hub.bom_artifacts a on a.artifact_id = e.artifact_id
               where a.client_id = %s
                 and a.tombstoned_at is null
                 and e.child_code = any(%s)
                 and coalesce(e.payload->>'description', '') <> ''
              union all
              select e.parent_code as code,
                     e.payload->>'description' as description,
                     a.published_at
                from hub.bom_edges e
                join hub.bom_artifacts a on a.artifact_id = e.artifact_id
               where a.client_id = %s
                 and a.tombstoned_at is null
                 and e.parent_code = any(%s)
                 and coalesce(e.payload->>'description', '') <> ''
            )
            select distinct on (code) code, description
              from hits
             order by code, published_at desc nulls last
            """,
            (client_id, needs_sample, client_id, needs_sample),
        )
        lookup = {code: desc for code, desc in cur.fetchall()}
    for (code, kind), stat in agg.items():
        if not stat.sample_text and code in lookup:
            stat.sample_text = (lookup[code] or "")[:300]


# ── State machine transitions ─────────────────────────────────────────────


def _get_candidate(candidate_id: int) -> dict | None:
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "select candidate_id, client_id, code, code_kind, status "
            "from hub.catalog_candidates where candidate_id=%s",
            (candidate_id,),
        )
        row = cur.fetchone()
        if not row:
            return None
        cols = [d[0] for d in cur.description]
        return dict(zip(cols, row))


def _bcct_paren_pairs_for_hq(client_id: str, hq_code: str) -> list[tuple[str, str]]:
    """Scan BCCT rows where customs_code=hq_code; return (hq, nb) pairs from
    paren-extract via parser rules. Used by Accept-HQ auto-mapping."""
    rules = load_rules(client_id=client_id, output_field="internal_code")
    if not rules:
        return []
    pairs: set[tuple[str, str]] = set()
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "select goods_name from hub.bcct_rows "
            "where client_id=%s and customs_code=%s",
            (client_id, hq_code),
        )
        for (goods_name,) in cur.fetchall():
            row = {"customs_code": hq_code, "goods_name": goods_name}
            from app.parsers.client_parser_rules import (
                extract_all_matches_from_compiled,
            )
            for m in extract_all_matches_from_compiled(rules, row=row):
                nb = (m.get("product_code") or "").strip()
                if nb and nb != hq_code:
                    pairs.add((hq_code, nb))
    return sorted(pairs)


def _bcct_paren_pairs_for_nb(client_id: str, nb_code: str) -> list[tuple[str, str]]:
    """Scan BCCT rows where paren-extract yields nb_code; return (hq, nb)
    pairs. Used by Accept-NB auto-mapping (retroactive)."""
    rules = load_rules(client_id=client_id, output_field="internal_code")
    if not rules:
        return []
    from app.parsers.client_parser_rules import (
        extract_all_matches_from_compiled,
    )
    pairs: set[tuple[str, str]] = set()
    with connect() as conn, conn.cursor() as cur:
        placeholders = customs_code_placeholders(cur, client_id=client_id)
        cur.execute(
            "select customs_code, goods_name from hub.bcct_rows "
            "where client_id=%s",
            (client_id,),
        )
        for customs_code, goods_name in cur.fetchall():
            hq = (customs_code or "").strip()
            if _is_missing_hq(hq, placeholders):
                continue
            row = {"customs_code": customs_code, "goods_name": goods_name}
            for m in extract_all_matches_from_compiled(rules, row=row):
                nb = (m.get("product_code") or "").strip()
                if nb == nb_code and nb != hq:
                    pairs.add((hq, nb))
    return sorted(pairs)


def _materials_codes_with_kind(client_id: str) -> dict[str, str]:
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "select material_code, code_kind from hub.materials where client_id=%s",
            (client_id,),
        )
        return {r[0]: r[1] for r in cur.fetchall()}


def _auto_map_for_accept(
    client_id: str, code: str, kind: str,
) -> int:
    """Run bidirectional auto-mapping per D5. Returns number of new mappings.
    Caller is responsible for ensuring `code` is now in materials."""
    if kind == "unified":
        return 0  # single-system clients: no NB/HQ split, no mapping

    materials = _materials_codes_with_kind(client_id)
    pairs: list[tuple[str, str]] = []
    if kind == "hq":
        # Scan BCCT for (hq, nb) pairs co-occurring with this hq
        for hq, nb in _bcct_paren_pairs_for_hq(client_id, code):
            if materials.get(nb) is not None:  # NB exists in materials
                pairs.append((hq, nb))
    elif kind == "nb":
        # Scan BCCT for (hq, nb) pairs co-occurring with this nb
        for hq, nb in _bcct_paren_pairs_for_nb(client_id, code):
            if materials.get(hq) == "hq":  # HQ exists in materials with hq kind
                pairs.append((hq, nb))

    if not pairs:
        return 0
    with connect() as conn, conn.cursor() as cur:
        for hq, nb in pairs:
            cur.execute(
                "insert into hub.code_mappings (client_id, internal_code, customs_code) "
                "values (%s, %s, %s) on conflict do nothing",
                (client_id, nb, hq),
            )
    return len(pairs)


def accept_candidate(
    candidate_id: int,
    *,
    actor: str,
    name: str,
    category: str,
    status: str = "under_review",
    uom: str | None = None,
    production_source: str | None = None,
    supplier_hint: str | None = None,
) -> None:
    """Accept a candidate: insert into materials + mark candidate accepted +
    run auto-mapping (D5)."""
    cand = _get_candidate(candidate_id)
    if cand is None:
        raise ValueError(f"candidate {candidate_id} not found")

    client_id = cand["client_id"]
    code = cand["code"]
    kind = cand["code_kind"]
    source = "bcct_observed"  # default — could be tuned per stream later

    with connect(user_id=actor) as conn, conn.cursor() as cur:
        cur.execute(
            """
            insert into hub.materials
              (client_id, material_code, name, category, status, source,
               code_kind, uom, production_source, supplier_hint)
            values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            on conflict (client_id, material_code) do update set
              name = excluded.name,
              category = excluded.category,
              status = excluded.status,
              code_kind = excluded.code_kind,
              uom = coalesce(excluded.uom, hub.materials.uom),
              production_source = coalesce(excluded.production_source,
                                           hub.materials.production_source),
              supplier_hint = coalesce(excluded.supplier_hint,
                                       hub.materials.supplier_hint)
            """,
            (client_id, code, name, category, status, source, kind,
             uom, production_source, supplier_hint),
        )
        cur.execute(
            "update hub.catalog_candidates set status='accepted', "
            " decided_at=now(), decided_by=%s, updated_at=now() "
            "where candidate_id=%s",
            (actor, candidate_id),
        )

    _auto_map_for_accept(client_id, code, kind)


def reject_candidate(
    candidate_id: int, *, actor: str, reason: str | None = None,
) -> None:
    """Mark candidate rejected. Sticky across refresh."""
    with connect(user_id=actor) as conn, conn.cursor() as cur:
        cur.execute(
            "update hub.catalog_candidates set status='rejected', "
            " decided_at=now(), decided_by=%s, decision_reason=%s, "
            " updated_at=now() "
            "where candidate_id=%s",
            (actor, reason, candidate_id),
        )


def unreject_candidate(candidate_id: int, *, actor: str) -> None:
    """Reset candidate from rejected/accepted back to pending."""
    with connect(user_id=actor) as conn, conn.cursor() as cur:
        cur.execute(
            "update hub.catalog_candidates set status='pending', "
            " decided_at=null, decided_by=null, decision_reason=null, "
            " updated_at=now() "
            "where candidate_id=%s",
            (candidate_id,),
        )
