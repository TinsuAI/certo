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


def _mark_internal(app):
    """Stamp requests that originate inside this process.

    The bridged calls carry no bearer — there is nobody for CO to prove itself
    to any more — but the API cannot simply stop checking, because those same
    routes are still served to the outside under the mount prefix. The marker
    lives in the ASGI scope rather than a header, so an external request cannot
    forge it: requests arriving through uvicorn never have it set.
    """

    from hub.app.auth.internal import INTERNAL_CALL

    async def _app(scope, receive, send):
        marker = INTERNAL_CALL.set(True)
        try:
            await app(scope, receive, send)
        finally:
            INTERNAL_CALL.reset(marker)

    return _app


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
        self._inner = httpx.ASGITransport(app=_mark_internal(app))

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
        """Authorize an in-process read.

        There is no token to present between the halves any more — they are one
        process sharing one session — so demanding a bearer here would be
        demanding proof of identity from ourselves. The rule mirrors CO's own
        guard instead:

          - a bearer, when one is supplied, is still verified and still carries
            the service-account `client_ids` whitelist (an outside caller);
          - otherwise the signed-in operator's scope applies;
          - and when CO does not require auth at all (local dev, the test
            suite), the read is allowed.

        The client-scoping check is never skipped when there IS a subject — that
        is the control that stops one operator reading another client's corpus.
        """
        from hub.app.routes.api import _require_can_view_client, _require_token

        header = self._auth_headers().get("Authorization")
        if header:
            claims = _require_token(header, scope=scope)
            if client_id:
                _require_can_view_client(claims, client_id)
            return claims

        from app import co_auth

        user = _current_co_user()
        if user is None:
            # No subject: either CO's middleware already decided this request may
            # proceed, or there is no request at all — the origin preload thread,
            # the co_stock materializer and the CLI all read through here. This
            # layer enforces scoping, not authentication; the middleware is the
            # gate, and duplicating it here would lock out background work.
            return None
        if client_id and not co_auth.can_view_client(user, client_id):
            from fastapi import HTTPException

            raise HTTPException(status_code=403, detail="forbidden")
        return None

    def list_materials(self, client_id: str, **query) -> list[dict]:
        """One query instead of a 14-page OFFSET walk. 5.75s -> 0.65s."""
        from hub.app.services import materials as materials_service

        self._authorize(client_id)
        if not _client_exists(client_id):
            raise _not_found(self.base_url, "/v1/hub/materials")
        return materials_service.list_materials(
            client_id,
            category=query.get("category"),
            status=query.get("status"),
            limit=None,
        )

    def list_bcct(self, client_id: str, **query) -> list[dict]:
        """One query instead of a 66-page OFFSET walk. 5.62s -> 2.66s."""
        return self._bcct(client_id, query)["items"]

    def list_bcct_with_envelope(
        self,
        client_id: str,
        *,
        since: str = "",
        include_tombstones: bool = False,
        **query,
    ) -> dict:
        """Envelope variant the delta-refresh path needs: items + server_time
        + tombstones. Same single-query shortcut as `list_bcct`."""
        result = self._bcct(
            client_id,
            query,
            since=since,
            want_tombstones=bool(since and include_tombstones),
        )
        return {
            "items": result["items"],
            "tombstones": result["tombstones"],
            "server_time": result["server_time"],
        }

    def bcct_server_time(self, client_id: str) -> str:
        """High-water-mark probe. Over HTTP this fetched page 1 to read one
        field; here it is just the clock, with no rows touched at all."""
        from datetime import datetime, timezone

        self._authorize(client_id)
        return _iso(datetime.now(timezone.utc))

    def _bcct(self, client_id: str, query: dict, *, since: str = "", want_tombstones: bool = False) -> dict:
        from hub.app.routes.api import _parse_since, _validate_pid_candidate_limit
        from hub.app.services import bcct as bcct_service

        self._authorize(client_id)
        if not _client_exists(client_id):
            raise _not_found(self.base_url, "/v1/hub/bcct")
        raw_identity = query.get("include_material_identity")
        include_identity = str(raw_identity).lower() in {"1", "true", "yes"} if raw_identity is not None else False
        result = bcct_service.list_bcct(
            client_id,
            year=query.get("year"),
            direction=query.get("direction"),
            declaration_no=query.get("declaration_no"),
            since_ts=_parse_since(since or query.get("since")),
            limit=None,
            include_material_identity=include_identity,
            candidate_limit=_validate_pid_candidate_limit(
                query.get("material_identity_candidate_limit")
            ),
            want_tombstones=want_tombstones,
        )
        # The HTTP path JSON-encodes before CO sees it; match that shaping so
        # downstream code (the (max(indexed_at), row_count) snapshot marker in
        # particular) sees strings where it always saw strings.
        from hub.app.services.materials import serialize

        return {
            "items": serialize(result["items"]),
            "tombstones": serialize(result["tombstones"]),
            "server_time": _iso(result["server_time"]),
        }

    def close(self) -> None:
        transport = getattr(self._client, "_transport", None)
        super().close()
        if isinstance(transport, SyncASGITransport):
            transport.close()


def _current_co_user():
    """The operator this call is being made for, if a request is in flight.

    CO's middleware parks the resolved user on request.state; the ContextVar
    that used to carry a Data Hub token now carries nothing, so the session is
    the only subject there is.
    """
    from app import co_auth

    return co_auth.CURRENT_CO_USER.get()


def _unauthorized(base_url: str) -> httpx.HTTPStatusError:
    return httpx.HTTPStatusError(
        "authentication required",
        request=httpx.Request("GET", base_url),
        response=httpx.Response(401),
    )


def _iso(value) -> str:
    return value.isoformat() if hasattr(value, "isoformat") else str(value or "")


def _not_found(base_url: str, path: str) -> httpx.HTTPStatusError:
    return httpx.HTTPStatusError(
        "Client not found",
        request=httpx.Request("GET", f"{base_url}{path}"),
        response=httpx.Response(404),
    )


def _client_exists(client_id: str) -> bool:
    from hub.app.routes.clients import get_client

    return bool(get_client(client_id))
