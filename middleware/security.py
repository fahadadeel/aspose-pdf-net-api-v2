"""
middleware/security.py -- Security headers and optional API key auth.

- SecurityHeadersMiddleware: adds common defensive headers to every response.
- APIKeyMiddleware: if API_KEY env var is set, requires X-API-Key header
  matching it on every /api/* request (read endpoints excluded by default).
  When API_KEY is unset, the middleware is a no-op — keeps local dev simple.
"""

import os

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse


# Routes that the middleware should never gate, even when API_KEY is set.
# Health and the index page must remain reachable for monitoring + UI.
_PUBLIC_PATHS = {"/api/health", "/api/health/ready", "/api/metrics/prometheus", "/", "/results", "/results-v2"}


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Adds defensive HTTP response headers.

    Headers chosen to satisfy common security scanners without breaking
    the streaming SSE endpoint or static HTML pages.
    """

    async def dispatch(self, request, call_next):
        response = await call_next(request)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "no-referrer")
        response.headers.setdefault("Permissions-Policy", "geolocation=(), microphone=(), camera=()")
        # HSTS only meaningful behind HTTPS; harmless on plain HTTP clients.
        response.headers.setdefault("Strict-Transport-Security", "max-age=31536000; includeSubDomains")
        return response


class APIKeyMiddleware(BaseHTTPMiddleware):
    """Optional API key gate on /api/* endpoints.

    Activated by setting the API_KEY env var.  Compares against either:
        X-API-Key: <key>
        Authorization: Bearer <key>
    Unauthenticated requests get 401.
    Local dev: leave API_KEY unset and the middleware is a no-op.
    """

    def __init__(self, app):
        super().__init__(app)
        self._expected_key = os.getenv("API_KEY", "").strip()

    async def dispatch(self, request, call_next):
        if not self._expected_key:
            return await call_next(request)

        path = request.url.path
        if not path.startswith("/api/"):
            return await call_next(request)
        if path in _PUBLIC_PATHS:
            return await call_next(request)

        provided = request.headers.get("X-API-Key", "").strip()
        if not provided:
            auth = request.headers.get("Authorization", "")
            if auth.lower().startswith("bearer "):
                provided = auth.split(" ", 1)[1].strip()

        if provided != self._expected_key:
            return JSONResponse({"error": "Unauthorized"}, status_code=401)

        return await call_next(request)
