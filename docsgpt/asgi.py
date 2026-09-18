"""ASGI entrypoint: Flask (WSGI) + FastMCP on the same process."""

from __future__ import annotations

from a2wsgi import WSGIMiddleware
from starlette.applications import Starlette
from starlette.datastructures import MutableHeaders
from starlette.middleware import Middleware
from starlette.middleware.cors import CORSMiddleware
from starlette.responses import JSONResponse
from starlette.routing import Mount
from starlette.types import ASGIApp, Receive, Scope, Send

from docsgpt.api.async_sse import async_sse_routes
from docsgpt.app import app as flask_app
from docsgpt.core.cors import cors_allowed_origins
from docsgpt.core.settings import settings
from docsgpt.mcp_server import mcp
from docsgpt.security.headers import apply_security_headers
from docsgpt.ui import StaticUI

_WSGI_THREADPOOL = int(settings.WSGI_THREADPOOL_WORKERS)


class CorsOriginRestrictionMiddleware:
    """Reject unknown browser origins before mounted ASGI apps handle them."""

    def __init__(self, app: ASGIApp, allowed_origins: tuple[str, ...]):
        self.app = app
        self.allowed_origins = frozenset(allowed_origins)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        origin = next(
            (
                value.decode("latin-1")
                for name, value in scope.get("headers", [])
                if name.lower() == b"origin"
            ),
            None,
        )
        if origin and origin not in self.allowed_origins:
            response = JSONResponse(
                {
                    "success": False,
                    "error": "cors_origin_not_allowed",
                    "message": "The request Origin is not allowed",
                },
                status_code=403,
            )
            await response(scope, receive, send)
            return

        await self.app(scope, receive, send)


class SecurityHeadersMiddleware:
    """Apply security headers to every HTTP response in the ASGI shell."""

    def __init__(self, app: ASGIApp):
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        async def send_with_security_headers(message):
            if message["type"] == "http.response.start":
                headers = MutableHeaders(scope=message)
                apply_security_headers(headers, is_https=scope.get("scheme") == "https")
            await send(message)

        await self.app(scope, receive, send_with_security_headers)


_CORS_ALLOWED_ORIGINS = cors_allowed_origins(
    settings.CORS_ALLOWED_ORIGINS,
    settings.AUTH_TYPE,
)

mcp_app = mcp.http_app(path="/")

# The web UI, when the package ships one (docsgpt/static) and SERVE_UI is on:
# files are served directly, Flask's own path prefixes pass through, and any
# other GET renders index.html for the client-side router.
_backend = StaticUI.wrap(
    WSGIMiddleware(flask_app, workers=_WSGI_THREADPOOL), flask_app.url_map, enabled=settings.SERVE_UI
)

asgi_app = Starlette(
    routes=[
        Mount("/mcp", app=mcp_app),
        # Native-async SSE readers intercept their exact paths before the
        # Flask catch-all, so a mostly-idle reconnect tail rides the event
        # loop instead of pinning a WSGI threadpool slot. Order matters:
        # Starlette matches routes top-to-bottom, so these must precede the
        # Mount("/") that hands everything else to Flask.
        *async_sse_routes,
        Mount("/", app=_backend),
    ],
    middleware=[
        Middleware(SecurityHeadersMiddleware),
        Middleware(
            CorsOriginRestrictionMiddleware,
            allowed_origins=_CORS_ALLOWED_ORIGINS,
        ),
        Middleware(
            CORSMiddleware,
            allow_origins=list(_CORS_ALLOWED_ORIGINS),
            allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
            allow_headers=[
                "Content-Type",
                "Authorization",
                "Mcp-Session-Id",
                "Idempotency-Key",
            ],
            expose_headers=["Mcp-Session-Id"],
        ),
    ],
    lifespan=mcp_app.lifespan,
)
