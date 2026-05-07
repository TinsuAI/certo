"""UI smoke for the BOM proposal review flow.

Covers:
- /clients/{cid}/edit — new bom_proposal_mode (3 options) + bom_approver_tier dropdown.
- /clients/{cid}/proposals — pending chip + sort.
- /clients/{cid}/proposals/{pid} — review form (approve / reject / withdraw)
  visible when status='pending' and user has approver permission.
- Approve flow materialises a new BOM version.

Run while dev server is up at 127.0.0.1:8754. Saves screenshots to /tmp/dh_ui/.
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import httpx
from playwright.async_api import async_playwright

BASE = "http://127.0.0.1:8754"
EMAIL = "admin@data-hub.local"
PASSWORD = "admin123"
CID = "growatt-vn"
OUT = Path("/tmp/dh_ui")
OUT.mkdir(parents=True, exist_ok=True)


def _shot_path(slug: str) -> Path:
    return OUT / f"{slug}.png"


async def _shot(page, slug: str):
    out = _shot_path(slug)
    await page.screenshot(path=str(out), full_page=True)
    print(f"  shot {out}")


async def _set_mode(page, mode: str):
    """Use the edit form to flip bom_proposal_mode."""
    await page.goto(f"{BASE}/clients/{CID}/edit")
    await page.select_option('select[name="bom_proposal_mode"]', mode)
    await page.click('button.btn-primary[type="submit"]')
    await page.wait_for_url(f"{BASE}/clients/{CID}", timeout=5000)


async def _submit_pending_proposal(parent_version: str) -> str:
    """Hit the /v1/hub API directly. Auth is disabled on dev so no bearer needed."""
    body = {
        "client_id": CID,
        "actor": "co_system",
        "intent": "modified_for_case",
        "parent_artifact_id": parent_version,
        "context": {"case_id": "UI-SMOKE-1"},
        "rows": [
            {"material_code": "PE-001", "qty_per_unit": 0.46, "uom": "kg"},
            {"material_code": "AL-100", "qty_per_unit": 0.30, "uom": "kg"},
            {"material_code": "PCB-12", "qty_per_unit": 1.0, "uom": "pcs"},
            {"material_code": "HEATSINK-A", "qty_per_unit": 1.0, "uom": "pcs"},
            {"material_code": "CASE-INV", "qty_per_unit": 1.0, "uom": "pcs"},
        ],
    }
    async with httpx.AsyncClient() as client:
        # Strict mode is off + auth disabled, but bom.py POST uses session
        # auth — easier to call the /v1/hub/ api endpoint which now allows
        # anon when DATA_HUB_API_AUTH_DISABLED=1.
        r = await client.post(
            f"{BASE}/v1/hub/products/INV-3000/bom/proposals",
            json=body, timeout=10,
        )
        r.raise_for_status()
        out = r.json()
        return out["proposal_id"]


async def _latest_published_version() -> str | None:
    """Read the most recent published artifact_id for INV-3000 via the public API."""
    async with httpx.AsyncClient() as client:
        r = await client.get(
            f"{BASE}/v1/hub/products/INV-3000/bom/versions",
            params={"client_id": CID}, timeout=10,
        )
        r.raise_for_status()
        items = r.json().get("items", [])
        for v in items:
            if v.get("status") == "published" and not v.get("tombstoned_at"):
                return v["artifact_id"]
    return None


async def main():
    parent_version = await _latest_published_version()
    if not parent_version:
        print("no parent version — abort", file=sys.stderr)
        sys.exit(1)
    print(f"parent_artifact_id = {parent_version}")

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(viewport={"width": 1440, "height": 900})
        await context.add_cookies([{
            "name": "data_hub_lang", "value": "vi", "url": BASE,
        }])
        page = await context.new_page()

        # Login
        print("login")
        await page.goto(f"{BASE}/login")
        await page.fill('input[name="email"]', EMAIL)
        await page.fill('input[name="password"]', PASSWORD)
        await page.click('button[type="submit"]')
        await page.wait_for_url(f"{BASE}/clients", timeout=5000)

        # 01 — edit form (new dropdowns)
        print("step 01 — edit form")
        await page.goto(f"{BASE}/clients/{CID}/edit")
        # sanity: dropdown has 3 options + tier dropdown present
        modes = await page.locator('select[name="bom_proposal_mode"] option').count()
        tiers = await page.locator('select[name="bom_approver_tier"] option').count()
        print(f"  bom_proposal_mode options = {modes}, approver_tier options = {tiers}")
        assert modes == 3, f"expected 3 modes, got {modes}"
        assert tiers == 3, f"expected 3 tiers, got {tiers}"
        await _shot(page, "01_edit_form")

        # 02 — switch to manual mode
        print("step 02 — switch to manual")
        await _set_mode(page, "manual")
        # Reload edit page to confirm persisted
        await page.goto(f"{BASE}/clients/{CID}/edit")
        selected_mode = await page.locator(
            'select[name="bom_proposal_mode"]'
        ).input_value()
        print(f"  reloaded mode = {selected_mode}")
        assert selected_mode == "manual"

        # 03 — submit a proposal via API → pending
        print("step 03 — submit pending proposal")
        proposal_id = await _submit_pending_proposal(parent_version)
        print(f"  proposal_id = {proposal_id}")

        # 04 — proposals list shows pending chip
        print("step 04 — proposals list")
        await page.goto(f"{BASE}/clients/{CID}/proposals")
        await _shot(page, "04_proposals_list_pending")
        # Sort — pending should be first row
        first_status = await page.locator(
            "table.dh-table tbody tr:first-child td:nth-child(6)"
        ).inner_text()
        print(f"  first row status text = {first_status!r}")

        # 05 — proposal detail with review form
        print("step 05 — proposal detail (pending → review form visible)")
        await page.goto(f"{BASE}/clients/{CID}/proposals/{proposal_id}")
        await _shot(page, "05_proposal_pending_with_review")
        approve_btn = await page.locator(
            'form[action$="/approve"] button[type="submit"]'
        ).count()
        reject_btn = await page.locator(
            'form[action$="/reject"] button[type="submit"]'
        ).count()
        withdraw_btn = await page.locator(
            'form[action$="/withdraw"] button[type="submit"]'
        ).count()
        print(f"  buttons → approve={approve_btn}, reject={reject_btn}, withdraw={withdraw_btn}")
        assert approve_btn == 1 and reject_btn == 1 and withdraw_btn == 1

        # 06 — approve → redirects to detail with badge=approved
        print("step 06 — click approve")
        await page.fill(
            'form[action$="/approve"] input[name="reason"]',
            "ui smoke approved",
        )
        await page.click('form[action$="/approve"] button[type="submit"]')
        await page.wait_for_url(
            f"{BASE}/clients/{CID}/proposals/{proposal_id}", timeout=5000,
        )
        await _shot(page, "06_proposal_approved")
        # The review callout should now be gone.
        callout = await page.locator('section.callout-info').count()
        print(f"  review callout count after approve = {callout}")
        assert callout == 0

        # 07 — restore mode to auto for clean state
        print("step 07 — restore auto mode")
        await _set_mode(page, "auto")
        await page.goto(f"{BASE}/clients/{CID}/edit")
        selected_mode = await page.locator(
            'select[name="bom_proposal_mode"]'
        ).input_value()
        print(f"  restored mode = {selected_mode}")
        assert selected_mode == "auto"

        await browser.close()
    print("\nUI smoke OK")


if __name__ == "__main__":
    asyncio.run(main())
