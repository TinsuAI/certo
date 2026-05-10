"""Real UI smoke for 3 ship items in this session:
1. BOM upload auto-detect → form has 'Tự động phát hiện' default + post lands on preview without mapping.
2. Manual_flat 4-shape → lineage shows 'manual_flat' badge + tooltip.
3. UI tombstone rename → catalog detail has '⌫ Loại khỏi danh mục' button + 'đã loại' badge; BOM artifact detail has 'Thời điểm thay thế' / 'Lý do thay thế' field labels for tombstoned artifacts.

Captures screenshots into /tmp/ui_smoke/ for visual confirmation.
"""
from __future__ import annotations

import asyncio
import io
import json
import sys
from pathlib import Path

import psycopg
from openpyxl import Workbook
from playwright.async_api import async_playwright


BASE = "http://127.0.0.1:8754"
EMAIL = "admin@data-hub.local"
PASSWORD = "admin123"
CLIENT_ID = "growatt-vn"

OUT = Path(".ai/features/2026-05-13-three-small-items/screenshots")
OUT.mkdir(parents=True, exist_ok=True)


def db():
    return psycopg.connect("host=/var/run/postgresql user=vp dbname=data_hub")


async def login(page):
    await page.goto(f"{BASE}/login")
    await page.fill('input[name="email"]', EMAIL)
    await page.fill('input[name="password"]', PASSWORD)
    # Login form submit — restrict to the form to avoid global header buttons.
    await page.locator('form:has(input[name="password"]) button[type="submit"]').click()
    await page.wait_for_load_state("networkidle")


def find_manual_flat_artifact() -> tuple[str, str] | None:
    """Look up an existing manual_flat artifact for assertion."""
    conn = db()
    with conn.cursor() as cur:
        cur.execute(
            "select client_id, artifact_id from hub.bom_artifacts "
            "where flatten_strategy='manual_flat_as_provided' "
            "  and tombstoned_at is null and status='published' "
            "limit 1",
        )
        r = cur.fetchone()
    conn.close()
    return r if r else None


def find_tombstoned_bom_artifact() -> tuple[str, str] | None:
    conn = db()
    with conn.cursor() as cur:
        cur.execute(
            "select client_id, artifact_id from hub.bom_artifacts "
            "where tombstoned_at is not null limit 1",
        )
        r = cur.fetchone()
    conn.close()
    return r if r else None


def find_tombstoned_material() -> tuple[str, str] | None:
    conn = db()
    with conn.cursor() as cur:
        cur.execute(
            "select client_id, material_code from hub.materials "
            "where status='tombstoned' limit 1",
        )
        r = cur.fetchone()
    conn.close()
    return r if r else None


def make_sheet_per_product_blob() -> bytes:
    """Build a workbook that the sheet_per_product adapter parses cleanly:
    one sheet per product, sheet title = product code."""
    wb = Workbook()
    ws = wb.active
    ws.title = "P-AUTO-SMOKE-1"
    ws.append(("Mã NVL", "Định mức", "ĐVT"))
    ws.append(("M-AUTO-A", 1, "kg"))
    ws.append(("M-AUTO-B", 2, "pcs"))
    ws2 = wb.create_sheet(title="P-AUTO-SMOKE-2")
    ws2.append(("Mã NVL", "Định mức", "ĐVT"))
    ws2.append(("M-AUTO-C", 0.5, "kg"))
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


async def smoke_upload_form_default(page) -> dict:
    """Test 1a: GET /bom/upload page; assert 'Tự động phát hiện' is the
    selected default in the profile dropdown."""
    await page.goto(f"{BASE}/clients/{CLIENT_ID}/bom/upload")
    await page.wait_for_load_state("networkidle")
    selected = await page.locator('select[name="profile"] option[selected]').get_attribute("value")
    label_text = await page.locator('select[name="profile"] option[selected]').text_content()
    await page.screenshot(path=str(OUT / "1a_upload_form_default.png"), full_page=True)
    return {"selected_value": selected, "selected_label": (label_text or "").strip()}


async def smoke_upload_auto_post(page) -> dict:
    """Test 1b: POST a sheet_per_product workbook with profile=auto;
    assert redirected to /bom/preview/<id> (not mapping)."""
    blob = make_sheet_per_product_blob()
    # Use page.evaluate to construct a multipart POST via fetch in browser context.
    # Easier: use page.set_input_files with the form, override the select to 'auto'.
    await page.goto(f"{BASE}/clients/{CLIENT_ID}/bom/upload")
    # Write blob to /tmp so set_input_files can ingest.
    p = OUT / "auto_smoke.xlsx"
    p.write_bytes(blob)
    await page.select_option('select[name="profile"]', "auto")
    await page.set_input_files('input[name="file"]', str(p))
    # Click the submit button inside the upload form (avoid global header
    # buttons matching `button[type=submit]`).
    await page.locator('form:has(input[name="file"]) button[type="submit"]').click()
    await page.wait_for_load_state("networkidle")
    url = page.url
    await page.screenshot(path=str(OUT / "1b_after_auto_upload.png"), full_page=True)
    return {"final_url": url}


