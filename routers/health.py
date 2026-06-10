"""
routers/health.py -- GET /api/health, /api/health/ready, /api/version, /api/metrics, /api/metrics/prometheus
"""

import os
import shutil
import subprocess
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

from fastapi import APIRouter
from fastapi.responses import JSONResponse

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


@router.get("/api/feature-flags")
async def feature_flags():
    """Read-only view of the feature flag registry with resolved values.

    Source of truth is `resources/feature_flags.json`. Values shown
    here reflect env-var overrides at the time of the request.
    """
    import features

    registry = features.list_flags()
    resolved = features.snapshot()

    return {
        "flags": [
            {
                "name": name,
                "enabled": resolved.get(name, False),
                "default": entry.get("default", False),
                "env_var": entry.get("env_var", ""),
                "owner": entry.get("owner", ""),
                "scope": entry.get("scope", ""),
                "description": entry.get("description", ""),
                "added": entry.get("added", ""),
            }
            for name, entry in sorted(registry.items())
        ],
        "count": len(registry),
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

    # Self-learning convergence: how many promoted patterns have actually
    # fired since promotion. Defensive: never let a metrics read crash
    # the endpoint.
    try:
        from config import load_config
        from knowledge.pattern_tracker import get_effectiveness_stats
        cfg = load_config()
        patterns = get_effectiveness_stats(cfg.auto_patterns_path)
    except Exception:
        patterns = {
            "total_patterns": 0,
            "active_patterns": 0,
            "dormant_patterns": 0,
            "total_hits": 0,
            "hit_rate": 0.0,
        }

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
        "patterns": patterns,
    }


# ── Deep health check ────────────────────────────────────────────────────────
# Probes downstream dependencies so external monitoring can distinguish
# "service responding" (/api/health) from "service can actually do work"
# (/api/health/ready). Each probe is isolated so tests can patch one at a time.

_HTTP_PROBE_TIMEOUT = 3.0
_DOTNET_PROBE_TIMEOUT = 5.0
_DISK_MIN_HEALTHY_GB = 1.0
_DISK_MIN_DEGRADED_GB = 0.1


def _probe_http(url: str, headers: dict | None = None, timeout: float = _HTTP_PROBE_TIMEOUT) -> dict:
    """Probe an HTTP endpoint. Any HTTP response (even 4xx) proves the server
    is reachable; only connection-level failures count as unhealthy."""
    start = time.time()
    try:
        req = urllib.request.Request(url, headers=headers or {})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return {
                "status": "healthy",
                "code": resp.status,
                "latency_ms": int((time.time() - start) * 1000),
            }
    except urllib.error.HTTPError as e:
        return {
            "status": "degraded" if e.code >= 500 else "healthy",
            "code": e.code,
            "latency_ms": int((time.time() - start) * 1000),
        }
    except urllib.error.URLError as e:
        reason = getattr(e, "reason", e)
        return {"status": "unhealthy", "detail": str(reason)[:80]}
    except (TimeoutError, OSError) as e:
        return {"status": "unhealthy", "detail": str(e)[:80]}


def _probe_mcp(generate_url: str) -> dict:
    """Probe the MCP server root (not the /generate path — we don't want to
    actually trigger generation)."""
    parsed = urlparse(generate_url)
    if not parsed.scheme or not parsed.netloc:
        return {"status": "unhealthy", "detail": "MCP URL not configured"}
    base = f"{parsed.scheme}://{parsed.netloc}"
    return _probe_http(base)


def _probe_llm(api_base: str, api_key: str) -> dict:
    """Probe the LLM proxy's /models endpoint (standard, cheap, returns the
    model list)."""
    if not api_base:
        return {"status": "unhealthy", "detail": "LLM api_base not configured"}
    headers = {}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    url = api_base.rstrip("/") + "/models"
    return _probe_http(url, headers=headers)


