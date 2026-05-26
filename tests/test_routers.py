"""Tests for FastAPI routers — health, job status, cancel, pause, resume."""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from routers.health import router as health_router
from routers.jobs import router as jobs_router
from state import init_build, BUILD_STATE, JOB_CANCEL_FLAGS, JOB_PAUSE_EVENTS, JOB_LOCK


# ── Test app setup ─────────────────────────────────────────────────────────────

app = FastAPI()
app.include_router(health_router)
app.include_router(jobs_router)

client = TestClient(app, raise_server_exceptions=False)


@pytest.fixture(autouse=True)
def clean_state():
    yield
    with JOB_LOCK:
        BUILD_STATE.clear()
        JOB_CANCEL_FLAGS.clear()
        JOB_PAUSE_EVENTS.clear()


# ── /api/health ────────────────────────────────────────────────────────────────

def test_health_returns_ok():
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_health_includes_service_name():
    response = client.get("/api/health")
    assert "service" in response.json()


# ── /api/status/{job_id} ───────────────────────────────────────────────────────

def test_status_unknown_job_returns_404():
    response = client.get("/api/status/nonexistent-job")
    assert response.status_code == 404
    assert "not found" in response.json()["error"].lower()


def test_status_known_job_returns_state():
    init_build("job-001", total=5)
    response = client.get("/api/status/job-001")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "running"
    assert data["total"] == 5


def test_status_contains_progress_fields():
    init_build("job-002", total=10)
    response = client.get("/api/status/job-002")
    data = response.json()
    for field in ("passed_count", "failed_count", "processed", "pass_rate"):
        assert field in data


# ── /api/cancel/{job_id} ──────────────────────────────────────────────────────

def test_cancel_unknown_job_returns_404():
    response = client.post("/api/cancel/no-such-job")
    assert response.status_code == 404


def test_cancel_running_job_sets_flag():
    init_build("job-cancel-1", total=3)
    response = client.post("/api/cancel/job-cancel-1")
    assert response.status_code == 200
    assert response.json()["status"] == "cancel_requested"
    with JOB_LOCK:
        assert JOB_CANCEL_FLAGS.get("job-cancel-1") is True


def test_cancel_already_completed_job_returns_400():
    init_build("job-done", total=1)
    with JOB_LOCK:
        BUILD_STATE["job-done"]["status"] = "completed"
    response = client.post("/api/cancel/job-done")
    assert response.status_code == 400


# ── /api/pause/{job_id} ───────────────────────────────────────────────────────

def test_pause_unknown_job_returns_404():
    response = client.post("/api/pause/ghost-job")
    assert response.status_code == 404


def test_pause_running_job_returns_paused():
    init_build("job-pause-1", total=5)
    response = client.post("/api/pause/job-pause-1")
    assert response.status_code == 200
    assert response.json()["status"] == "paused"


def test_pause_non_running_job_returns_400():
    init_build("job-pause-2", total=5)
    with JOB_LOCK:
        BUILD_STATE["job-pause-2"]["status"] = "completed"
    response = client.post("/api/pause/job-pause-2")
    assert response.status_code == 400


def test_pause_already_paused_job_returns_400():
    init_build("job-pause-3", total=5)
    client.post("/api/pause/job-pause-3")  # first pause
    response = client.post("/api/pause/job-pause-3")  # second pause
    assert response.status_code == 400


# ── /api/start validation ─────────────────────────────────────────────────────

def test_start_invalid_mode_returns_400():
    response = client.post("/api/start", data={"mode": "invalid"})
    assert response.status_code == 400
    assert "invalid mode" in response.json()["error"].lower()


def test_start_single_without_prompt_returns_400():
    response = client.post("/api/start", data={"mode": "single", "prompt": ""})
    assert response.status_code == 400


def test_start_csv_without_file_returns_400():
    response = client.post("/api/start", data={"mode": "csv"})
    assert response.status_code == 400


# ── /api/start-tasks validation ───────────────────────────────────────────────

def test_start_tasks_without_tasks_or_categories_returns_400():
    response = client.post("/api/start-tasks", json={})
    assert response.status_code == 400
    assert "tasks" in response.json()["error"].lower() or "categories" in response.json()["error"].lower()


# ── /api/retry-pr/{job_id} ────────────────────────────────────────────────────

def test_retry_pr_unknown_job_returns_404():
    response = client.post("/api/retry-pr/ghost-job")
    assert response.status_code == 404


def test_retry_pr_running_job_returns_400():
    init_build("job-running", total=5)
    response = client.post("/api/retry-pr/job-running")
    assert response.status_code == 400


def test_retry_pr_no_passed_results_returns_400():
    init_build("job-empty", total=5)
    with JOB_LOCK:
        BUILD_STATE["job-empty"]["status"] = "completed"
    response = client.post("/api/retry-pr/job-empty")
    assert response.status_code == 400
