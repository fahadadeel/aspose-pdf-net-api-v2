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


# ── /api/health/ready (deep health check) ───────────────────────────────────

def _stub_all_healthy(monkeypatch):
    """Patch every probe to return a healthy result."""
    import routers.health as h
    monkeypatch.setattr(h, "_probe_mcp", lambda _u: {"status": "healthy", "code": 200, "latency_ms": 5})
    monkeypatch.setattr(h, "_probe_llm", lambda _b, _k: {"status": "healthy", "code": 200, "latency_ms": 12})
    monkeypatch.setattr(h, "_probe_disk", lambda *a, **k: {"status": "healthy", "free_gb": 84.2})
    monkeypatch.setattr(h, "_probe_dotnet", lambda *a, **k: {"status": "healthy", "version": "10.0.100"})
    monkeypatch.setattr(h, "_probe_repo_path", lambda _p: {"status": "healthy", "path": "/repo"})


def test_health_ready_all_healthy(client, monkeypatch):
    _stub_all_healthy(monkeypatch)
    r = client.get("/api/health/ready")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "healthy"
    for name in ("mcp", "llm", "disk", "dotnet", "repo_path"):
        assert body["checks"][name]["status"] == "healthy"
    assert "timestamp" in body


def test_health_ready_unhealthy_mcp_returns_503(client, monkeypatch):
    _stub_all_healthy(monkeypatch)
    import routers.health as h
    monkeypatch.setattr(h, "_probe_mcp", lambda _u: {"status": "unhealthy", "detail": "Connection refused"})

    r = client.get("/api/health/ready")
    assert r.status_code == 503
    body = r.json()
    assert body["status"] == "unhealthy"
    assert body["checks"]["mcp"]["status"] == "unhealthy"


def test_health_ready_degraded_disk_returns_200(client, monkeypatch):
    _stub_all_healthy(monkeypatch)
    import routers.health as h
    monkeypatch.setattr(h, "_probe_disk", lambda *a, **k: {"status": "degraded", "free_gb": 0.5})

    r = client.get("/api/health/ready")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "degraded"
    assert body["checks"]["disk"]["status"] == "degraded"


def test_health_ready_dotnet_missing(client, monkeypatch):
    _stub_all_healthy(monkeypatch)
    import routers.health as h
    monkeypatch.setattr(
        h, "_probe_dotnet",
        lambda *a, **k: {"status": "unhealthy", "detail": "dotnet CLI not found in PATH"},
    )

    r = client.get("/api/health/ready")
    assert r.status_code == 503
    body = r.json()
    assert body["checks"]["dotnet"]["status"] == "unhealthy"
    assert "not found" in body["checks"]["dotnet"]["detail"]


def test_health_ready_repo_path_unset(client, monkeypatch):
    _stub_all_healthy(monkeypatch)
    import routers.health as h
    monkeypatch.setattr(h, "_probe_repo_path", lambda _p: {"status": "unhealthy", "detail": "REPO_PATH not configured"})

    r = client.get("/api/health/ready")
    assert r.status_code == 503
    assert r.json()["checks"]["repo_path"]["status"] == "unhealthy"


# ── Probe-level unit-ish tests ──────────────────────────────────────────────

def test_probe_disk_classifies_levels(monkeypatch):
    """Disk probe boundary tests — use a stub that returns controllable usage."""
    import routers.health as h
    from collections import namedtuple
    Usage = namedtuple("Usage", "total used free")
    GB = 1024 ** 3

    monkeypatch.setattr(h.shutil, "disk_usage", lambda _p: Usage(100 * GB, 0, 50 * GB))
    assert h._probe_disk()["status"] == "healthy"

    monkeypatch.setattr(h.shutil, "disk_usage", lambda _p: Usage(100 * GB, 0, int(0.5 * GB)))
    assert h._probe_disk()["status"] == "degraded"

    monkeypatch.setattr(h.shutil, "disk_usage", lambda _p: Usage(100 * GB, 0, int(0.05 * GB)))
    assert h._probe_disk()["status"] == "unhealthy"


def test_probe_repo_path_unset():
    import routers.health as h
    assert h._probe_repo_path("")["status"] == "unhealthy"


def test_probe_repo_path_missing_dir():
    import routers.health as h
    assert h._probe_repo_path("/no/such/path/exists")["status"] == "unhealthy"


def test_probe_repo_path_exists(tmp_path):
    import routers.health as h
    res = h._probe_repo_path(str(tmp_path))
    assert res["status"] == "healthy"
    assert res["path"] == str(tmp_path)


def test_probe_mcp_handles_missing_url():
    import routers.health as h
    assert h._probe_mcp("")["status"] == "unhealthy"


def test_probe_llm_handles_missing_base():
    import routers.health as h
    assert h._probe_llm("", "")["status"] == "unhealthy"
