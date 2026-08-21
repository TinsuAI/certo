"""Persistence + refresh for hub.material_substitutes (Feature 4 MVP).

Sources implemented in this MVP: client_confirmed (P1), same_hs (P4),
trigram (P5a). Skipped: same_customs_diff_internal (P2 — needs
code_mappings join, deferred), prefix_rule (P3 — deferred),
embedding (P5b — needs pgvector, deferred).

Refresh policy: idempotent — re-running adds new candidates without
disturbing already-rejected pairs (rejected stays rejected; new
sources for the same pair coexist).
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Iterable

from hub.app.database import connect


# Score formula — keep in sync with brief Feature 4 + UI badge ordering.
_COMBINED_SCORE_SQL = """
case source
  when 'client_confirmed'             then 1.00
  when 'same_customs_diff_internal'   then 0.90
  when 'same_hs'                      then 0.85
  when 'manual_user'                  then 0.80
  when 'embedding'                    then 0.30 + 0.70 * coalesce(score, 0)
  when 'trigram'                      then 0.20 + 0.50 * coalesce(score, 0)
  when 'prefix_rule'                  then 0.40 + 0.40 * coalesce(score, 0)
end
"""


@dataclass(frozen=True)
class SubstituteCandidate:
    material_b_code: str
    name: str | None
    category: str | None
    hs_code: str | None
    sources: list[str]            # all source enum values that flagged this pair
    raw_scores: dict[str, float]  # source → raw similarity score (or 1.0 fixed)
    combined_score: float         # max combined across sources
    confirmed: bool               # any source has confirmed_at
    confirmed_at: datetime | None


# ── single-pair operations ─────────────────────────────────────────


def insert_candidate(
    *, client_id: str, material_a_code: str, material_b_code: str,
    source: str, score: float | None = None,
    confirmed_by: str | None = None,
) -> tuple[int, bool]:
    """Insert one substitute edge. Returns (id, created).

    `created=False` when an idempotent no-op (UNIQUE on
    client_id+a+b+source). Rejected pairs are NOT re-inserted — caller
    should consult `is_rejected` first if avoiding revival is important.
    """
    confirmed_at = datetime.now() if confirmed_by else None
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            """
            insert into hub.material_substitutes
              (client_id, material_a_code, material_b_code, source,
               score, confirmed_by, confirmed_at)
            values (%s, %s, %s, %s, %s, %s, %s)
            on conflict (client_id, material_a_code, material_b_code, source)
              do nothing
            returning id
            """,
            (client_id, material_a_code, material_b_code, source,
             score, confirmed_by, confirmed_at),
        )
        row = cur.fetchone()
        if row:
            return row[0], True
        cur.execute(
            """
            select id from hub.material_substitutes
             where client_id=%s and material_a_code=%s
               and material_b_code=%s and source=%s
            """,
            (client_id, material_a_code, material_b_code, source),
        )
        existing = cur.fetchone()
        return (existing[0] if existing else 0), False


def reject_pair(
    *, client_id: str, material_a_code: str, material_b_code: str,
    rejected_by: str,
) -> int:
    """Mark all sources for this pair as rejected. Returns rows updated."""
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            """
            update hub.material_substitutes
               set rejected_by=%s, rejected_at=now()
             where client_id=%s
               and material_a_code=%s
               and material_b_code=%s
               and rejected_at is null
            """,
            (rejected_by, client_id, material_a_code, material_b_code),
        )
        return cur.rowcount


def unreject_pair(
    *, client_id: str, material_a_code: str, material_b_code: str,
) -> int:
    """Clear rejection (e.g. user changed their mind)."""
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            """
            update hub.material_substitutes
               set rejected_by=null, rejected_at=null
             where client_id=%s
               and material_a_code=%s
               and material_b_code=%s
            """,
            (client_id, material_a_code, material_b_code),
        )
        return cur.rowcount


# ── ranked listing ─────────────────────────────────────────────────


def list_for_material(
    *, client_id: str, material_code: str,
    min_score: float = 0.0, include_rejected: bool = False,
    limit: int = 20,
) -> list[SubstituteCandidate]:
    """Return ranked substitute candidates for a material. Combines all
    sources per (a, b) pair, picks the highest combined_score across
    sources, returns sorted desc."""
    sql = f"""
      with edges as (
        select s.material_b_code,
               s.source,
               s.score as raw_score,
               ({_COMBINED_SCORE_SQL}) as combined_score,
               s.confirmed_at
          from hub.material_substitutes s
         where s.client_id = %(cid)s
           and s.material_a_code = %(code)s
           {"" if include_rejected else "and s.rejected_at is null"}
      ),
      grouped as (
        select material_b_code,
               array_agg(source order by combined_score desc) as sources,
               jsonb_object_agg(source, raw_score) as raw_scores,
               max(combined_score) as combined_score,
               max(confirmed_at) as confirmed_at,
               bool_or(confirmed_at is not null) as confirmed
          from edges
         group by material_b_code
      )
      select g.material_b_code,
             m.name, m.category, m.hs_code,
             g.sources, g.raw_scores, g.combined_score,
             g.confirmed, g.confirmed_at
        from grouped g
        left join hub.materials m
               on m.client_id = %(cid)s and m.material_code = g.material_b_code
       where g.combined_score >= %(min)s
       order by g.combined_score desc, g.material_b_code
       limit %(lim)s
    """
    with connect() as conn, conn.cursor() as cur:
        cur.execute(sql, {
            "cid": client_id, "code": material_code,
            "min": min_score, "lim": limit,
        })
        out: list[SubstituteCandidate] = []
        for row in cur.fetchall():
            (b, name, cat, hs, sources, raw_scores, score,
             confirmed, confirmed_at) = row
            out.append(SubstituteCandidate(
                material_b_code=b, name=name, category=cat, hs_code=hs,
                sources=list(sources or []),
                raw_scores={k: float(v) if v is not None else 1.0
                            for k, v in (raw_scores or {}).items()},
                combined_score=float(score),
                confirmed=bool(confirmed),
                confirmed_at=confirmed_at,
            ))
        return out


# ── refresh job ────────────────────────────────────────────────────


@dataclass
class RefreshStats:
    same_hs_inserted: int = 0
    trigram_inserted: int = 0
    embedding_inserted: int = 0
    rules_applied: list[str] = None
    rules_skipped: list[str] = None


def _client_rules(client_id: str) -> dict:
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "select substitute_rules from hub.clients where client_id=%s",
            (client_id,),
        )
        row = cur.fetchone()
        return row[0] if row and row[0] else {}


def refresh_candidates(
    *, client_id: str, trigram_threshold: float = 0.4,
    trigram_limit_per_material: int = 10,
    same_hs_max_group_size: int = 50,
) -> RefreshStats:
    """Materialize same_hs + trigram suggestions per client. Idempotent.
    Honors clients.substitute_rules toggles.

    `same_hs_max_group_size`: skip HS codes whose material count exceeds
    this cap. Generic HS codes like 73269099 ("other articles of iron
    or steel") accumulate thousands of materials with no real product
    affinity — exploding the same_hs join would produce N² pairs of
    noise. Cap surfaces the rule's value (small targeted groups) while
    preventing combinatorial blow-up.
    """
    rules = _client_rules(client_id)
    stats = RefreshStats(rules_applied=[], rules_skipped=[])

    if rules.get("p4_same_hs", True):
        with connect() as conn, conn.cursor() as cur:
            cur.execute(
                """
                with valid_hs as (
                    select hs_code, count(*) as n
                      from hub.materials
                     where client_id = %(cid)s
                       and hs_code is not null and hs_code <> ''
                       and status = 'active'
                     group by hs_code
                    having count(*) <= %(cap)s
                )
                insert into hub.material_substitutes
                  (client_id, material_a_code, material_b_code,
                   source, score)
                select %(cid)s, m1.material_code, m2.material_code,
                       'same_hs', 1.0
                  from hub.materials m1
                  join valid_hs vh on vh.hs_code = m1.hs_code
                  join hub.materials m2
                       on m2.client_id = m1.client_id
                      and m2.hs_code = m1.hs_code
                 where m1.client_id = %(cid)s
                   and m1.material_code <> m2.material_code
                   and m1.status = 'active'
                   and m2.status = 'active'
                on conflict (client_id, material_a_code,
                             material_b_code, source) do nothing
                """,
                {"cid": client_id, "cap": same_hs_max_group_size},
            )
            stats.same_hs_inserted = cur.rowcount
            conn.commit()
        stats.rules_applied.append("p4_same_hs")
    else:
        stats.rules_skipped.append("p4_same_hs")

    if rules.get("p5_embedding", False):
        # Per-material top-N nearest by cosine similarity. HNSW <=>
        # operator returns cosine distance (0 = identical, 1 = orthogonal,
        # 2 = opposite); similarity = 1 - distance.
        from hub.app import embedding as _embedding
        cfg = _embedding.get_client_config(client_id)
        with connect() as conn, conn.cursor() as cur:
            cur.execute(
                """
                insert into hub.material_substitutes
                  (client_id, material_a_code, material_b_code,
                   source, score)
                select %(cid)s, m1.material_code, sim.material_code,
                       'embedding', sim.s
                  from hub.materials m1
                  cross join lateral (
                    select m2.material_code,
                           1 - (m2.description_embedding
                                <=> m1.description_embedding) as s
                      from hub.materials m2
                     where m2.client_id = %(cid)s
                       and m2.material_code <> m1.material_code
                       and m2.description_embedding is not null
                       and m2.status = 'active'
                     order by m2.description_embedding
                              <=> m1.description_embedding
                     limit 10
                  ) sim
                 where m1.client_id = %(cid)s
                   and m1.description_embedding is not null
                   and m1.status = 'active'
                   and sim.s >= %(thr)s
                on conflict (client_id, material_a_code,
                             material_b_code, source) do update
                  set score = excluded.score
                """,
                {"cid": client_id, "thr": cfg.score_threshold},
            )
            stats.embedding_inserted = cur.rowcount
            conn.commit()
        stats.rules_applied.append("p5_embedding")
    else:
        stats.rules_skipped.append("p5_embedding")

    if rules.get("p5_trigram", True):
        # Per-material top-N similar codes via pg_trgm. Single SQL
        # uses LATERAL join to bound work to top N per material.
        with connect() as conn, conn.cursor() as cur:
            cur.execute(
                """
                insert into hub.material_substitutes
                  (client_id, material_a_code, material_b_code,
                   source, score)
                select %(cid)s, m1.material_code, sim.material_code,
                       'trigram', sim.s
                  from hub.materials m1
                  cross join lateral (
                    select m2.material_code,
                           similarity(m1.material_code, m2.material_code) as s
                      from hub.materials m2
                     where m2.client_id = %(cid)s
                       and m2.material_code <> m1.material_code
                       and m1.material_code %% m2.material_code
                       and m2.status = 'active'
                     order by similarity(m1.material_code, m2.material_code) desc
                     limit %(lim)s
                  ) sim
                 where m1.client_id = %(cid)s
                   and m1.status = 'active'
                   and sim.s >= %(thr)s
                on conflict (client_id, material_a_code,
                             material_b_code, source) do update
                  set score = excluded.score
                """,
                {"cid": client_id, "thr": trigram_threshold,
                 "lim": trigram_limit_per_material},
            )
            stats.trigram_inserted = cur.rowcount
            conn.commit()
        stats.rules_applied.append("p5_trigram")
    else:
        stats.rules_skipped.append("p5_trigram")

    return stats
