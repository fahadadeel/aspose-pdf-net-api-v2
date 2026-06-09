"""Contract tests — verify the live app matches its declared OpenAPI schema.

`schemathesis` reads the OpenAPI schema from the live ASGI app and generates
property-based requests for documented endpoints, then asserts the response
shape matches the declared schema. Catches drift between what the API
says it does and what it actually returns.

This is the foundation for full contract coverage. Today we run against a
small allowlist of well-defined, side-effect-free GET endpoints. As endpoint
schemas are tightened (explicit response_model, error responses declared,
etc.), more paths can be moved from `_TODO_PATHS` to `_ALLOWED_PATHS`.
"""

import os

import pytest

# schemathesis is optional locally — skip cleanly if not installed
schemathesis = pytest.importorskip("schemathesis", reason="schemathesis not installed")


# Set CORS_ORIGINS before importing main (CORS middleware reads it once at
# import time). Include http://example.test so test_app_integration's CORS
# checks continue to pass regardless of which test file pytest imports first.
os.environ.setdefault("CORS_ORIGINS", "http://localhost:7103,http://example.test")

from main import app  # noqa: E402  -- intentional, must follow env setup


# Endpoints whose schema + response shape are confirmed to match.
# Adding to this list is a deliberate act: the response must match the
# declared schema for all generated inputs schemathesis throws at it.
_ALLOWED_PATHS = {
    "/api/health",
    "/api/version",
    "/api/metrics",
    "/api/auto-fixes",
    "/api/results",
    "/api/repo-categories",
}

# Endpoints we know need schema tightening before they can be contract-tested.
# Tracked here so the gap is visible and the test scope grows over time.
_TODO_PATHS = {
    "/api/status/{job_id}",          # response model is the raw build state dict
    "/api/failed-tasks/{category}",  # 404 path not declared
    "/api/results/sync-status",      # response model incomplete
    "/api/results/{category}",       # 404 path not declared
    "/api/tasks",                    # external API proxy, depends on upstream
}


# Build the schema from the live ASGI app, no network involved.
_schema = schemathesis.openapi.from_asgi("/openapi.json", app=app)


@_schema.parametrize()
def test_api_matches_openapi_schema(case):
    """Documented endpoints return responses that match the OpenAPI schema."""
    path = case.path
    if path not in _ALLOWED_PATHS:
        pytest.skip(f"{case.method.upper()} {path} not yet in contract allowlist")
    response = case.call()
    case.validate_response(response)