def _probe_disk(path: str = ".") -> dict:
    """Probe free disk space on the partition holding ``path``."""
    try:
        usage = shutil.disk_usage(path)
    except Exception as e:
        return {"status": "unhealthy", "detail": str(e)[:80]}
    free_gb = usage.free / (1024 ** 3)
    if free_gb < _DISK_MIN_DEGRADED_GB:
        status = "unhealthy"
    elif free_gb < _DISK_MIN_HEALTHY_GB:
        status = "degraded"
    else:
        status = "healthy"
    return {"status": status, "free_gb": round(free_gb, 2)}


def _probe_dotnet(timeout: float = _DOTNET_PROBE_TIMEOUT) -> dict:
    """Probe the dotnet CLI — the .NET SDK is required for the build stage."""
    try:
        result = subprocess.run(
            ["dotnet", "--version"],
            timeout=timeout,
            capture_output=True,
            text=True,
            check=False,
        )
    except FileNotFoundError:
        return {"status": "unhealthy", "detail": "dotnet CLI not found in PATH"}
    except subprocess.TimeoutExpired:
        return {"status": "unhealthy", "detail": "dotnet --version timed out"}
    except Exception as e:
        return {"status": "unhealthy", "detail": str(e)[:80]}

    if result.returncode != 0:
        return {"status": "unhealthy", "detail": (result.stderr or "non-zero exit")[:80]}
    return {"status": "healthy", "version": result.stdout.strip()}


def _probe_repo_path(repo_path: str) -> dict:
    """Probe that REPO_PATH is set and points at an existing directory."""
    if not repo_path:
        return {"status": "unhealthy", "detail": "REPO_PATH not configured"}
    if not Path(repo_path).is_dir():
        return {"status": "unhealthy", "detail": f"not a directory: {repo_path}"}
    return {"status": "healthy", "path": repo_path}


@router.get("/api/health/ready")
async def health_ready():
    """Deep health check — probes downstream dependencies.

    Returns:
        200 + `status: healthy` — every probe passed
        200 + `status: degraded` — at least one degraded probe, no unhealthy
        503 + `status: unhealthy` — at least one unhealthy probe
    """
    from config import load_config
    cfg = load_config()

    checks = {
        "mcp": _probe_mcp(cfg.mcp.generate_url),
        "llm": _probe_llm(cfg.llm.api_base, cfg.llm.api_key),
        "disk": _probe_disk(),
        "dotnet": _probe_dotnet(),
        "repo_path": _probe_repo_path(cfg.git.repo_path),
    }

    has_unhealthy = any(c.get("status") == "unhealthy" for c in checks.values())
    has_degraded = any(c.get("status") == "degraded" for c in checks.values())

    if has_unhealthy:
        overall, code = "unhealthy", 503
    elif has_degraded:
        overall, code = "degraded", 200
    else:
        overall, code = "healthy", 200

    return JSONResponse(
        status_code=code,
        content={
            "status": overall,
            "checks": checks,
            "timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
        },
    )


# ── Prometheus exposition ──────────────────────────────────────────────────
# Standard scraping endpoint for Prometheus / Grafana / etc. Returns the
# text format defined in https://prometheus.io/docs/instrumenting/exposition_formats/.

@router.get("/api/metrics/prometheus")
async def metrics_prometheus():
    """Prometheus exposition format. Returns all defined counters, gauges,
    and histograms in plain text for scraping."""
    from fastapi.responses import Response
    from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

    import metrics as m

    # Keep the uptime gauge fresh on every scrape
    m.UPTIME_SECONDS.set(time.time() - _START_TS)

    # Refresh pattern-effectiveness gauges from disk on every scrape
    # (cheap — the patterns file is small)
    try:
        from config import load_config
        from knowledge.pattern_tracker import get_effectiveness_stats
        cfg = load_config()
        stats = get_effectiveness_stats(cfg.auto_patterns_path)
        m.PATTERN_HIT_RATE.set(stats["hit_rate"])
        m.PATTERN_TOTAL.set(stats["total_patterns"])
    except Exception:
        pass

    return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)


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
