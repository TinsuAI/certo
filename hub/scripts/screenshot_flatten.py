"""UI walkthrough + screenshots for technical_flatten BOM upload.

Multiple scenarios in one run:

  A. Big seed — 8 demo cases in a single upload:
       1. simple 2-level TP                 → flattened / technical_exploded
       2. multi-level (3-level) TP          → flattened / technical_exploded
       3. dual-source TP (BCCT + child BOM) → 2 variants, staff picks
       4. non-flattened TP (missing child)  → non_flattened / no_strategy
       5. BTP-only entry                    → BTP version (no consuming TP)
       6. cycle (A→B→A)                     → cycle_detected unresolved
       7. UOM canonical g→kg conversion     → flattened with conversion evidence
       8. catalog-active NVL leaf           → catalog_imported_nvl evidence
  B. Duplicate re-upload (same blob)        → 0 new versions (idempotent)
  C. Johnson SAP fixture upload             → flatten over an exploded format
  D. Growatt Chinese-headers fixture upload → flatten over Vietnamese parser path

Output: data/screenshots/flatten_*.png  (light + dark themes for the main case)

Run: uv run python scripts/screenshot_flatten.py
"""
from __future__ import annotations

import asyncio
import io
import shutil
from pathlib import Path

import openpyxl
from playwright.async_api import async_playwright

from hub.app.database import connect


BASE = "http://127.0.0.1:8754"
EMAIL = "admin@data-hub.local"
PASSWORD = "admin123"
CLIENT = "ui_flat_test"

OUT = Path(__file__).resolve().parent.parent / "data" / "screenshots"
OUT.mkdir(parents=True, exist_ok=True)


def _xlsx(rows: list[tuple]) -> bytes:
    wb = openpyxl.Workbook()
    ws = wb.active
    for r in rows:
        ws.append(list(r))
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def seed_db():
    """Idempotent setup. Drop + recreate the test client so screenshots
    are reproducible from a clean slate."""
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute("delete from hub.clients where client_id = %s", (CLIENT,))
            cur.execute(
                """
                insert into hub.clients (client_id, name, code_resolution_mode)
                values (%s, %s, 'identity')
                """,
                (CLIENT, "UI flatten test"),
            )
            # Materials catalog: leafs in kg, BTPs, plus a g-unit material
            # that triggers UOM conversion when BOM rows arrive in g.
            for code, cat, unit in [
                # NVL leaves
                ("UI_NVL-1",      "nvl",    "kg"),
                ("UI_NVL-2",      "nvl",    "kg"),
                ("UI_NVL-3",      "nvl",    "kg"),
                ("UI_NVL-G",      "nvl",    "kg"),   # canonical kg → BOM row in g
                ("UI_NVL-CAT",    "nvl",    "kg"),   # active catalog leaf
                # BTPs
                ("UI_BTP-DUAL",   "btp_sx", "kg"),   # has BCCT import → dual-source
                ("UI_BTP-PURE",   "btp_sx", "kg"),
                ("UI_BTP-MID",    "btp_sx", "kg"),   # middle of 3-level chain
                ("UI_BTP-ORPHAN", "btp_sx", "kg"),   # uploaded standalone (BTP-only)
                # Cycle pair
                ("UI_CYC-A",      "btp_sx", "kg"),
                ("UI_CYC-B",      "btp_sx", "kg"),
            ]:
                cur.execute(
                    """
                    insert into hub.materials (client_id, material_code, category, uom, status)
                    values (%s, %s, %s, %s, 'active')
                    """,
                    (CLIENT, code, cat, unit),
                )
            # BCCT import evidence ONLY for UI_BTP-DUAL → triggers dual-source.
            cur.execute(
                """
                insert into hub.bcct_rows
                  (client_id, transaction_key, line_no, registration_date,
                   declaration_no, declaration_type, direction,
                   customs_code, internal_code, goods_name)
                values (%s, 'UI_TX', '1', '2026-01-01',
                        'UI_DECL', 'E11', 'import',
                        'UI_BTP-DUAL', 'UI_BTP-DUAL', 'imported BTP')
                """,
                (CLIENT,),
            )


async def screenshot_full(page, slug: str):
    out = OUT / f"flatten_{slug}.png"
    await page.screenshot(path=str(out), full_page=True)
    print(f"  saved {out}")


async def login(page):
    await page.goto(f"{BASE}/login")
    await page.fill('input[name="email"]', EMAIL)
    await page.fill('input[name="password"]', PASSWORD)
    await page.click('button[type="submit"]')
    await page.wait_for_load_state("networkidle")


