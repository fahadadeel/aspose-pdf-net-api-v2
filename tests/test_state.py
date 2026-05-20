"""Tests for state.py — in-memory job state management."""

import pytest
from state import (
    init_build, set_status, get_build_state, is_cancelled,
    add_passed, add_failed, add_log, pause_job, resume_job,
    is_paused, JOB_CANCEL_FLAGS, BUILD_STATE, JOB_PAUSE_EVENTS,
    JOB_LOCK,
)


@pytest.fixture(autouse=True)
def cleanup_state():
    """Clean up global state between tests."""
    yield
    with JOB_LOCK:
        BUILD_STATE.clear()
        JOB_CANCEL_FLAGS.clear()
        JOB_PAUSE_EVENTS.clear()


def test_job_lifecycle():
    job_id = "test-job-1"
    init_build(job_id, total=10)

    state = get_build_state(job_id)
    assert state["status"] == "running"
    assert state["total"] == 10
    assert state["passed_count"] == 0
    assert state["failed_count"] == 0

    add_passed(job_id, "t1", "Convert PDF", "baseline", code="// ok", category="Conversion")
    add_failed(job_id, "t2", "Bad task", "stage5", code="// fail", category="Conversion")

    state = get_build_state(job_id)
    assert state["passed_count"] == 1
    assert state["failed_count"] == 1
    assert state["processed"] == 2
    assert state["pass_rate"] == 50

    # Cancel
    with JOB_LOCK:
        JOB_CANCEL_FLAGS[job_id] = True
    assert is_cancelled(job_id) is True

    set_status(job_id, "cancelled")
    state = get_build_state(job_id)
    assert state["status"] == "cancelled"


def test_pause_resume():
    job_id = "test-job-2"
    init_build(job_id)

    assert is_paused(job_id) is False

    pause_job(job_id)
    assert is_paused(job_id) is True

    resume_job(job_id)
    assert is_paused(job_id) is False
