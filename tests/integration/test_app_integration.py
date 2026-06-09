"""Integration tests against the full FastAPI app (main.app).

These tests boot the actual app (including all routers, CORS middleware, and
the MCP mount) via FastAPI TestClient — closer to a real request than the
isolated router tests in test_routers.py.
"""

import os

import pytest
from fastapi.testclient import TestClient


@pytest.fixture(scope="module")
def app_client():
    # Force a known CORS origin set before importing main
    os.environ["CORS_ORIGINS"] = "http://localhost:7103,http://example.test"
    # Importing main has side effects (router registration, MCP mount) so
    # we do it lazily inside the fixture.
    from main import app
    return TestClient(app, raise_server_exceptions=False)


# ── Smoke: app boots and core endpoints respond ────────────────────────────

def test_health_endpoint_responds(app_client):
    r = app_client.get("/api/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert "service" in body


def test_index_page_renders(app_client):
    r = app_client.get("/")
    assert r.status_code == 200
    assert "text/html" in r.headers.get("content-type", "")


def test_results_v2_page_renders(app_client):
    r = app_client.get("/results-v2")
    assert r.status_code == 200
    assert "text/html" in r.headers.get("content-type", "")


# ── CORS middleware actually applies configured origins ─────────────────────

def test_cors_allows_configured_origin(app_client):
    r = app_client.options(
        "/api/health",
        headers={
            "Origin": "http://example.test",
            "Access-Control-Request-Method": "GET",
        },
    )
    # Either preflight succeeded or the request returned an OK status —
    # what matters is the access-control header is present for the
    # configured origin.
    allow = r.headers.get("access-control-allow-origin", "")
    assert allow == "http://example.test"


def test_cors_rejects_unlisted_origin(app_client):
    r = app_client.options(
        "/api/health",
        headers={
            "Origin": "http://attacker.test",
            "Access-Control-Request-Method": "GET",
        },
    )
    allow = r.headers.get("access-control-allow-origin", "")
    assert allow != "http://attacker.test"


# ── MCP mount exposes the /mcp endpoint ─────────────────────────────────────

def test_mcp_endpoint_mounted(app_client):
    # /mcp is an SSE stream so a GET would hang; instead inspect the
    # registered routes to confirm FastApiMCP.mount() ran.
    from main import app
    paths = {route.path for route in app.routes if hasattr(route, "path")}
    assert "/mcp" in paths, f"/mcp not in registered routes: {sorted(paths)}"


# ── Validation: unknown job ID handling stays consistent ────────────────────

def test_status_unknown_job_full_app(app_client):
    r = app_client.get("/api/status/integration-ghost-job")
    assert r.status_code == 404
    assert "error" in r.json()


def test_cancel_unknown_job_full_app(app_client):
    r = app_client.post("/api/cancel/integration-ghost-job")
    assert r.status_code == 404


# ── Update README endpoint kicks off a job ──────────────────────────────────

def test_update_readme_endpoint_returns_job_id(app_client, monkeypatch):
    # Stub the worker so the test doesn't talk to GitHub
    import jobs as jobs_module
    called = {}

    def fake_runner(job_id):
        called["job_id"] = job_id

    monkeypatch.setattr(jobs_module, "run_update_readme", fake_runner)
    # Routers import the symbol at module load time, so patch there too
    import routers.jobs as jobs_router
    monkeypatch.setattr(jobs_router, "run_update_readme", fake_runner)

    r = app_client.post("/api/update-readme")
    assert r.status_code == 200
    body = r.json()
    assert "job_id" in body
    assert len(body["job_id"]) > 0
