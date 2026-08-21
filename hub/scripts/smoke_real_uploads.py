"""Drive real BOM + BQD files through the live UI; capture screenshots.

Maps `/tmp/dh_real_data/{company}/*.{xlsx,xls}` files onto seeded clients
and uploads each via the actual web form. Screenshots are saved per
company × entity to `data/screenshots/real_uploads/`.

Run:
    DATA_HUB_REAL_DATA_DIR=/tmp/dh_real_data \
        uv run python scripts/smoke_real_uploads.py

Server must be live on 127.0.0.1:8754. Login is admin@data-hub.local /
admin123. Each upload reports its outcome (200 + redirect, 400 parse
error, etc.) so the script doubles as a smoke test for the HTTP layer.
"""
from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

from playwright.async_api import async_playwright

BASE = "http://127.0.0.1:8754"
EMAIL = "admin@data-hub.local"
PASSWORD = "admin123"

OUT = Path(__file__).resolve().parent.parent / "data" / "screenshots" / "real_uploads"
OUT.mkdir(parents=True, exist_ok=True)

REAL_DIR = Path(os.environ.get("DATA_HUB_REAL_DATA_DIR", "/tmp/dh_real_data"))

# Maps client business name → seeded client_id in this DB.
CLIENT_IDS = {
    "growatt": "growatt-vn",
    "johnson": "johnson-vn",
    "dke": "dke-vietnam-d0e3",
    "dothanh": "do-thanh-vietnam-2614",
}

# Upload matrix. Each entry: (company, entity, profile_or_None, rel_path,
# expected_outcome). Order matters: BQD before BOM lets BCCT-derived
# code mappings exist when BOM rows reference materials.
JOBS = [
    # Growatt — BQD (Vietnamese N-to-N mappings)
    ("growatt", "bqd", None, "growatt/bqd_tp.xlsx",  "ok"),
    ("growatt", "bqd", None, "growatt/bqd_nvl.xlsx", "ok"),
    # DKE — BQD (Bug B fix: 'Mã ERP' / 'Mã NPL/TP' aliases now wired)
    ("dke",     "bqd", None, "dke/bqd.xls",          "ok"),
    # Growatt — Catalog (DS NVL + DS SP curated fixtures)
    ("growatt", "catalog", None, "growatt/catalog_nvl.xlsx", "ok"),
    ("growatt", "catalog", None, "growatt/catalog_sp.xlsx",  "ok"),
    # Johnson — BOM (synthetic SAP fixture)
    ("johnson", "bom", "johnson_sap_exploded", "johnson/bom_sap.xlsx", "ok"),
    # Growatt — BOM TP + BTP (Bug A fix: header_row alias-aware scoring
    # now picks the real header row past the leading-empty STT cell)
    ("growatt", "bom", "manual_flat", "growatt/bom_tp.xlsx",  "ok"),
    ("growatt", "bom", "manual_flat", "growatt/bom_btp.xlsx", "ok"),
    # Growatt — BCCT (Phase 2: all-NEW path now goes through preview gate
    # too, not only the existing UPDATED/DELETED flow). Uses the small
    # manual_test fixture (MAN_C1_* keys won't conflict with real data).
    ("growatt", "bcct", None, "manual_test/bcct_baseline.xlsx", "ok"),
]


async def login(page) -> None:
    await page.goto(f"{BASE}/login")
    await page.fill('input[name="email"]', EMAIL)
    await page.fill('input[name="password"]', PASSWORD)
    await page.click('button[type="submit"]')
    await page.wait_for_url(f"{BASE}/clients", timeout=5000)


async def shot(page, slug: str) -> Path:
    out = OUT / f"{slug}.png"
    await page.screenshot(path=str(out), full_page=True)
    print(f"  📸 {out}")
    return out


async def _submit_and_classify(
    page, *, post_url: str, list_url: str, slug: str,
    preview_pattern: str | None = None,
) -> str:
    """Submit the upload form. Capture status from the POST response and end-state.

    Phase 2 universal preview: upload now redirects to a preview page; this
    helper auto-clicks the primary "Save" button to drive through preview to
    list. `preview_pattern` is a substring expected in the preview URL
    (e.g., "/bqd/preview/"). When None, the legacy direct-redirect flow
    applies. Captures separate screenshots for the preview state.

    Returns 'ok' (303 chain → list page), 'parse_error' (400 with
    'Parse error:' body), 'preview_only' (preview rendered but Save button
    missing), or 'http:<status>' for other failures.
    """
    captured: dict[str, int | str] = {}

    def _on_response(resp):
        if resp.url == post_url and resp.request.method == "POST":
            captured["status"] = resp.status

    page.on("response", _on_response)
    try:
        await page.click("form[action*='/upload'] button.btn-primary[type='submit']")
        # Wait either for the preview URL (Phase 2 happy path), the list URL
        # (Phase 1 legacy or post-confirm landing), or an error page render.
        try:
            if preview_pattern:
                await page.wait_for_url(
                    lambda url: preview_pattern in url or url == list_url,
                    timeout=30000,
                )
            else:
                await page.wait_for_url(list_url, timeout=30000)
        except Exception:
            await page.wait_for_load_state("networkidle", timeout=5000)
    finally:
        page.remove_listener("response", _on_response)

    status = captured.get("status")
    if status == 400:
        await shot(page, f"{slug}_error")
        return "parse_error"

    if preview_pattern and preview_pattern in page.url:
        # Preview shown — capture, then auto-confirm via the Save button.
        await shot(page, f"{slug}_preview")
        save_btn = await page.query_selector(
            # BQD/BOM/Catalog use multi-button forms with formaction;
            # BCCT uses single-button form with action on <form>. Match both.
            "form[action*='/confirm'] button.btn-primary[type='submit'], "
            "form button.btn-primary[formaction*='/preview/'][formaction$='/confirm']"
        )
        if save_btn is None:
            return "preview_only"
        await save_btn.click()
        try:
            await page.wait_for_url(
                lambda url: list_url in url, timeout=30000,
            )
        except Exception:
            await page.wait_for_load_state("networkidle", timeout=5000)

    if list_url in page.url:
        await shot(page, f"{slug}_after")
        return "ok"
    await shot(page, f"{slug}_unexpected")
    return f"http:{status}"


