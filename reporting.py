"""
reporting.py — Fire-and-forget usage reporting to external endpoint.

Reports job completion metrics to a Google Apps Script endpoint.
Also logs each report locally to usage_reports.jsonl for review.
Failures are logged but NEVER affect the pipeline.

Config switches:
  REPORTING_ENABLED      — master switch (default: true)
  REPORTING_LOG_TO_FILE  — write each report to usage_reports.jsonl (default: true)
  REPORTING_ENDPOINT_URL — if empty, remote POST is skipped (local log still works)
"""

import json
import threading
from datetime import datetime, timezone
from pathlib import Path

import requests

from config import AppConfig

# Local log file — one JSON object per line, appended after each run
_LOG_FILE = Path("usage_reports.jsonl")


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
    """Fire-and-forget: log locally + POST usage report in a background thread.

    Does nothing if reporting is disabled via config.
    Never raises exceptions to the caller.
    """
    if not config.reporting.enabled:
        return

    try:
        payload = _build_payload(
            config, job_id, total, passed, failed,
            elapsed_seconds, usage_snapshot, status,
        )

        # Always log locally first (synchronous, fast)
        if config.reporting.log_to_file:
            _log_to_file(payload)

        # POST to remote endpoint in background (only if configured)
        endpoint = config.reporting.endpoint_url
        if endpoint:
            thread = threading.Thread(
                target=_send_report,
                args=(endpoint, config.reporting.endpoint_token, payload, config.reporting.timeout),
                daemon=True,
            )
            thread.start()
    except Exception as e:
        print(f"[reporting] Failed to start report: {e}")


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
    return {
        "timestamp": datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z"),
        "agent_name": config.reporting.agent_name,
        "agent_owner": config.reporting.agent_owner,
        "job_type": "C# Example Generation",
        "run_id": job_id,
        "status": status,
        "product": "Aspose.PDF",
        "platform": ".NET",
        "website": config.reporting.website,
        "website_section": config.reporting.website_section,
        "item_name": "Examples",
        "items_discovered": total,
        "items_failed": failed,
        "items_succeeded": passed,
        "run_duration_ms": int(elapsed_seconds * 1000),
        "token_usage": usage_snapshot.get("llm_tokens", 0),
        "api_calls_count": usage_snapshot.get("total_api_calls", 0),
    }


def _log_to_file(payload: dict):
    """Append one JSON line to the local log file."""
    try:
        with open(_LOG_FILE, "a", encoding="utf-8") as f:
            f.write(json.dumps(payload) + "\n")
        print(f"[reporting] Logged to {_LOG_FILE}")
    except Exception as e:
        print(f"[reporting] File log failed: {e}")


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