async def upload_and_preview(page, blob_path: Path, slug: str,
                             theme: str = "light") -> str | None:
    """Upload a workbook with technical_flatten profile, return pending_id
    extracted from the URL after upload. Screenshots upload form +
    preview at given theme."""
    await page.goto(f"{BASE}/clients/{CLIENT}/bom/upload")
    await page.wait_for_load_state("networkidle")
    await page.select_option('select[name="profile"]', "technical_flatten")
    await page.set_input_files('input[type="file"]', str(blob_path.resolve()))
    await page.locator('form[action*="/bom/upload"] button[type="submit"]').click()
    await page.wait_for_load_state("networkidle")
    if "/flatten-preview/" not in page.url:
        # Parse error or non-flatten redirect.
        print(f"  ! non-flatten redirect: {page.url}")
        await screenshot_full(page, f"{slug}_unexpected_{theme}")
        return None
    await screenshot_full(page, f"{slug}_preview_{theme}")
    return page.url.split("/")[-1]


async def confirm_all_decisions(page):
    """Tick every confirm checkbox on the preview page. Used for the
    happy-path demo so the page screenshots show what materialization
    would look like with everything green-lit."""
    checkboxes = page.locator('input[type="checkbox"][name^="confirm_"]')
    count = await checkboxes.count()
    for i in range(count):
        await checkboxes.nth(i).check()


async def click_materialize(page):
    await page.locator(
        'form[action*="/flatten-preview/"] button[type="submit"]:has-text("Materialize")'
    ).click()
    await page.wait_for_load_state("networkidle")


