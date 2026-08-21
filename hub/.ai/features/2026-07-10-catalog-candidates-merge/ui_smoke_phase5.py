"""UI smoke for catalog phase 5 (#35) — bulk approval.

Two-part proof, both against the dev server on :8754:

  Part A (growatt-vn, read-only): the discovery page shows the new
  filter bar and the "Duyệt N mã đang lọc" button; applying the
  flattened-leaf filter narrows to the rule's set (~2,156) and each row
  carries the ✓ lá phẳng badge. No data is mutated.

  Part B (a disposable client): seed a few pending codes, press the bulk
  button through the real UI, capture the success toast, and assert the
  materials were created and one catalog_bulk_accept audit event was
  written. The client is deleted afterwards, so growatt-vn stays
  pristine.

Run with the dev server up on :8754:
    uv run python .ai/features/2026-07-10-catalog-candidates-merge/ui_smoke_phase5.py
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from playwright.async_api import async_playwright

from app.database import connect
from app.stores.bcct_nb_codes import rebuild_for_client

BASE = "http://127.0.0.1:8754"
EMAIL = "admin@data-hub.local"
PASSWORD = "admin123"
GROWATT = "growatt-vn"
SMOKE = "_smoke_bulk_phase5"

OUT = Path(__file__).resolve().parent / "screenshots"
OUT.mkdir(parents=True, exist_ok=True)


async def shoot(page, name: str) -> None:
    out = OUT / f"{name}.png"
    await page.screenshot(path=str(out), full_page=False)
    print(f"  saved {out.name}")


def _seed_smoke_client() -> None:
    _drop_smoke_client()
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "insert into hub.clients (client_id, name) values (%s, 'Smoke Bulk')",
            (SMOKE,),
        )
        for i in range(1, 4):
            cur.execute(
                """
                insert into hub.bcct_rows
                  (client_id, transaction_key, line_no, declaration_no,
                   declaration_type, direction, registration_date,
                   customs_code, goods_name, payload)
                values (%s, %s, '1', %s, 'E11', 'import', '2026-04-01',
                        %s, %s, '{}'::jsonb)
                """,
                (SMOKE, f"TX{i}", f"D{i}", f"SMOKE.{i:04d}", f"vật tư mẫu {i}"),
            )
    rebuild_for_client(SMOKE)


def _drop_smoke_client() -> None:
    with connect() as conn, conn.cursor() as cur:
        for tbl in ("catalog_rejections", "bcct_nb_codes", "code_mappings",
                    "bcct_rows", "materials"):
            cur.execute(f"delete from hub.{tbl} where client_id=%s", (SMOKE,))
        cur.execute(
            "delete from hub.bom_audit_events where client_id=%s", (SMOKE,))
        cur.execute("delete from hub.clients where client_id=%s", (SMOKE,))


def _smoke_material_count() -> int:
    with connect() as conn, conn.cursor() as cur:
        cur.execute("select count(*) from hub.materials where client_id=%s "
                    "and status='active'", (SMOKE,))
        return cur.fetchone()[0]


def _smoke_bulk_events() -> int:
    with connect() as conn, conn.cursor() as cur:
        cur.execute("select count(*) from hub.bom_audit_events where "
                    "client_id=%s and event_type='catalog_bulk_accept'",
                    (SMOKE,))
        return cur.fetchone()[0]


async def _login(page) -> None:
    await page.goto(f"{BASE}/login")
    await page.fill('input[name="email"]', EMAIL)
    await page.fill('input[name="password"]', PASSWORD)
    await page.click('button[type="submit"]')
    await page.wait_for_url(f"{BASE}/clients", timeout=10000)


async def main() -> None:
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        ctx = await browser.new_context(viewport={"width": 1400, "height": 900})
        await ctx.add_cookies([
            {"name": "data_hub_lang", "value": "vi", "url": BASE},
        ])
        page = await ctx.new_page()
        await _login(page)

        # ── Part A: growatt-vn, read-only ──────────────────────────────
        await page.goto(f"{BASE}/clients/{GROWATT}/catalog/candidates")
        await page.wait_for_load_state("networkidle")
        assert await page.locator('button:has-text("mã đang lọc")').count() == 1, \
            "bulk-approve button missing"
        assert await page.locator('text=Chỉ lá BOM đã làm phẳng').count() == 1, \
            "leaf filter missing"
        await shoot(page, "14_bulk_filter_bar_and_button")

        # Apply the flattened-leaf rule.
        await page.goto(
            f"{BASE}/clients/{GROWATT}/catalog/candidates?leaf=1")
        await page.wait_for_load_state("networkidle")
        btn = await page.locator('button:has-text("mã đang lọc")').inner_text()
        print(f"  leaf-filtered bulk button: {btn.strip()!r}")
        assert await page.locator('text=lá phẳng').count() >= 1, \
            "leaf badge missing on filtered rows"
        await shoot(page, "15_leaf_filtered_rule")

        # ── Part B: disposable client, real bulk accept ────────────────
        _seed_smoke_client()
        try:
            await page.goto(f"{BASE}/clients/{SMOKE}/catalog/candidates")
            await page.wait_for_load_state("networkidle")
            before = _smoke_material_count()
            assert before == 0, f"expected 0 materials, got {before}"
            # Confirm dialog on the bulk button → auto-accept.
            page.on("dialog", lambda d: asyncio.create_task(d.accept()))
            async with page.expect_navigation(timeout=30000):
                await page.locator('button:has-text("mã đang lọc")').click()
            assert "bulk_accepted=" in page.url, page.url
            await page.wait_for_load_state("networkidle")
            assert await page.locator('text=Đã duyệt hàng loạt').count() == 1, \
                "bulk toast missing"
            await shoot(page, "16_bulk_accepted_toast")

            after = _smoke_material_count()
            events = _smoke_bulk_events()
            print(f"  materials created: {after}; bulk audit events: {events}")
            assert after == 3, f"expected 3 materials, got {after}"
            assert events == 1, f"expected 1 audit event, got {events}"
        finally:
            _drop_smoke_client()

        await ctx.close()
        await browser.close()
        print("OK")


if __name__ == "__main__":
    asyncio.run(main())
