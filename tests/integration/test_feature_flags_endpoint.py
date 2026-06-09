"""Integration test for the /api/feature-flags read-only endpoint."""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from routers.health import router as health_router


@pytest.fixture
def client():
    app = FastAPI()
    app.include_router(health_router)
    return TestClient(app)


def test_feature_flags_endpoint_returns_registry(client):
    r = client.get("/api/feature-flags")
    assert r.status_code == 200
    body = r.json()
    assert "flags" in body
    assert "count" in body
    assert body["count"] >= 7
    assert isinstance(body["flags"], list)


def test_feature_flags_entries_have_expected_shape(client):
    r = client.get("/api/feature-flags")
    flags = r.json()["flags"]
    for entry in flags:
        for key in ("name", "enabled", "default", "env_var", "owner", "scope", "description", "added"):
            assert key in entry, f"missing {key!r} in {entry.get('name', '?')}"
        assert isinstance(entry["enabled"], bool)
        assert isinstance(entry["default"], bool)


def test_known_pipeline_flag_present(client):
    flags = {f["name"]: f for f in client.get("/api/feature-flags").json()["flags"]}
    assert "use_own_llm" in flags
    assert flags["use_own_llm"]["scope"] == "pipeline"
    assert flags["use_own_llm"]["env_var"] == "USE_OWN_LLM"
