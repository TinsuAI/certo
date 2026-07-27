"""UI smoke + committed proof for the BCCT Apply-gate hint (issue #56).

Drives the real preview page on :8754 through Playwright:
  1. load with a blocking cross-family UoM drift -> Apply button disabled,
     locked-state hint visible.
  2. tick the drift ack checkbox -> button enabled, hint hidden.

Writes screenshots next to this file. Seeds + cleans up its own throwaway
client, so it does not depend on existing data.

Run with the dev server up on :8754:
    uv run python .ai/features/2026-07-27-bcct-apply-gate-hint/ui_smoke.py
"""
from __future__ import annotations

import json
import secrets
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from app.auth.session import SESSION_COOKIE, create_session, hash_password
from app.database import connect

OUT = Path(__file__).resolve().parent / "screenshots"
BASE = "http://127.0.0.1:8754"
CLIENT = "smoke_gate"
ADMIN = "u_smoke_gate_admin"


def seed() -> str:
    pending_id = secrets.token_urlsafe(16)
    parsed = [
        {"customs_code": "COUNT_PCS", "unit": "kg",
         "declaration_no": "SMOKE_DRIFT", "line_no": 1,
         "transaction_key": "SMOKE_DRIFT-1", "direction": "import",
         "invoice_date": "2026-05-19"},
    ]
    diff = {
        "new": 14164, "noop": 31171, "total": 14164, "orphan": [],
        "diff": [{
            "key": ["SMOKE_DRIFT-1", 1], "decl_no": "SMOKE_DRIFT", "line_no": 1,
            "changed_fields": ["invoice_date"],
            "old": {"invoice_date": "2026-04-19"},
            "new": {"invoice_date": "2026-05-19"},
        }],
    }
    with connect() as conn, conn.cursor() as cur:
        cur.execute("insert into hub.clients (client_id, name) values (%s, %s) "
                    "on conflict (client_id) do nothing", (CLIENT, "smoke gate"))
        cur.execute(
            "insert into hub.materials (client_id, material_code, name, "
            "category, uom) values (%s, 'COUNT_PCS', 'count material', 'nvl', "
            "'pcs') on conflict (client_id, material_code) do update set "
            "uom = excluded.uom", (CLIENT,))
        cur.execute(
            "insert into hub.users (user_id, email, display_name, "
            "password_hash, role, status) values (%s, %s, 'Smoke Gate', %s, "
            "'admin', 'active') on conflict (user_id) do update set "
            "role='admin', status='active'",
            (ADMIN, "smoke-gate@test.local", hash_password("smoke-pw")))
        cur.execute(
            "insert into hub.upload_pending (pending_id, client_id, module, "
            "parsed_rows, diff_summary, expires_at) values (%s, %s, 'bcct', "
            "%s::jsonb, %s::jsonb, %s)",
            (pending_id, CLIENT, json.dumps(parsed), json.dumps(diff),
             datetime.now(timezone.utc) + timedelta(hours=1)))
        conn.commit()
    return pending_id


def cleanup():
    with connect() as conn, conn.cursor() as cur:
        cur.execute("delete from hub.upload_pending where client_id=%s", (CLIENT,))
        cur.execute("delete from hub.sessions where user_id=%s", (ADMIN,))
        cur.execute("delete from hub.materials where client_id=%s", (CLIENT,))
        cur.execute("delete from hub.users where user_id=%s", (ADMIN,))
        cur.execute("delete from hub.clients where client_id=%s", (CLIENT,))
        conn.commit()


def main() -> int:
    from playwright.sync_api import sync_playwright

    OUT.mkdir(exist_ok=True)
    pending = seed()
    sess = create_session(ADMIN)
    errors = []
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch()
            ctx = browser.new_context(viewport={"width": 1280, "height": 900})
            ctx.add_cookies([{"name": SESSION_COOKIE, "value": sess,
                              "domain": "127.0.0.1", "path": "/"}])
            url = f"{BASE}/clients/{CLIENT}/bcct/upload/preview/{pending}"
            page = ctx.new_page()
            page.goto(url, wait_until="load")

            btn = page.locator("#confirm-form button.btn-primary")
            hint = page.locator("#uom-gate-hint")

            locked = btn.is_disabled()
            hint_shown = hint.is_visible()
            print(f"[load]      button disabled={locked}  hint visible={hint_shown}")
            if not locked:
                errors.append("button not disabled on load")
            if not hint_shown:
                errors.append("hint not visible on load")
            page.screenshot(path=str(OUT / "01-locked.png"), full_page=True)

            # The operator's exact misconception: ticking confirm_diffs must
            # NOT unlock the button (only ack_uom_drift does), and the hint
            # must stay until then.
            page.check("input[name=confirm_diffs]")
            still_locked = btn.is_disabled()
            hint_still = hint.is_visible()
            print(f"[+diffs]    button disabled={still_locked}  hint visible={hint_still}")
            if not still_locked:
                errors.append("confirm_diffs enabled the button (it should not)")
            if not hint_still:
                errors.append("hint hidden by confirm_diffs (should stay until ack)")

            page.check("input[name=ack_uom_drift]")
            unlocked = not btn.is_disabled()
            hint_hidden = not hint.is_visible()
            print(f"[after ack] button enabled={unlocked}  hint hidden={hint_hidden}")
            if not unlocked:
                errors.append("button not enabled after ack")
            if not hint_hidden:
                errors.append("hint not hidden after ack")
            page.screenshot(path=str(OUT / "02-unlocked.png"), full_page=True)

            # F2 / #58: browser form-restore re-checks the ack on reload
            # WITHOUT firing 'change'. Simulate by pre-checking the ack in the
            # served HTML; the button must be ENABLED on load, not stuck
            # disabled by the banner's DOMContentLoaded handler.
            def _precheck(route):
                resp = route.fetch()
                html = resp.text().replace(
                    'name="ack_uom_drift" value="1"',
                    'name="ack_uom_drift" value="1" checked')
                route.fulfill(response=resp, body=html)
            page2 = ctx.new_page()
            page2.route("**/bcct/upload/preview/**", _precheck)
            page2.goto(url, wait_until="load")
            btn2 = page2.locator("#confirm-form button.btn-primary")
            restore_ok = not btn2.is_disabled()
            print(f"[restore]   ack pre-checked on load -> enabled={restore_ok}")
            if not restore_ok:
                errors.append("F2: button stuck disabled when ack is "
                              "restored-checked on load (banner ignores it)")

            browser.close()
    finally:
        cleanup()

    print("-" * 60)
    if errors:
        for e in errors:
            print(f"FAIL: {e}")
        return 1
    print("PASS: locked+hint -> tick ack -> enabled+hint gone. Screenshots in "
          f"{OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
