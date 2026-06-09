"""
routers/health.py -- GET /api/health, /api/metrics, /api/version
"""

import os
import time

from fastapi import APIRouter

router = APIRouter()

# Service start timestamp captured at module import (process startup)
_START_TS = time.time()

# Cached service version — read once at import
_VERSION = os.getenv("SERVICE_VERSION", "2.0.0")


@router.get("/api/health")
async def health():
    return {"status": "ok", "service": "aspose-examples-generator"}


@router.get("/api/version")
async def version():
    """Service version and build identity. Useful for deployment verification."""
    return {
        "service": "aspose-examples-generator",
        "version": _VERSION,
        "nuget_version": os.getenv("NUGET_VERSION", ""),
        "build_tfm": os.getenv("BUILD_TFM", "net10.0"),
    }


@router.get("/api/metrics")
async def metrics():
    """Lightweight operational metrics — uptime, active jobs, totals.

    Designed for status pages, dashboards, and simple polling — not a
    Prometheus replacement. For Prometheus scraping, expose this via a
    sidecar or extend with the prometheus_client library.
    """
    from state import BUILD_STATE, JOB_LOCK

    now = time.time()
    uptime_seconds = int(now - _START_TS)

    with JOB_LOCK:
        jobs = list(BUILD_STATE.values())

    total_jobs = len(jobs)
    active = sum(1 for j in jobs if j.get("status") == "running")
    paused = sum(1 for j in jobs if j.get("paused"))
    completed = sum(1 for j in jobs if j.get("status") in ("completed", "done"))
    failed_jobs = sum(1 for j in jobs if j.get("status") == "failed")
    cancelled = sum(1 for j in jobs if j.get("status") == "cancelled")

    total_passed = sum(j.get("passed_count", 0) for j in jobs)
    total_failed = sum(j.get("failed_count", 0) for j in jobs)
    total_processed = total_passed + total_failed
    pass_rate = round(100.0 * total_passed / total_processed, 2) if total_processed else None

    return {
        "service": "aspose-examples-generator",
        "version": _VERSION,
        "uptime_seconds": uptime_seconds,
        "uptime_human": _format_uptime(uptime_seconds),
        "jobs": {
            "total": total_jobs,
            "active": active,
            "paused": paused,
            "completed": completed,
            "failed": failed_jobs,
            "cancelled": cancelled,
        },
        "examples": {
            "total_passed": total_passed,
            "total_failed": total_failed,
            "total_processed": total_processed,
            "pass_rate_pct": pass_rate,
        },
    }


def _format_uptime(seconds: int) -> str:
    """Render uptime as 'Xd Yh Zm' or 'Xh Ym' for shorter durations."""
    days, rem = divmod(seconds, 86400)
    hours, rem = divmod(rem, 3600)
    minutes, _ = divmod(rem, 60)
    if days:
        return f"{days}d {hours}h {minutes}m"
    if hours:
        return f"{hours}h {minutes}m"
    return f"{minutes}m"
