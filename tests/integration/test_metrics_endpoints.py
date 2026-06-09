"""Integration tests for /api/health, /api/version, /api/metrics."""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from routers.health import router as health_router
from state import init_build, BUILD_STATE, JOB_LOCK


@pytest.fixture
def client():
    app = FastAPI()
    app.include_router(health_router)
    return TestClient(app)


@pytest.fixture(autouse=True)
def clean_state():
    yield
    with JOB_LOCK:
        BUILD_STATE.clear()


# ── /api/version ────────────────────────────────────────────────────────────

def test_version_returns_expected_fields(client):
    r = client.get("/api/version")
    assert r.status_code == 200
    body = r.json()
    assert body["service"] == "aspose-examples-generator"
    assert "version" in body
    assert "nuget_version" in body
    assert "build_tfm" in body


# ── /api/metrics ────────────────────────────────────────────────────────────

def test_metrics_empty_state(client):
    r = client.get("/api/metrics")
    assert r.status_code == 200
    body = r.json()
    assert body["service"] == "aspose-examples-generator"
    assert body["uptime_seconds"] >= 0
    assert isinstance(body["uptime_human"], str)
    assert body["jobs"]["total"] == 0
    assert body["jobs"]["active"] == 0
    assert body["examples"]["total_passed"] == 0
    assert body["examples"]["pass_rate_pct"] is None  # no data → None


def test_metrics_counts_jobs_by_status(client):
    init_build("job-active", total=5)
    init_build("job-completed", total=3)
    init_build("job-failed", total=2)

    with JOB_LOCK:
        BUILD_STATE["job-completed"]["status"] = "completed"
        BUILD_STATE["job-completed"]["passed_count"] = 3
        BUILD_STATE["job-failed"]["status"] = "failed"
        BUILD_STATE["job-failed"]["failed_count"] = 2

    r = client.get("/api/metrics")
    assert r.status_code == 200
    body = r.json()
    assert body["jobs"]["total"] == 3
    assert body["jobs"]["active"] == 1
    assert body["jobs"]["completed"] == 1
    assert body["jobs"]["failed"] == 1


def test_metrics_pass_rate_calculation(client):
    init_build("job-stats", total=10)
    with JOB_LOCK:
        BUILD_STATE["job-stats"]["passed_count"] = 8
        BUILD_STATE["job-stats"]["failed_count"] = 2

    r = client.get("/api/metrics")
    body = r.json()
    assert body["examples"]["total_passed"] == 8
    assert body["examples"]["total_failed"] == 2
    assert body["examples"]["total_processed"] == 10
    assert body["examples"]["pass_rate_pct"] == 80.0


def test_metrics_paused_job_counted(client):
    init_build("job-paused", total=5)
    with JOB_LOCK:
        BUILD_STATE["job-paused"]["paused"] = True

    r = client.get("/api/metrics")
    body = r.json()
    assert body["jobs"]["paused"] == 1


def test_metrics_uptime_human_format(client):
    r = client.get("/api/metrics")
    body = r.json()
    # Process just started in this test run → minutes-only format
    assert "m" in body["uptime_human"]


# ── /api/health (regression) ───────────────────────────────────────────────

def test_health_endpoint_still_works(client):
    r = client.get("/api/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"
