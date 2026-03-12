"""
reporting.py — Fire-and-forget usage reporting to external endpoint.

Reports job completion metrics to a Google Apps Script endpoint.
Failures are logged but NEVER affect the pipeline.
"""

import threading
from datetime import datetime, timezone

import requests

from config import AppConfig


def report_job_usage(
    config: AppConfig,
    job_id: str,
    total: int,
    passed: int,
    failed: int,
    elapsed_seconds: float,
    usage_snapshot: dict,
    status: str = "success",
):
    """Fire-and-forget: POST usage report in a background thread.

    Does nothing if reporting is not configured.
    Never raises exceptions to the caller.
    """
    endpoint = config.reporting.endpoint_url
    if not endpoint:
        return

    try:
        payload = _build_payload(
            config, job_id, total, passed, failed,
            elapsed_seconds, usage_snapshot, status,
        )
        thread = threading.Thread(
            target=_send_report,
            args=(endpoint, config.reporting.endpoint_token, payload, config.reporting.timeout),
            daemon=True,
        )
        thread.start()
    except Exception as e:
        print(f"[reporting] Failed to start report thread: {e}")


def _build_payload(
    config: AppConfig,
    job_id: str,
    total: int,
    passed: int,
    failed: int,
    elapsed_seconds: float,
    usage_snapshot: dict,
    status: str,
) -> dict:
    """Build the JSON payload for the reporting endpoint."""
    # Extract owner/repo from git URL
    website_section = ""
    try:
        from git_ops.github_api import GitHubAPI
        owner, repo_name = GitHubAPI.extract_repo_info(config.git.repo_url)
        if owner and repo_name:
            website_section = f"{owner}/{repo_name}"
    except Exception:
        pass

    return {
        "timestamp": datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z"),
        "agent_name": config.reporting.agent_name,
        "agent_owner": config.reporting.agent_owner,
        "job_type": "C# Example Generation",
        "run_id": job_id,
        "status": status,
        "product": "Aspose.PDF",
        "platform": ".NET",
        "website": "github.com",
        "website_section": website_section,
        "item_name": "Examples",
        "items_discovered": total,
        "items_failed": failed,
        "items_succeeded": passed,
        "run_duration_ms": int(elapsed_seconds * 1000),
        "token_usage": usage_snapshot.get("llm_tokens", 0),
        "api_calls_count": usage_snapshot.get("total_api_calls", 0),
    }


def _send_report(endpoint: str, token: str, payload: dict, timeout: int):
    """Send the report. Runs in a daemon thread. Swallows all errors."""
    try:
        url = f"{endpoint}?token={token}" if token else endpoint
        resp = requests.post(
            url,
            json=payload,
            timeout=timeout,
            headers={"Content-Type": "application/json"},
        )
        if resp.status_code < 300:
            print(f"[reporting] Usage report sent for job {payload.get('run_id', '?')}")
        else:
            print(f"[reporting] Report failed: HTTP {resp.status_code} - {resp.text[:200]}")
    except Exception as e:
        print(f"[reporting] Report failed: {e}")