async def main():
    seed_db()
    print("seed: ok")

    # ── Scenario A: comprehensive in one upload ────────────────────
    blob_a = _xlsx([
        ("Mã SP",        "Mã NVL",       "Định mức", "ĐVT"),
        # 1. Simple 2-level: TP-PURE → BTP-PURE → NVL-1
        ("UI_TP-PURE",   "UI_BTP-PURE",  2,          "kg"),
        ("UI_BTP-PURE",  "UI_NVL-1",     0.4,        "kg"),
        # 2. Multi-level: TP-DEEP → BTP-MID → BTP-PURE → NVL-1, 2
        ("UI_TP-DEEP",   "UI_BTP-MID",   1,          "kg"),
        ("UI_BTP-MID",   "UI_BTP-PURE",  3,          "kg"),
        ("UI_BTP-MID",   "UI_NVL-2",     0.7,        "kg"),
        # 3. Dual-source: TP-DUAL → BTP-DUAL (has BCCT-import + child BOM)
        ("UI_TP-DUAL",   "UI_BTP-DUAL",  1,          "kg"),
        ("UI_BTP-DUAL",  "UI_NVL-3",     0.6,        "kg"),
        # 4. Non-flattened: TP-MISSING → UI_GHOST (no evidence anywhere)
        ("UI_TP-MISSING","UI_GHOST",     1,          "kg"),
        # 5. BTP-only orphan upload (no consuming TP) — still gets a version
        ("UI_BTP-ORPHAN","UI_NVL-1",     0.5,        "kg"),
        # 6. Cycle: CYC-A ↔ CYC-B
        ("UI_CYC-A",     "UI_CYC-B",     1,          "kg"),
        ("UI_CYC-B",     "UI_CYC-A",     1,          "kg"),
        # 7. UOM conversion (g → kg) — global canonical
        ("UI_TP-UOM",    "UI_NVL-G",     250,        "g"),
        # 8. Catalog-active NVL leaf as direct child
        ("UI_TP-CAT",    "UI_NVL-CAT",   0.9,        "kg"),
    ])
    blob_path = OUT / "_flatten_input_main.xlsx"
    blob_path.write_bytes(blob_a)

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)

        # Light + dark theme captures of the redesigned preview.
        for theme in ("light", "dark"):
            context = await browser.new_context(viewport={"width": 1440, "height": 1500})
            await context.add_cookies([
                {"name": "data_hub_lang",  "value": "vi",    "url": BASE},
                {"name": "data_hub_theme", "value": theme,   "url": BASE},
            ])
            page = await context.new_page()
            await login(page)

            pending_id = await upload_and_preview(
                page, blob_path, slug="A_main_redesign", theme=theme,
            )

            if theme == "light":
                # Confirm all + screenshot the "decided" state, then click
                # materialize.
                await confirm_all_decisions(page)
                await screenshot_full(page, "A_main_decided_light")
                # Pick "purchased_btp_as_leaf" for every dual-source choice.
                duals = page.locator(
                    'select[name^="choose_"]'
                ).filter(has=page.locator('option[value="purchased_btp_as_leaf"]'))
                for i in range(await duals.count()):
                    await duals.nth(i).select_option("purchased_btp_as_leaf")
                # Pick "publish_with_review_required" for every non_flattened
                # (TP-MISSING + CYC-A + CYC-B all need this gate to land).
                nfs = page.locator(
                    'select[name^="choose_"]'
                ).filter(has=page.locator('option[value="publish_with_review_required"]'))
                for i in range(await nfs.count()):
                    await nfs.nth(i).select_option("publish_with_review_required")
                await click_materialize(page)
                await screenshot_full(page, "A_main_after_confirm_light")
                # Visit the BOM list page (default = "All" filter)
                await page.goto(f"{BASE}/clients/{CLIENT}/bom")
                await page.wait_for_load_state("networkidle")
                await screenshot_full(page, "A_main_list_all_light")
                # Click the "non_flattened" filter chip and snap again.
                await page.locator('.filter-chip[data-filter="non_flattened"]').click()
                await screenshot_full(page, "A_main_list_nonflat_filter_light")
                # And the "flattened" filter
                await page.locator('.filter-chip[data-filter="flattened"]').click()
                await screenshot_full(page, "A_main_list_flat_filter_light")
            else:
                # Dark: BOM list too — covers the staleness bar dark fix.
                await page.goto(f"{BASE}/clients/{CLIENT}/bom")
                await page.wait_for_load_state("networkidle")
                await screenshot_full(page, "A_main_list_all_dark")
            await context.close()

        # ── Scenario B: duplicate upload — idempotency ────────────
        context = await browser.new_context(viewport={"width": 1440, "height": 1100})
        await context.add_cookies([
            {"name": "data_hub_lang",  "value": "vi",    "url": BASE},
            {"name": "data_hub_theme", "value": "light", "url": BASE},
        ])
        page = await context.new_page()
        await login(page)

        # Re-upload the exact same file. Engine produces same FlattenResult.
        # On confirm, create_artifact's idempotency lookup returns the existing
        # artifact_ids → 0 new rows in bom_artifacts.
        with connect() as conn, conn.cursor() as cur:
            cur.execute(
                "select count(*) from hub.bom_artifacts where client_id = %s",
                (CLIENT,),
            )
            (n_before,) = cur.fetchone()

        pending_id = await upload_and_preview(
            page, blob_path, slug="B_duplicate", theme="light",
        )
        await confirm_all_decisions(page)
        duals = page.locator('select[name^="choose_"]').filter(
            has=page.locator('option[value="purchased_btp_as_leaf"]'))
        for i in range(await duals.count()):
            await duals.nth(i).select_option("purchased_btp_as_leaf")
        nfs = page.locator('select[name^="choose_"]').filter(
            has=page.locator('option[value="publish_with_review_required"]'))
        for i in range(await nfs.count()):
            await nfs.nth(i).select_option("publish_with_review_required")
        await click_materialize(page)
        await screenshot_full(page, "B_duplicate_after_confirm")

        with connect() as conn, conn.cursor() as cur:
            cur.execute(
                "select count(*) from hub.bom_artifacts where client_id = %s",
                (CLIENT,),
            )
            (n_after,) = cur.fetchone()
        print(f"Idempotent re-upload: before={n_before}, after={n_after} "
              f"(delta={n_after - n_before}; expect 0)")
        await context.close()

        # ── Scenario C: Johnson SAP fixture (technical_flatten path) ──
        johnson_fixture = Path(__file__).resolve().parent.parent / "tests" / "fixtures" / "edge_cases" / "johnson_sap_english_headers.xlsx"
        if johnson_fixture.exists():
            context = await browser.new_context(viewport={"width": 1440, "height": 1300})
            await context.add_cookies([
                {"name": "data_hub_lang",  "value": "vi",    "url": BASE},
                {"name": "data_hub_theme", "value": "light", "url": BASE},
            ])
            page = await context.new_page()
            await login(page)
            await upload_and_preview(
                page, johnson_fixture, slug="C_johnson", theme="light",
            )
            await context.close()

        # ── Scenario D: Growatt Chinese-headers fixture ──
        growatt_fixture = Path(__file__).resolve().parent.parent / "tests" / "fixtures" / "edge_cases" / "growatt_bom_chinese_headers.xlsx"
        if growatt_fixture.exists():
            context = await browser.new_context(viewport={"width": 1440, "height": 1300})
            await context.add_cookies([
                {"name": "data_hub_lang",  "value": "vi",    "url": BASE},
                {"name": "data_hub_theme", "value": "light", "url": BASE},
            ])
            page = await context.new_page()
            await login(page)
            await upload_and_preview(
                page, growatt_fixture, slug="D_growatt", theme="light",
            )
            await context.close()

        await browser.close()

    # Print final DB state.
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            """
            select product_code, source_bom_kind, flatten_status,
                   flatten_strategy, artifact_no, display_label
            from hub.bom_artifacts where client_id = %s
            order by product_code, artifact_no
            """,
            (CLIENT,),
        )
        print("\nMaterialized versions:")
        for r in cur.fetchall():
            print(f"  {r}")


if __name__ == "__main__":
    asyncio.run(main())
