"""Phase 3 G — refresh-preview UI smoke screenshot.

Creates a Tier B + Tier A fixture artifact, logs in, navigates to the
/refresh/preview page, and captures the rendered plan.

Saves to .ai/features/2026-05-13-bom-refresh-preview/screenshots/
"""
from __future__ import annotations

import asyncio
import json
import secrets
from pathlib import Path

import psycopg
from playwright.async_api import async_playwright


BASE = "http://127.0.0.1:8754"
EMAIL = "admin@data-hub.local"
PASSWORD = "admin123"
CLIENT_ID = "growatt-vn"
PRODUCT = "TEST_TP_REFRESH_PREVIEW"

OUT = Path(".ai/features/2026-05-13-bom-refresh-preview/screenshots")
OUT.mkdir(parents=True, exist_ok=True)


def db():
    return psycopg.connect("host=/var/run/postgresql user=vp dbname=data_hub")


def cleanup():
    conn = db()
    with conn.cursor() as cur:
        cur.execute(
            "delete from hub.bom_artifact_rows where artifact_id in "
            "(select artifact_id from hub.bom_artifacts where "
            "client_id=%s and product_code=%s)",
            (CLIENT_ID, PRODUCT))
        cur.execute(
            "delete from hub.bom_edges where artifact_id in "
            "(select artifact_id from hub.bom_artifacts where "
            "client_id=%s and product_code=%s)",
            (CLIENT_ID, PRODUCT))
        cur.execute(
            "delete from hub.bom_artifacts where client_id=%s "
            "and product_code=%s",
            (CLIENT_ID, PRODUCT))
        cur.execute(
            "delete from hub.materials where client_id=%s "
            "and material_code in ('M_REFRESH_TIERA','M_REFRESH_TIERB',"
            "                        %s)",
            (CLIENT_ID, PRODUCT))
        conn.commit()
    conn.close()


def seed_fixture() -> str:
    """Build a stale derived artifact with mixed Tier A + Tier B rows.
    Returns the derived artifact_id."""
    conn = db()
    with conn.cursor() as cur:
        # Materials.
        cur.execute(
            "insert into hub.materials (client_id, material_code, name, "
            "category, status, uom) values "
            "(%s, %s, %s, 'tp', 'active', 'KG'), "
            "(%s, %s, %s, 'nvl', 'active', 'SETS'), "
            "(%s, %s, %s, 'nvl', 'active', 'KG') "
            "on conflict (client_id, material_code) do update set "
            "uom=excluded.uom",
            (CLIENT_ID, PRODUCT, PRODUCT,
             CLIENT_ID, "M_REFRESH_TIERA", "M_REFRESH_TIERA",
             CLIENT_ID, "M_REFRESH_TIERB", "M_REFRESH_TIERB"),
        )
        # Raw artifact + 2 edges.
        raw_id = "ba_rp_smoke_raw"
        cur.execute(
            "insert into hub.bom_artifacts (artifact_id, client_id, "
            "product_code, artifact_no, status, actor, intent, context, "
            "normalized_hash, row_count, source_bom_kind, flatten_status, "
            "flatten_strategy, source_channel, bom_variant_id, lineage, "
            "flatten_method, flatten_method_version, published_at) "
            "values (%s, %s, %s, 1, 'published', 'agency_staff', "
            "'asserted_technical', '{}', %s, 2, 'technical_raw', "
            "'non_flattened', 'no_strategy', 'agency_upload', 'default', "
            "'{}', 'as_provided', 'v1', now()) "
            "on conflict (artifact_id) do nothing",
            (raw_id, CLIENT_ID, PRODUCT, f"h_{raw_id}"),
        )
        cur.execute("delete from hub.bom_edges where artifact_id=%s", (raw_id,))
        cur.execute(
            "insert into hub.bom_edges (artifact_id, row_index, root_code, "
            "parent_code, child_code, qty_per_parent, uom) values "
            "(%s, 0, %s, %s, 'M_REFRESH_TIERA', 4.0, 'EA'), "
            "(%s, 1, %s, %s, 'M_REFRESH_TIERB', 7.0, 'EA')",
            (raw_id, PRODUCT, PRODUCT, raw_id, PRODUCT, PRODUCT),
        )
        # Derived stale.
        derived_id = "ba_rp_smoke_der"
        reasons = [{"dim": "catalog_category", "source_table": "hub.materials",
                    "source_pk": f"{CLIENT_ID}/seed",
                    "observed_at": "2026-05-13T00:00:00Z"}]
        cur.execute(
            "insert into hub.bom_artifacts (artifact_id, client_id, "
            "product_code, artifact_no, status, actor, intent, context, "
            "normalized_hash, row_count, source_bom_kind, flatten_status, "
            "flatten_strategy, source_channel, bom_variant_id, lineage, "
            "flatten_method, flatten_method_version, published_at, "
            "is_stale, stale_reasons, stale_first_at) "
            "values (%s, %s, %s, 1, 'published', 'agency_staff', "
            "'derived', '{}', %s, 0, 'technical_flattened', 'flattened', "
            "'technical_exploded', 'migration', 'default', '{}', "
            "'recursive_sql', '1', now(), true, %s::jsonb, now()) "
            "on conflict (artifact_id) do nothing",
            (derived_id, CLIENT_ID, PRODUCT, f"h_{derived_id}",
             json.dumps(reasons)),
        )
        conn.commit()
    conn.close()
    return derived_id


async def main():
    cleanup()
    derived_id = seed_fixture()
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        context = await browser.new_context(viewport={"width": 1200, "height": 900})
        page = await context.new_page()
        # Login via form post.
        await page.goto(f"{BASE}/login")
        await page.fill('input[name="email"]', EMAIL)
        await page.fill('input[name="password"]', PASSWORD)
        await page.click('button[type="submit"]')
        await page.wait_for_load_state("networkidle")
        # Refresh preview page.
        await page.goto(
            f"{BASE}/clients/{CLIENT_ID}/bom/artifact/{derived_id}/refresh/preview"
        )
        await page.wait_for_load_state("networkidle")
        await page.screenshot(path=str(OUT / "01_preview_mixed_tiers.png"),
                               full_page=True)
        print(f"saved {OUT / '01_preview_mixed_tiers.png'}")
        await browser.close()
    cleanup()


if __name__ == "__main__":
    asyncio.run(main())
