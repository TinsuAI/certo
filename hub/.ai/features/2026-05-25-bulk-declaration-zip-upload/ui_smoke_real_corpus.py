"""UI smoke driven by real Johnson TKN XLS corpus.

Mirrors `ui_smoke.py` but pulls 50 real TKN files from
`data/source_inventory/johnson-vn/2026-05-07-updated/Johnson/TKN/`,
adds 1 renamed-mismatch + 1 corrupted-parse-error so every status
bucket is populated, and walks the full operator flow with
fine-grained screenshots.

Screenshots land in `screenshots/real-corpus/` so they don't clobber
the synthesized smoke run.

Run with dev server up on :8754.
"""
from __future__ import annotations

import asyncio
import io
import os
import random
import sys
import zipfile
from pathlib import Path

sys.path.insert(0, os.fspath(Path(__file__).resolve().parents[3]))

from playwright.async_api import async_playwright

from app.database import connect
from app.routes.clients import upsert_client


BASE = "http://127.0.0.1:8754"
EMAIL = "admin@data-hub.local"
PASSWORD = "admin123"
CLIENT_ID = "johnson-bulk-smoke-vn"

JOHNSON_TKN = Path(
    "data/source_inventory/johnson-vn/2026-05-07-updated/Johnson/TKN"
)

OUT = Path(__file__).resolve().parent / "screenshots" / "real-corpus"
OUT.mkdir(parents=True, exist_ok=True)


def _build_real_corpus_zip(sample_size: int = 50) -> tuple[bytes, dict]:
    """Bundle `sample_size` real Johnson TKN XLS plus 2 synthetic
    non-OK members so the preview shows all four status buckets.

    Returns (zip_bytes, stats) where stats = {real, mismatch, parse_error}.
    """
    candidates = sorted(JOHNSON_TKN.glob("*.xls"))
    assert candidates, f"no XLS in {JOHNSON_TKN}"
    # Deterministic sampling so re-runs produce the same preview counts.
    random.seed(2026_05_25)
    picked = random.sample(candidates, min(sample_size, len(candidates)))

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for fp in picked:
            zf.writestr(fp.name, fp.read_bytes())
        # Mismatch: take a real file's bytes, rename to a wrong decl_no
        donor = picked[0]
        zf.writestr(
            "99999998_999999999999.xls",  # wrong decl_no in name
            donor.read_bytes(),
        )
        # Parse error: filename matches pattern but content is junk.
        zf.writestr(
            "99999999_888888888888.xls",
            b"this is intentionally not a valid XLS file",
        )
    return buf.getvalue(), {
        "real": len(picked), "mismatch": 1, "parse_error": 1,
    }


def _setup_client() -> None:
    upsert_client(
        client_id=CLIENT_ID, name="Johnson Bulk Smoke",
        tax_code=None, code_resolution_mode="identity",
        bom_proposal_mode="manual", bom_proposal_qty_tolerance_pct=5.0,
        bom_approver_tier="edit", status="active", notes=None,
    )


def _cleanup_client() -> None:
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "delete from hub.customs_declaration_files where client_id=%s",
            (CLIENT_ID,),
        )
        cur.execute("delete from hub.clients where client_id=%s", (CLIENT_ID,))


async def capture(page, slug: str) -> None:
    out = OUT / f"{slug}.png"
    await page.screenshot(path=str(out), full_page=True)
    print(f"  saved {out.relative_to(Path.cwd())}")


