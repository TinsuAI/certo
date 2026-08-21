"""End-to-end proof for #55 — real approvals against a throwaway client.

Unlike ui_smoke.py (which photographs states without submitting), this drives
the whole write path: seed a small pending queue on a disposable client, then
in a real browser select rows and approve (bulk), and open the modal and accept
(single) — screenshotting the before/after of each so the queue-shrink and the
success toast are visible.

It never touches a real client. The throwaway id ends in `-<8hex>`, which
`tests/conftest.py::_sweep_test_junk_clients` deletes even if this script dies
before its own cleanup.

Run with the dev server up on :8754:
    uv run python .ai/features/2026-07-18-catalog-selection-modal/e2e_smoke.py
"""
from __future__ import annotations

import asyncio
import os
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from playwright.async_api import async_playwright

from hub.app.database import connect
from hub.app.parsers.client_parser_rules import clear_rules_cache
from hub.app.stores.bcct_nb_codes import rebuild_for_client

BASE = "http://127.0.0.1:8754"
EMAIL = os.environ.get("DATA_HUB_SEED_EMAIL", "admin@data-hub.local")
PASSWORD = os.environ.get("DATA_HUB_SEED_PASSWORD", "admin123")
OUT = Path(__file__).resolve().parent / "screenshots"
OUT.mkdir(parents=True, exist_ok=True)

CLIENT = "e2e-catalog-" + uuid.uuid4().hex[:8]   # matches the conftest sweep

# HQ code + an NB code in the parens; the parser rule extracts the NB side, so
# each seed yields two derivable pending rows.
SEED = [
    ("D1", "AAA100", "Điện trở AAA (019.A100)"),
    ("D2", "BBB200", "Tụ điện BBB (019.B200)"),
    ("D3", "CCC300", "Cuộn cảm CCC (019.C300)"),
    ("D4", "DDD400", "Diode DDD (019.D400)"),
]


def seed():
    with connect() as conn, conn.cursor() as cur:
        cur.execute("insert into hub.clients (client_id, name) values (%s, %s) "
                    "on conflict do nothing", (CLIENT, "E2E Catalog Demo"))
        cur.execute(
            "insert into hub.client_parser_rules "
            "(client_id, output_field, priority, pattern, source_field, "
            " match_group, match_action, no_match_action, enabled, created_by) "
            "values (%s, 'internal_code', 10, '\\(([\\d\\.\\w\\-]+)\\)', "
            " 'goods_name', 1, 'capture', 'next_rule', true, 'e2e') "
            "on conflict do nothing", (CLIENT,))
        for decl, customs, goods in SEED:
            cur.execute(
                "insert into hub.bcct_rows (client_id, transaction_key, line_no,"
                " declaration_no, declaration_type, direction, "
                " registration_date, customs_code, goods_name, payload) "
                "values (%s, %s, '1', %s, 'E11', 'import', '2026-04-01', %s, %s,"
                " '{}'::jsonb)", (CLIENT, f"TX_{decl}", decl, customs, goods))
    clear_rules_cache()
    rebuild_for_client(CLIENT)


def teardown():
    with connect() as conn, conn.cursor() as cur:
        cur.execute("delete from hub.clients where client_id=%s", (CLIENT,))
    clear_rules_cache()


def pending_count():
    with connect() as conn, conn.cursor() as cur:
        cur.execute("select count(*) from hub.catalog_discovery(%s) "
                    "where status='pending'", (CLIENT,))
        return cur.fetchone()[0]


def material_count():
    with connect() as conn, conn.cursor() as cur:
        cur.execute("select count(*) from hub.materials where client_id=%s",
                    (CLIENT,))
        return cur.fetchone()[0]


async def run() -> int:
    page_url = f"{BASE}/clients/{CLIENT}/catalog/candidates"
    failures: list[str] = []
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        ctx = await browser.new_context(viewport={"width": 1440, "height": 900})
        await ctx.add_cookies([
            {"name": "data_hub_theme", "value": "light", "url": BASE},
            {"name": "data_hub_lang", "value": "vi", "url": BASE},
        ])
        page = await ctx.new_page()
        await page.goto(f"{BASE}/login")
        await page.fill('input[name="email"]', EMAIL)
        await page.fill('input[name="password"]', PASSWORD)
        await page.click('button[type="submit"]')
        await page.wait_for_load_state("networkidle")

        # ── Before ──
        await page.goto(page_url)
        await page.wait_for_load_state("networkidle")
        before_q = pending_count()
        print(f"  before: queue={before_q}, materials={material_count()}")
        await page.screenshot(path=str(OUT / "e2e_1_before.png"), full_page=True)

        # ── Bulk: check two rows, approve ──
        rows = page.locator(".row-check")
        await rows.nth(0).check()
        await rows.nth(1).check()
        await page.wait_for_timeout(150)
        await page.screenshot(path=str(OUT / "e2e_2_selected.png"),
                              full_page=True)
        await page.locator("#bulk-approve-btn").click()
        await page.wait_for_load_state("networkidle")
        after_bulk_q = pending_count()
        after_bulk_m = material_count()
        print(f"  after bulk approve of 2: queue={after_bulk_q}, "
              f"materials={after_bulk_m}")
        await page.screenshot(path=str(OUT / "e2e_3_after_bulk.png"),
                              full_page=True)
        if after_bulk_m < 2:
            failures.append(f"bulk approve created {after_bulk_m} materials, "
                            "expected >=2")
        if after_bulk_q >= before_q:
            failures.append("queue did not shrink after bulk approve")

        # ── Modal: single-row accept ──
        await page.locator(".js-accept-open").first.click()
        await page.wait_for_timeout(150)
        await page.screenshot(path=str(OUT / "e2e_4_modal_open.png"))
        # name may be empty for a bom-less row; fill to satisfy `required`.
        if not (await page.locator("#ad-name").input_value()):
            await page.fill("#ad-name", "Hàng duyệt qua modal")
        m_before = material_count()
        await page.locator('#accept-dialog button[type="submit"]').click()
        await page.wait_for_load_state("networkidle")
        m_after = material_count()
        print(f"  after modal accept: materials {m_before} -> {m_after}")
        await page.screenshot(path=str(OUT / "e2e_5_after_modal.png"),
                              full_page=True)
        if m_after <= m_before:
            failures.append("modal accept created no material")

        await browser.close()

    print(f"\nscreenshots -> {OUT}")
    if failures:
        print("FAILURES:\n  " + "\n  ".join(failures))
        return 1
    print("e2e: bulk approve + modal accept both wrote through, queue shrank.")
    return 0


def main() -> int:
    seed()
    try:
        return asyncio.run(run())
    finally:
        teardown()


if __name__ == "__main__":
    raise SystemExit(main())