async def smoke_manual_flat_badge(page, client_id: str, artifact_id: str) -> dict:
    await page.goto(f"{BASE}/clients/{client_id}/bom/artifact/{artifact_id}")
    await page.wait_for_load_state("networkidle")
    body = await page.content()
    badge_count = body.count("badge-shape-manual-flat")
    has_old_shallow_with_strategy = ('badge-shape-shallow' in body and
                                       'manual_flat_as_provided' in body)
    await page.screenshot(path=str(OUT / "2_manual_flat_badge.png"), full_page=True)
    return {
        "manual_flat_badge_count": badge_count,
        "regression_old_shallow_with_strategy": has_old_shallow_with_strategy,
    }


async def smoke_tombstone_bom_labels(page, client_id: str, artifact_id: str) -> dict:
    await page.goto(f"{BASE}/clients/{client_id}/bom/artifact/{artifact_id}")
    await page.wait_for_load_state("networkidle")
    body = await page.content()
    await page.screenshot(path=str(OUT / "3a_tombstoned_bom_labels.png"), full_page=True)
    return {
        "has_thoi_diem_thay_the": "Thời điểm thay thế" in body,
        "has_ly_do_thay_the": "Lý do thay thế" in body,
        "has_old_tombstoned_at_label": "Tombstoned at" in body,
        "has_old_tombstone_reason_label": "Tombstone reason" in body,
    }


async def smoke_tombstone_catalog_labels(page, client_id: str,
                                          material_code: str) -> dict:
    await page.goto(f"{BASE}/clients/{client_id}/catalog/{material_code}/detail")
    await page.wait_for_load_state("networkidle")
    body = await page.content()
    await page.screenshot(path=str(OUT / "3b_tombstoned_material_badge.png"),
                          full_page=True)
    return {
        "has_da_loai_badge": "đã loại" in body,
        "has_old_tombstoned_badge_text_visible": (
            ">tombstoned<" in body  # plain visible text, not in attrs
        ),
    }


async def smoke_catalog_button_label(page, client_id: str) -> dict:
    """Find an active material to confirm the '⌫ Loại khỏi danh mục'
    button label on its detail page."""
    conn = db()
    with conn.cursor() as cur:
        cur.execute(
            "select material_code from hub.materials "
            "where client_id=%s and status='active' "
            "  and category in ('nvl','tp','btp_sx','btp_mua') "
            "limit 1",
            (client_id,),
        )
        r = cur.fetchone()
    conn.close()
    if not r:
        return {"skipped": True, "reason": "no active material in fixture"}
    code = r[0]
    await page.goto(f"{BASE}/clients/{client_id}/catalog/{code}/detail")
    await page.wait_for_load_state("networkidle")
    body = await page.content()
    await page.screenshot(path=str(OUT / "3c_active_material_button.png"),
                          full_page=True)
    return {
        "material_code": code,
        "has_loai_button": "⌫ Loại khỏi danh mục" in body,
        "has_old_button": "⌫ Tombstone" in body,
    }


async def main():
    results: dict = {}
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        ctx = await browser.new_context(viewport={"width": 1400, "height": 900})
        page = await ctx.new_page()
        await login(page)

        results["1a_upload_form_default"] = await smoke_upload_form_default(page)
        results["1b_upload_auto_post"] = await smoke_upload_auto_post(page)

        mf = find_manual_flat_artifact()
        if mf:
            results["2_manual_flat_badge"] = await smoke_manual_flat_badge(page, *mf)
        else:
            results["2_manual_flat_badge"] = {"skipped": True}

        tb = find_tombstoned_bom_artifact()
        if tb:
            results["3a_tombstone_bom"] = await smoke_tombstone_bom_labels(page, *tb)
        else:
            results["3a_tombstone_bom"] = {"skipped": True}

        tm = find_tombstoned_material()
        if tm:
            results["3b_tombstone_material"] = await smoke_tombstone_catalog_labels(
                page, *tm)
        else:
            results["3b_tombstone_material"] = {"skipped": True}

        results["3c_catalog_button"] = await smoke_catalog_button_label(
            page, CLIENT_ID)

        await browser.close()

    print(json.dumps(results, indent=2, ensure_ascii=False))
    # Cleanup the throwaway upload from test 1b.
    conn = db()
    with conn.cursor() as cur:
        cur.execute(
            "delete from hub.upload_pending where client_id=%s "
            "  and parsed_rows::text like %s",
            (CLIENT_ID, "%P-AUTO-SMOKE-1%"))
        cur.execute(
            "delete from hub.file_uploads where client_id=%s "
            "  and original_filename='auto_smoke.xlsx'",
            (CLIENT_ID,))
        conn.commit()
    conn.close()


if __name__ == "__main__":
    asyncio.run(main())
