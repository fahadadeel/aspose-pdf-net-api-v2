"""Integration tests for SecurityHeadersMiddleware and APIKeyMiddleware."""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from middleware.security import SecurityHeadersMiddleware, APIKeyMiddleware


# ── Security headers ────────────────────────────────────────────────────────

@pytest.fixture
def headers_client():
    app = FastAPI()
    app.add_middleware(SecurityHeadersMiddleware)

    @app.get("/ping")
    def ping():
        return {"ok": True}

    @app.get("/api/anything")
    def anything():
        return {"ok": True}

    return TestClient(app)


def test_security_headers_present_on_every_response(headers_client):
    r = headers_client.get("/ping")
    assert r.status_code == 200
    assert r.headers["X-Content-Type-Options"] == "nosniff"
    assert r.headers["X-Frame-Options"] == "DENY"
    assert r.headers["Referrer-Policy"] == "no-referrer"
    assert "geolocation=()" in r.headers["Permissions-Policy"]
    assert "max-age=" in r.headers["Strict-Transport-Security"]


def test_security_headers_apply_to_api_paths(headers_client):
    r = headers_client.get("/api/anything")
    assert r.headers["X-Frame-Options"] == "DENY"


# ── API key gate ────────────────────────────────────────────────────────────

def _build_api_key_app(api_key: str = "secret-key-123"):
    """Helper that builds a fresh app with APIKeyMiddleware reading a known key.

    The middleware reads API_KEY from env at instantiation, so monkeypatch
    must run before app creation.
    """
    app = FastAPI()

    @app.get("/api/protected")
    def protected():
        return {"ok": True}

    @app.get("/api/health")
    def health():
        return {"ok": True}

    @app.get("/")
    def root():
        return {"ok": True}

    @app.add_middleware  # type: ignore[misc]
    def _noop(_app):
        return _app

    # Add the real middleware
    app.user_middleware = []
    app.middleware_stack = None
    app.add_middleware(APIKeyMiddleware)
    return app


def test_no_api_key_means_open_endpoints(monkeypatch):
    monkeypatch.delenv("API_KEY", raising=False)

    app = FastAPI()
    app.add_middleware(APIKeyMiddleware)

    @app.get("/api/protected")
    def protected():
        return {"ok": True}

    client = TestClient(app)
    r = client.get("/api/protected")
    assert r.status_code == 200


def test_api_key_blocks_without_header(monkeypatch):
    monkeypatch.setenv("API_KEY", "secret-key-xyz")

    app = FastAPI()
    app.add_middleware(APIKeyMiddleware)

    @app.get("/api/protected")
    def protected():
        return {"ok": True}

    client = TestClient(app)
    r = client.get("/api/protected")
    assert r.status_code == 401
    assert "Unauthorized" in r.json().get("error", "")


def test_api_key_allows_with_x_api_key_header(monkeypatch):
    monkeypatch.setenv("API_KEY", "secret-key-xyz")

    app = FastAPI()
    app.add_middleware(APIKeyMiddleware)

    @app.get("/api/protected")
    def protected():
        return {"ok": True}

    client = TestClient(app)
    r = client.get("/api/protected", headers={"X-API-Key": "secret-key-xyz"})
    assert r.status_code == 200


def test_api_key_allows_with_bearer_header(monkeypatch):
    monkeypatch.setenv("API_KEY", "secret-key-xyz")

    app = FastAPI()
    app.add_middleware(APIKeyMiddleware)

    @app.get("/api/protected")
    def protected():
        return {"ok": True}

    client = TestClient(app)
    r = client.get("/api/protected", headers={"Authorization": "Bearer secret-key-xyz"})
    assert r.status_code == 200


def test_api_key_rejects_wrong_key(monkeypatch):
    monkeypatch.setenv("API_KEY", "secret-key-xyz")

    app = FastAPI()
    app.add_middleware(APIKeyMiddleware)

    @app.get("/api/protected")
    def protected():
        return {"ok": True}

    client = TestClient(app)
    r = client.get("/api/protected", headers={"X-API-Key": "wrong-key"})
    assert r.status_code == 401


def test_api_key_health_endpoint_still_public(monkeypatch):
    """/api/health must stay reachable for monitoring even when API_KEY is set."""
    monkeypatch.setenv("API_KEY", "secret-key-xyz")

    app = FastAPI()
    app.add_middleware(APIKeyMiddleware)

    @app.get("/api/health")
    def health():
        return {"ok": True}

    client = TestClient(app)
    r = client.get("/api/health")
    assert r.status_code == 200


def test_api_key_does_not_gate_non_api_paths(monkeypatch):
    """Static / UI routes are not gated even with API_KEY set."""
    monkeypatch.setenv("API_KEY", "secret-key-xyz")

    app = FastAPI()
    app.add_middleware(APIKeyMiddleware)

    @app.get("/")
    def root():
        return {"ok": True}

    client = TestClient(app)
    r = client.get("/")
    assert r.status_code == 200


def test_api_key_accepts_query_string(monkeypatch):
    """EventSource (SSE) can't send custom headers, so the middleware
    falls back to the ?api_key=... query string."""
    monkeypatch.setenv("API_KEY", "secret-key-xyz")

    app = FastAPI()
    app.add_middleware(APIKeyMiddleware)

    @app.get("/api/protected")
    def protected():
        return {"ok": True}

    client = TestClient(app)
    r = client.get("/api/protected?api_key=secret-key-xyz")
    assert r.status_code == 200


def test_api_key_query_string_rejects_wrong_value(monkeypatch):
    monkeypatch.setenv("API_KEY", "secret-key-xyz")

    app = FastAPI()
    app.add_middleware(APIKeyMiddleware)

    @app.get("/api/protected")
    def protected():
        return {"ok": True}

    client = TestClient(app)
    r = client.get("/api/protected?api_key=wrong")
    assert r.status_code == 401


def test_api_key_header_takes_precedence_over_query_string(monkeypatch):
    """If both are present, the header wins (defence in depth: a leaked
    URL with a stale ?api_key=... won't override a fresh header)."""
    monkeypatch.setenv("API_KEY", "secret-key-xyz")

    app = FastAPI()
    app.add_middleware(APIKeyMiddleware)

    @app.get("/api/protected")
    def protected():
        return {"ok": True}

    client = TestClient(app)
    # Right header, wrong query — should pass because header is checked first
    r = client.get("/api/protected?api_key=wrong",
                   headers={"X-API-Key": "secret-key-xyz"})
    assert r.status_code == 200
