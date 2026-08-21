"""Deploy smoke: assert the sister-app API enforces auth on the PUBLIC
surface (https://ttdatahub.tinsu.ai), not just in unit tests.

Regression guard for the 2026-06-06 leak where anonymous callers got
200 + real customs documents from the declaration download endpoints
(app permissive-mode kill-switch + Cloudflare caching `.pdf`/`.zip`).

Checks, anonymously, that download.pdf / download.zip / metadata all
return 401 — an anonymous 200 is a HARD FAIL (the leak). A cached 200
served by Cloudflare also fails here, so this doubles as a cache-purge
verifier. Optionally, with DATA_HUB_SMOKE_TOKEN set, asserts an
authorized hub:read bearer still gets 200 (happy path intact).

Usage:
  uv run python scripts/smoke_public_auth.py
  DATA_HUB_SMOKE_BASE=https://ttdatahub.tinsu.ai \
  DATA_HUB_SMOKE_CLIENT=johnson-vn \
  DATA_HUB_SMOKE_DECL=107271918940 \
  DATA_HUB_SMOKE_TOKEN=<hub:read bearer> \
      uv run python scripts/smoke_public_auth.py
"""
from __future__ import annotations

import os
import sys

import httpx

BASE = os.environ.get("DATA_HUB_SMOKE_BASE", "https://ttdatahub.tinsu.ai").rstrip("/")
CLIENT = os.environ.get("DATA_HUB_SMOKE_CLIENT", "johnson-vn")
DECL = os.environ.get("DATA_HUB_SMOKE_DECL", "107271918940")
TOKEN = os.environ.get("DATA_HUB_SMOKE_TOKEN")

_PARAMS = {"direction": "import", "declaration_nos": DECL}
_ENDPOINTS = {
    "download.pdf": f"/v1/hub/clients/{CLIENT}/declarations/download.pdf",
    "download.zip": f"/v1/hub/clients/{CLIENT}/declarations/download.zip",
    "metadata": f"/v1/hub/clients/{CLIENT}/declarations",
}


def main() -> int:
    failures: list[str] = []
    # Cache-bust so a stale Cloudflare entry can't mask a still-open hole;
    # a separate un-busted probe detects a cached-200 leak directly.
    with httpx.Client(timeout=30, follow_redirects=False) as c:
        for name, path in _ENDPOINTS.items():
            for label, extra in (("anon", {}), ("anon+cachebust", {"cb": "smoke"})):
                params = {**_PARAMS, **extra} if name != "metadata" else extra
                r = c.get(f"{BASE}{path}", params=params)
                cc = r.headers.get("cache-control", "")
                cf = r.headers.get("cf-cache-status", "-")
                ok = r.status_code == 401
                flag = "OK " if ok else "LEAK"
                print(f"[{flag}] {name:13} {label:15} -> {r.status_code} "
                      f"(cf-cache={cf}, cache-control={cc!r})")
                if not ok:
                    failures.append(
                        f"{name} {label}: expected 401, got {r.status_code}"
                    )

        if TOKEN:
            print("--- authorized happy path ---")
            for name, path in _ENDPOINTS.items():
                params = _PARAMS if name != "metadata" else {}
                r = c.get(f"{BASE}{path}", params=params,
                          headers={"authorization": f"Bearer {TOKEN}"})
                ok = r.status_code == 200
                print(f"[{'OK ' if ok else 'FAIL'}] {name:13} authorized -> "
                      f"{r.status_code}")
                if not ok:
                    failures.append(
                        f"{name} authorized: expected 200, got {r.status_code}"
                    )
        else:
            print("(set DATA_HUB_SMOKE_TOKEN to also check the 200 happy path)")

    if failures:
        print(f"\nSMOKE FAILED ({len(failures)}):")
        for f in failures:
            print(f"  - {f}")
        return 1
    print("\nSMOKE PASSED: public surface enforces auth (anonymous -> 401).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
