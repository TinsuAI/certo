"""UI smoke: NXT + year-end inventory tier.

Drives the real upload → preview → confirm flow for both modules against the
system-standard templates, plus the browse-detail views, capturing:
  1. NXT upload form (Năm required)   4. Inventory upload form (Ngày chốt required)
  2. NXT preview (parsed)             5. Inventory preview (parsed, variance flagged)
  3. NXT list (Năm col, clickable)    6. Inventory list (clickable)
  7. admin adapter registry           8. NXT column-mapping page
  9. NXT detail (lines + mã → Catalog cross-link)
 10. Inventory detail (lines + mã → Catalog cross-link)

Run with the dev server up on :8754 (local-socket DB):
    uv run python .ai/features/2026-06-14-nxt-inventory-tier/ui_smoke.py
"""
from __future__ import annotations

import asyncio
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from playwright.async_api import async_playwright  # noqa: E402

from app.parsers.nxt_adapters.system_template import (  # noqa: E402
    render_template_xlsx as render_nxt,
)
from app.parsers.inventory_adapters.system_template import (  # noqa: E402
    render_template_xlsx as render_inv,
)
from datetime import date  # noqa: E402

from app.database import connect  # noqa: E402
from app.stores import inventory_snapshots as inv_store  # noqa: E402
from app.stores import nxt as nxt_store  # noqa: E402

# Self-contained cross-link demo: a throwaway client where we control both the
# catalog and the NXT/inventory codes, so the mã → Catalog links resolve (real
# ingested data uses codes that don't yet match the catalog — the lossy
# best-effort join, a separate data-normalization gap). Seeded + dropped here.
XLINK_DEMO = "nxt-xlink-demo"
# (code, name, in_catalog?) — two resolve to the catalog, one stays plain text.
DEMO_CODES = [
    ("NVL-100", "Nhựa ABS", True),
    ("NVL-200", "Thép cuộn", True),
    ("NVL-900", "Mã chưa có trong Danh Mục", False),
]


def _seed_xlink_demo() -> tuple[str, str]:
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "insert into hub.clients (client_id, name) values (%s, %s) "
            "on conflict (client_id) do nothing",
            (XLINK_DEMO, "NXT cross-link demo"))
        for code, name, in_cat in DEMO_CODES:
            if in_cat:
                cur.execute(
                    "insert into hub.materials (client_id, material_code, name, "
                    "category, status, uom) values (%s, %s, %s, 'nvl', 'active', "
                    "'KG') on conflict do nothing", (XLINK_DEMO, code, name))
    nxt_lines = [{"internal_code": c, "name": n, "uom": "KG", "opening": 100,
                  "inbound_total": 50, "outbound_total": 30,
                  "closing_reported": 120, "reported_role": "nvl"}
                 for c, n, _ in DEMO_CODES]
    inv_lines = [{"code": c, "name": n, "uom": "KG", "warehouse": "Kho A",
                  "qty_book": 120, "qty_physical": 118} for c, n, _ in DEMO_CODES]
    art_id = nxt_store.create_artifact(
        client_id=XLINK_DEMO, period_year=2025, lines=nxt_lines,
        period_from=date(2025, 1, 1), period_to=date(2025, 12, 31),
        source_kind="demo", adapter_name="demo")
    snap_id = inv_store.create_snapshot(
        client_id=XLINK_DEMO, snapshot_date=date(2025, 12, 31), lines=inv_lines,
        source_kind="demo", adapter_name="demo")
    return art_id, snap_id


def _drop_xlink_demo():
    with connect() as conn, conn.cursor() as cur:
        cur.execute("delete from hub.clients where client_id=%s", (XLINK_DEMO,))

BASE = "http://127.0.0.1:8754"
EMAIL = "admin@data-hub.local"
PASSWORD = "admin123"
CLIENT = "growatt-vn"
OUT = Path(__file__).resolve().parent / "screenshots"
OUT.mkdir(parents=True, exist_ok=True)
TMP = Path(tempfile.mkdtemp())


def _write(name: str, blob: bytes) -> str:
    p = TMP / name
    p.write_bytes(blob)
    return str(p)