async def main() -> None:
    _setup_client()
    print(f"client {CLIENT_ID} ready")
    zip_bytes, stats = _build_real_corpus_zip(sample_size=50)
    print(
        f"corpus zip: {len(zip_bytes)/1024:.0f} KB · "
        f"{stats['real']} real + {stats['mismatch']} mismatch + "
        f"{stats['parse_error']} parse_error",
    )

    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            context = await browser.new_context(
                viewport={"width": 1440, "height": 900},
            )
            await context.add_cookies([
                {"name": "data_hub_theme", "value": "light", "url": BASE},
                {"name": "data_hub_lang", "value": "vi", "url": BASE},
            ])
            page = await context.new_page()
            await page.goto(f"{BASE}/login")
            await page.fill('input[name="email"]', EMAIL)
            await page.fill('input[name="password"]', PASSWORD)
            await page.click('button[type="submit"]')
            await page.wait_for_url(f"{BASE}/clients", timeout=5000)

            # 01 — Empty declarations index (fresh client, nothing yet)
            await page.goto(f"{BASE}/clients/{CLIENT_ID}/declarations")
            await page.wait_for_load_state("networkidle")
            await capture(page, "01_declarations_index_empty")

            # 02 — Upload page, default tab (single)
            await page.goto(
                f"{BASE}/clients/{CLIENT_ID}/declarations/upload",
            )
            await page.wait_for_load_state("networkidle")
            await capture(page, "02_upload_form_single_tab_default")

            # 03 — Bulk tab activated
            await page.click("#tab-bulk")
            await capture(page, "03_upload_form_bulk_tab")

            # 04 — File chosen + direction picked, before submit
            await page.set_input_files(
                '#panel-bulk input[name="file"]',
                files=[{
                    "name": "johnson_tkn_smoke.zip",
                    "mimeType": "application/zip",
                    "buffer": zip_bytes,
                }],
            )
            await page.select_option(
                '#panel-bulk select[name="direction"]', "import",
            )
            await capture(page, "04_bulk_form_ready")

            # 05 — Submit ZIP → preview page
            await page.click('#panel-bulk button[type="submit"]')
            await page.wait_for_url(
                "**/declarations/upload-zip", timeout=30000,
            )
            await page.wait_for_load_state("networkidle")
            await capture(page, "05_preview_first_upload_50_ok")

            # 06 — Scroll the preview to the non-OK detail table
            await page.evaluate(
                "() => document.querySelector('table.data-table')"
                "?.scrollIntoView({behavior:'instant', block:'start'})",
            )
            await capture(page, "06_preview_non_ok_table")

            # 07 — Confirm commit → declarations index with toast +
            #      populated list of 50 newly inserted declaration entries.
            await page.click('button:has-text("Xác nhận tải lên")')
            await page.wait_for_url(
                "**/declarations?**bulk_inserted=50**", timeout=30000,
            )
            await page.wait_for_load_state("networkidle")
            await capture(page, "07_index_after_first_commit")

            # 08 — Re-upload exact same ZIP: every real file is now in DB.
            await page.goto(
                f"{BASE}/clients/{CLIENT_ID}/declarations/upload#bulk",
            )
            await page.click("#tab-bulk")
            await page.set_input_files(
                '#panel-bulk input[name="file"]',
                files=[{
                    "name": "johnson_tkn_smoke.zip",
                    "mimeType": "application/zip",
                    "buffer": zip_bytes,
                }],
            )
            await page.select_option(
                '#panel-bulk select[name="direction"]', "import",
            )
            await page.click('#panel-bulk button[type="submit"]')
            await page.wait_for_url(
                "**/declarations/upload-zip", timeout=30000,
            )
            await page.wait_for_load_state("networkidle")
            await capture(page, "08_preview_second_upload_50_duplicate")

            # 09 — Confirm the re-upload → toast says "bỏ qua 50 trùng"
            await page.click('button:has-text("Xác nhận tải lên")')
            await page.wait_for_url(
                "**/declarations?**bulk_inserted=0**bulk_deduped=50**",
                timeout=30000,
            )
            await page.wait_for_load_state("networkidle")
            await capture(page, "09_index_after_dedup_commit")

            # 10 — Cancel flow: stage a third upload, hit Huỷ.
            await page.goto(
                f"{BASE}/clients/{CLIENT_ID}/declarations/upload#bulk",
            )
            await page.click("#tab-bulk")
            await page.set_input_files(
                '#panel-bulk input[name="file"]',
                files=[{
                    "name": "johnson_tkn_smoke.zip",
                    "mimeType": "application/zip",
                    "buffer": zip_bytes,
                }],
            )
            await page.select_option(
                '#panel-bulk select[name="direction"]', "import",
            )
            await page.click('#panel-bulk button[type="submit"]')
            await page.wait_for_url(
                "**/declarations/upload-zip", timeout=30000,
            )
            await page.wait_for_load_state("networkidle")
            # Now hit the Huỷ button on the preview page.
            await page.click('button:has-text("Huỷ")')
            # Match with or without `#bulk` fragment (the route appends
            # it so the operator stays on the bulk tab).
            await page.wait_for_url(
                "**/declarations/upload**", timeout=10000,
            )
            await page.wait_for_load_state("networkidle")
            await capture(page, "10_after_cancel_back_to_upload")

            await browser.close()
    finally:
        _cleanup_client()
        print(f"client {CLIENT_ID} cleaned up")


if __name__ == "__main__":
    asyncio.run(main())
