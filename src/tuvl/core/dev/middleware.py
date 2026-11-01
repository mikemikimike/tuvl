import hmac
import json
from collections.abc import Awaitable

from starlette.types import ASGIApp, Receive, Scope, Send

from tuvl.core.access_control import host_is_permitted
from tuvl.core.config import settings

_JSON = b"application/json"


def _json_response(send: Send, status: int, body: dict) -> Awaitable[None]:

    async def _send() -> None:
        data = json.dumps(body).encode()
        await send(
            {
                "type": "http.response.start",
                "status": status,
                "headers": [(b"content-type", _JSON), (b"content-length", str(len(data)).encode())],
            }
        )
        await send({"type": "http.response.body", "body": data, "more_body": False})

    return _send()


class DevMiddleware:
    """Pure-ASGI middleware for /dev route authentication.

    Uses raw ASGI instead of BaseHTTPMiddleware so that the scope dict
    is never mutated — BaseHTTPMiddleware strips `headers` from scope
    when calling call_next, which breaks mounted sub-applications.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        path = scope.get("path", "")
        if not path.startswith("/dev"):
            await self.app(scope, receive, send)
            return

        # ── /dev/* — enforce Bearer token + IP allowlist ──────────────────
        client = scope.get("client")
        client_host = client[0] if client else ""
        if not host_is_permitted(client_host):
            await _json_response(send, 403, {"detail": "forbidden"})
            return

        headers = {k.lower(): v for k, v in scope.get("headers", [])}
        auth = headers.get(b"authorization", b"").decode("ascii", errors="ignore")
        if not auth.lower().startswith("bearer "):
            await _json_response(send, 401, {"detail": "unauthorized"})
            return
        incoming = auth[len("Bearer ") :]
        # Fail closed when no dev key is configured: an empty key must never
        # authenticate (hmac.compare_digest("", "") is True).
        if not (
            settings.tuvl_dev_api_key and hmac.compare_digest(incoming, settings.tuvl_dev_api_key)
        ):
            await _json_response(send, 401, {"detail": "unauthorized"})
            return

        await self.app(scope, receive, send)