def _build_weird_nxt() -> bytes:
    """A file with headers outside the alias list → routes to the mapping page."""
    import io
    import openpyxl
    wb = openpyxl.Workbook(); ws = wb.active; ws.title = "Sheet1"
    for ci, h in enumerate(["Code", "Name", "Unit", "Begin", "In", "Out", "End"], 1):
        ws.cell(1, ci, h)
    ws.append(["MAT-01", "Thép tấm", "KG", 1000, 500, 300, 1200])
    ws.append(["MAT-02", "Ốc vít", "PCE", 5000, 2000, 1500, 5500])
    out = io.BytesIO(); wb.save(out)
    return out.getvalue()


async def shot(page, slug: str):
    await page.wait_for_load_state("networkidle")
    await page.screenshot(path=str(OUT / f"{slug}.png"), full_page=True)
    print(f"saved {slug}.png")


async def main():
    nxt_file = _write("mau-nxt.xlsx", render_nxt())
    inv_file = _write("mau-ton.xlsx", render_inv())
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(viewport={"width": 1500, "height": 950})
        await context.add_cookies([
            {"name": "data_hub_lang", "value": "vi", "url": BASE},
            {"name": "data_hub_theme", "value": "light", "url": BASE},
        ])
        page = await context.new_page()
        await page.goto(f"{BASE}/login")
        await page.fill('input[name="email"]', EMAIL)
        await page.fill('input[name="password"]', PASSWORD)
        await page.click('button[type="submit"]')
        await page.wait_for_url(f"{BASE}/clients", timeout=8000)

        # ── NXT ──
        await page.goto(f"{BASE}/clients/{CLIENT}/nxt/upload")
        await shot(page, "01_nxt_upload")
        await page.set_input_files('input[name="file"]', nxt_file)
        await page.fill('input[name="period_year"]', "2025")
        await page.fill('input[name="period_from"]', "2025-01-01")
        await page.fill('input[name="period_to"]', "2025-12-31")
        await page.click('button:has-text("Tải lên & xem trước")')
        await page.wait_for_url("**/nxt/preview/**", timeout=8000)
        await shot(page, "02_nxt_preview")
        await page.click('button:has-text("Xác nhận lưu")')
        await page.wait_for_url(f"{BASE}/clients/{CLIENT}/nxt**", timeout=8000)
        await shot(page, "03_nxt_list")

        # ── Inventory ──
        await page.goto(f"{BASE}/clients/{CLIENT}/inventory-snapshots/upload")
        await shot(page, "04_inventory_upload")
        await page.set_input_files('input[name="file"]', inv_file)
        await page.fill('input[name="snapshot_date"]', "2025-12-31")
        await page.click('button:has-text("Tải lên & xem trước")')
        await page.wait_for_url("**/inventory-snapshots/preview/**", timeout=8000)
        await shot(page, "05_inventory_preview")
        await page.click('button:has-text("Xác nhận lưu")')
        await page.wait_for_url(f"{BASE}/clients/{CLIENT}/inventory-snapshots**", timeout=8000)
        await shot(page, "06_inventory_list")

        # ── Admin adapter registry (Web-UI management) ──
        await page.goto(f"{BASE}/admin/settlement-adapters")
        await shot(page, "07_admin_adapter_registry")

        # ── Column-mapping page (unknown headers → manual_generic) ──
        weird = _write("weird-nxt.xlsx", _build_weird_nxt())
        await page.goto(f"{BASE}/clients/{CLIENT}/nxt/upload")
        await page.set_input_files('input[name="file"]', weird)
        await page.fill('input[name="period_year"]', "2025")
        await page.click('button:has-text("Tải lên & xem trước")')
        await page.wait_for_url("**/nxt/upload/mapping/**", timeout=8000)
        await shot(page, "08_nxt_column_mapping")

        # ── Detail views (browse ingested lines + mã → Catalog cross-link) ──
        art_id, snap_id = _seed_xlink_demo()
        try:
            await page.goto(f"{BASE}/clients/{XLINK_DEMO}/nxt/{art_id}")
            await shot(page, "09_nxt_detail")
            await page.goto(
                f"{BASE}/clients/{XLINK_DEMO}/inventory-snapshots/{snap_id}")
            await shot(page, "10_inventory_detail")
        finally:
            _drop_xlink_demo()

        await browser.close()


if __name__ == "__main__":
    asyncio.run(main())