async def upload_bqd(page, *, client_id: str, file_path: Path, slug: str) -> str:
    upload_url = f"{BASE}/clients/{client_id}/bqd/upload"
    list_url = f"{BASE}/clients/{client_id}/bqd"
    await page.goto(upload_url)
    await shot(page, f"{slug}_form")
    await page.set_input_files('input[type="file"]', str(file_path))
    return await _submit_and_classify(
        page, post_url=upload_url, list_url=list_url, slug=slug,
        preview_pattern="/bqd/preview/",
    )


async def upload_bom(page, *, client_id: str, profile: str, file_path: Path, slug: str) -> str:
    upload_url = f"{BASE}/clients/{client_id}/bom/upload"
    list_url = f"{BASE}/clients/{client_id}/bom"
    await page.goto(upload_url)
    await shot(page, f"{slug}_form")
    await page.select_option('select[name="profile"]', profile)
    await page.set_input_files('input[type="file"]', str(file_path))
    return await _submit_and_classify(
        page, post_url=upload_url, list_url=list_url, slug=slug,
        preview_pattern="/bom/preview/",
    )


async def upload_catalog(page, *, client_id: str, file_path: Path, slug: str) -> str:
    upload_url = f"{BASE}/clients/{client_id}/catalog/upload"
    list_url = f"{BASE}/clients/{client_id}/catalog"
    await page.goto(upload_url)
    await shot(page, f"{slug}_form")
    await page.set_input_files('input[type="file"]', str(file_path))
    return await _submit_and_classify(
        page, post_url=upload_url, list_url=list_url, slug=slug,
        preview_pattern="/catalog/preview/",
    )


async def upload_bcct(page, *, client_id: str, file_path: Path, slug: str) -> str:
    upload_url = f"{BASE}/clients/{client_id}/bcct/upload"
    list_url = f"{BASE}/clients/{client_id}/bcct"
    await page.goto(upload_url)
    await shot(page, f"{slug}_form")
    await page.set_input_files('input[type="file"]', str(file_path))
    return await _submit_and_classify(
        page, post_url=upload_url, list_url=list_url, slug=slug,
        preview_pattern="/bcct/upload/preview/",
    )


async def main() -> int:
    if not REAL_DIR.exists():
        print(f"missing real-data dir: {REAL_DIR}", file=sys.stderr)
        return 2
    print(f"== real_uploads smoke ==  base={BASE}  data={REAL_DIR}")
    rows: list[tuple] = []
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        ctx = await browser.new_context(viewport={"width": 1440, "height": 900})
        await ctx.add_cookies([{"name": "data_hub_lang", "value": "vi", "url": BASE}])
        page = await ctx.new_page()
        await login(page)
        print("  logged in.")
        for company, entity, profile, rel, expected in JOBS:
            client_id = CLIENT_IDS[company]
            file_path = REAL_DIR / rel
            slug = f"{company}_{entity}_{Path(rel).stem}"
            if expected == "skip_unsafe":
                # Just screenshot the form; do NOT actually post.
                await page.goto(f"{BASE}/clients/{client_id}/{entity}/upload")
                await shot(page, f"{slug}_form_skipped")
                rows.append((company, entity, rel, expected, "skipped (would corrupt)"))
                continue
            if not file_path.exists():
                rows.append((company, entity, rel, expected, "missing fixture"))
                continue
            try:
                if entity == "bqd":
                    outcome = await upload_bqd(page, client_id=client_id, file_path=file_path, slug=slug)
                elif entity == "bom":
                    outcome = await upload_bom(page, client_id=client_id, profile=profile, file_path=file_path, slug=slug)
                elif entity == "catalog":
                    outcome = await upload_catalog(page, client_id=client_id, file_path=file_path, slug=slug)
                elif entity == "bcct":
                    outcome = await upload_bcct(page, client_id=client_id, file_path=file_path, slug=slug)
                else:
                    outcome = "skip_unknown_entity"
            except Exception as e:
                outcome = f"exception:{type(e).__name__}:{e}"
            verdict = (
                "✓ as expected" if outcome == expected
                else "△ unexpected"
            )
            rows.append((company, entity, rel, expected, f"{outcome} {verdict}"))
            print(f"  {company:8} {entity:4} {rel:40}  expected={expected:12} got={outcome}")
        await ctx.close()
        await browser.close()
    print()
    print("Summary:")
    for r in rows:
        print(f"  {r[0]:8} {r[1]:4} {r[2]:40}  {r[4]}")
    n_ok = sum(1 for r in rows if r[3] in ("ok", "parse_error") and r[3] in r[4])
    print(f"\n{n_ok}/{len(rows)} jobs matched expectation.")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
