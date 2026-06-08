"""Batch embed materials for one client (Feature 4 P5b).

Walks `hub.materials` for the target client, builds the embedding text
per the configured template, and re-embeds rows where
`embedding_text_hash` is NULL or mismatches the recomputed hash for the
current config (model + template). Vectors land in
`description_embedding` (pgvector, dim=1536 by default).

Idempotent. Re-runnable. Dry-run is default; pass `--commit` to write.

Usage:
    uv run python scripts/embed_materials.py --client johnson-vn
    uv run python scripts/embed_materials.py --client johnson-vn --commit
    uv run python scripts/embed_materials.py --client johnson-vn --commit \\
        --limit 200    # smoke run
"""
from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, os.fspath(Path(__file__).resolve().parents[1]))

from app import embedding
from app.database import connect


def _select_dirty(client_id: str, limit: int | None,
                  template: str, model: str) -> list[dict]:
    """Return materials whose stored hash != current expected hash, plus
    rows with no vector at all. Compute hash in app code (template can
    drift independently of materials, so SQL-side hashing is fragile)."""
    sql = """
        select material_code, name, hs_code, uom as unit, category, notes,
               provenance,
               description_embedding is null as needs_initial,
               embedding_text_hash, embedding_model
          from hub.materials
         where client_id = %s and status = 'active'
         order by material_code
    """
    if limit is not None:
        sql += f" limit {int(limit)}"
    with connect() as conn, conn.cursor() as cur:
        cur.execute(sql, (client_id,))
        cols = [d.name for d in cur.description]
        rows = [dict(zip(cols, r)) for r in cur.fetchall()]

    dirty: list[dict] = []
    for r in rows:
        # Pull country_origin from provenance — Johnson catalog stores
        # it as a derived attribute via bcct_observed.
        prov = r.get("provenance") or {}
        country_origin = ""
        if isinstance(prov, dict):
            seen = prov.get("seen_in_bcct", {})
            if isinstance(seen, dict):
                country_origin = seen.get("origin") or ""
        r["country_origin"] = country_origin
        text = embedding.build_embedding_text(r, template)
        new_hash = embedding.text_hash(text, model)
        if (r["needs_initial"]
            or r["embedding_text_hash"] != new_hash
            or r["embedding_model"] != model):
            r["_text"] = text
            r["_new_hash"] = new_hash
            dirty.append(r)
    return dirty


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--client", required=True)
    ap.add_argument("--commit", action="store_true",
                    help="actually call API + write DB (default: dry-run)")
    ap.add_argument("--limit", type=int, default=None,
                    help="process at most N materials (smoke run)")
    ap.add_argument("--force", action="store_true",
                    help="re-embed ALL active materials, ignore hash. "
                         "Default: only dirty rows (hash mismatch / null vector)")
    args = ap.parse_args()

    cfg = embedding.get_client_config(args.client)
    if args.commit and not cfg.is_live:
        print(
            "ERROR: no API key configured. Set "
            "embedding.openrouter_api_key in /admin/settings/embedding "
            "before --commit.",
            file=sys.stderr,
        )
        return 2

    print(f"client_id    = {args.client}")
    print(f"model        = {cfg.model}")
    print(f"dim          = {cfg.dim}")
    print(f"batch_size   = {cfg.batch_size}")
    print(f"template     = {cfg.text_template!r}")
    print(f"commit       = {args.commit}")
    print(f"limit        = {args.limit or 'all'}")
    print()

    t0 = time.monotonic()
    if args.force:
        # Treat every active row as dirty by clearing the hash check —
        # `_select_dirty` reuses the same path and will mark all as dirty
        # because stored_hash != recomputed_hash after we wipe.
        with connect() as conn, conn.cursor() as cur:
            cur.execute(
                "update hub.materials set embedding_text_hash = null "
                "where client_id = %s and status = 'active'",
                (args.client,),
            )
            conn.commit()
        print(f"  --force: cleared embedding_text_hash for active rows")
    dirty = _select_dirty(args.client, args.limit, cfg.text_template, cfg.model)
    print(f"Materials to (re-)embed: {len(dirty)}")
    if not dirty:
        return 0
    if not args.commit:
        sample = dirty[:3]
        for s in sample:
            print(f"  e.g. {s['material_code']}: {s['_text'][:120]}")
        print("\n(dry-run) re-run with --commit to call API + write.")
        return 0

    client = embedding.OpenRouterClient(cfg)
    written = 0
    failed = 0
    started = time.monotonic()

    def _progress(done, total, batch_seconds):
        rate = done / max(time.monotonic() - started, 0.001)
        print(f"  [{done}/{total}] {rate:.1f}/s "
              f"(last batch {batch_seconds:.1f}s)")

    texts = [r["_text"] for r in dirty]
    try:
        vectors = client.embed_chunked(texts, on_progress=_progress)
    except embedding.EmbeddingError as exc:
        print(f"\nFATAL: {exc}", file=sys.stderr)
        return 1

    if len(vectors) != len(dirty):
        print(f"ERROR: vector count {len(vectors)} != dirty {len(dirty)}",
              file=sys.stderr)
        return 1

    # Write vectors back. One row per UPDATE — pgvector wants `vector`
    # text format on the wire.
    with connect() as conn, conn.cursor() as cur:
        for r, vec in zip(dirty, vectors):
            try:
                cur.execute(
                    """
                    update hub.materials
                       set description_embedding = %s::vector,
                           embedding_text_hash = %s,
                           embedding_model = %s,
                           embedding_at = now()
                     where client_id = %s and material_code = %s
                    """,
                    (embedding.vector_to_pg(vec), r["_new_hash"], cfg.model,
                     args.client, r["material_code"]),
                )
                written += 1
            except Exception as exc:
                failed += 1
                print(f"  ERR {r['material_code']}: {exc}",
                      file=sys.stderr)
        conn.commit()

    elapsed = time.monotonic() - t0
    print(f"\nDone in {elapsed:.1f}s. Written: {written}, failed: {failed}")

    # Auto-enable the embedding-source substitute rule on first
    # successful run. User who bothered to populate vectors clearly
    # wants them used; no point making them flip a hidden DB flag.
    if written > 0 and failed == 0:
        with connect() as conn, conn.cursor() as cur:
            cur.execute(
                "update hub.clients "
                "   set substitute_rules = "
                "       substitute_rules || '{\"p5_embedding\": true}'::jsonb "
                " where client_id = %s "
                "   and (substitute_rules->>'p5_embedding') is distinct from 'true'",
                (args.client,),
            )
            if cur.rowcount > 0:
                print(f"  → enabled p5_embedding rule for {args.client} "
                      f"(was off; auto-flipped on first successful embed).")
            conn.commit()

    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
