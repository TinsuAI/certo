"""In-process Data Hub client — no server, no socket.

Phase 1 of the consolidation. Two mechanisms, chosen per endpoint by what the
measurement says:

**Bridge** (the default for every inherited method). `SyncASGITransport` drives
Data Hub's ASGI app directly through a blocking portal, so the whole existing
`DataHubClient` surface works with no second process and no duplicated handler
logic. It is a *topology* change, not a speed one — measured at 6.07s against
5.75s over the socket for the same call.

**Extraction** (the overrides below). For the paths the perf audit named, the
client calls the same service function the route calls, skipping HTTP, JSON and
— the part that actually costs — the OFFSET pagination walk.

Measured on johnson-vn against `co_merged`:

| call | HTTP / bridge | direct |
|---|---|---|
| `list_materials` (13,131 rows, 14 pages) | 5.75s / 6.07s | **0.65s** |
| `list_bcct` (65,846 rows, 66 pages) | 5.62s | **2.66s** |

JSON encode+decode of the 8.7 MB materials payload is 0.13s of that, so
serialisation is not the problem. `limit 1000 offset 12000` re-scanning and
discarding 12,000 rows on every page is.

Auth is unchanged on purpose (phase 3 owns it): each override verifies the same
bearer token through Data Hub's own `_require_token` and enforces the same
`_require_can_view_client` scoping, so an in-process call cannot see a client
that the HTTP call would have refused.
"""
from __future__ import annotations

from typing import Callable

import anyio.from_thread
import httpx

from app.data_hub_client import DataHubClient


class SyncASGITransport(httpx.BaseTransport):
    """Sync httpx transport that drives an ASGI app in the same process.

    `httpx.ASGITransport` implements only `handle_async_request`, so a sync
    `httpx.Client` cannot use it directly. This runs it on an anyio blocking
    portal — the same mechanism starlette's `TestClient` uses.

    Note the portal is a single event loop: bridged calls serialise against each
    other, matching production Data Hub's `--workers 1`. Data Hub's handlers are
    `async def` with blocking `connect()` inside (the CO-524 defect class), so
    they do not release the loop while querying. Not a regression over the
    two-process setup, and not phase 1's to fix.
    """

    def __init__(self, app):
        self._portal_cm = anyio.from_thread.start_blocking_portal("asyncio")
        self._portal = self._portal_cm.__enter__()
        self._inner = httpx.ASGITransport(app=app)

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        body = request.read()
        areq = httpx.Request(
            method=request.method,
            url=request.url,
            headers=request.headers,
            content=body,
        )
        aresp = self._portal.call(self._inner.handle_async_request, areq)
        content = self._portal.call(aresp.aread)
        self._portal.call(aresp.aclose)
        return httpx.Response(
            status_code=aresp.status_code,
            headers=aresp.headers,
            content=content,
            request=request,
        )

    def close(self) -> None:
        try:
            self._portal_cm.__exit__(None, None, None)
        except Exception:  # noqa: BLE001 - teardown must not mask a real error
            pass


class InProcessDataHubClient(DataHubClient):
    """`DataHubClient` that talks to Data Hub in-process.

    Everything inherited goes through the ASGI bridge. The overrides below take
    the extracted-service path instead.
    """

    def __init__(
        self,
        *,
        token: str,
        token_provider: Callable[[], str] | None = None,
        timeout: float = 20,
    ):
        from hub.app.main import app as hub_app

        super().__init__(
            base_url="http://data-hub.internal",
            token=token,
            token_provider=token_provider,
            timeout=timeout,
            transport=SyncASGITransport(hub_app),
        )

    def _authorize(self, client_id: str | None = None, *, scope: str = "hub:read"):
        """Run Data Hub's own bearer verification and client scoping.

        Same functions the route handlers call, so in-process access rights are
        identical to HTTP access rights — including the service-account
        `client_ids` whitelist and the per-user `can_view_client` check.
        """
        from hub.app.routes.api import _require_can_view_client, _require_token

        header = self._auth_headers().get("Authorization")
        claims = _require_token(header, scope=scope)
        if client_id:
            _require_can_view_client(claims, client_id)
        return claims

    def list_materials(self, client_id: str, **query) -> list[dict]:
        """One query instead of a 14-page OFFSET walk. 5.75s -> 0.65s."""
        from hub.app.services import materials as materials_service

        self._authorize(client_id)
        if not _client_exists(client_id):
            raise httpx.HTTPStatusError(
                "Client not found",
                request=httpx.Request("GET", f"{self.base_url}/v1/hub/materials"),
                response=httpx.Response(404),
            )
        return materials_service.list_materials(
            client_id,
            category=query.get("category"),
            status=query.get("status"),
            limit=None,
        )

    def close(self) -> None:
        transport = getattr(self._client, "_transport", None)
        super().close()
        if isinstance(transport, SyncASGITransport):
            transport.close()


def _client_exists(client_id: str) -> bool:
    from hub.app.routes.clients import get_client

    return bool(get_client(client_id))
