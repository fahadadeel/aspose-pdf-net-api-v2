"""
state.py — Shared in-process state for Build Monitor.

Thread-safe via JOB_LOCK. All access to BUILD_STATE and JOB_CANCEL_FLAGS
must go through the helper functions or be protected with JOB_LOCK.

Fully in-memory — no database. Everything is lost on restart.
"""

import json
import time
import threading
from datetime import datetime, timezone
from typing import Dict, List, Optional

JOB_LOCK = threading.Lock()

BUILD_STATE: Dict[str, dict] = {}
JOB_CANCEL_FLAGS: Dict[str, bool] = {}
JOB_NOTIFY: Dict[str, List[threading.Event]] = {}

_MAX_LOGS = 500


# ── SSE listener management ────────────────────────────────────────────────

def register_listener(job_id: str) -> threading.Event:
    evt = threading.Event()
    with JOB_LOCK:
        JOB_NOTIFY.setdefault(job_id, []).append(evt)
    return evt


def unregister_listener(job_id: str, evt: threading.Event):
    with JOB_LOCK:
        listeners = JOB_NOTIFY.get(job_id, [])
        try:
            listeners.remove(evt)
        except ValueError:
            pass
        if not listeners:
            JOB_NOTIFY.pop(job_id, None)


def _notify_listeners(job_id: str):
    with JOB_LOCK:
        for evt in JOB_NOTIFY.get(job_id, []):
            evt.set()


# ── Build state management ─────────────────────────────────────────────────

def init_build(job_id: str, total: int = 0):
    with JOB_LOCK:
        BUILD_STATE[job_id] = {
            "status": "running",
            "total": total,
            "passed": [],
            "failed": [],
            "logs": [],
            "current_task": "",
            "start_time": time.monotonic(),
            "pr_url": "",
            "pr_branch": "",
            "results_summary": [],
        }
        JOB_CANCEL_FLAGS[job_id] = False
    _notify_listeners(job_id)


def add_passed(job_id: str, task_id: str, task: str, badge: str, code: str = "", category: str = "", product: str = "", metadata: dict = None):
    with JOB_LOCK:
        state = BUILD_STATE.get(job_id)
        if state:
            state["passed"].append({
                "id": task_id, "task": task, "badge": badge,
                "code": code, "category": category, "product": product,
                "metadata": metadata or {},
            })
    _notify_listeners(job_id)


def add_failed(job_id: str, task_id: str, task: str, badge: str, code: str = "", category: str = "", product: str = ""):
    with JOB_LOCK:
        state = BUILD_STATE.get(job_id)
        if state:
            state["failed"].append({"id": task_id, "task": task, "badge": badge, "code": code, "category": category, "product": product})
    _notify_listeners(job_id)


def add_log(job_id: str, message: str):
    ts = datetime.now(timezone.utc).strftime("%H:%M:%S")
    line = f"{ts} {message}"
    with JOB_LOCK:
        state = BUILD_STATE.get(job_id)
        if state:
            state["logs"].append(line)
            if len(state["logs"]) > _MAX_LOGS:
                state["logs"] = state["logs"][-_MAX_LOGS:]
    print(f"[LOG] {line}")
    _notify_listeners(job_id)


def set_current_task(job_id: str, message: str):
    with JOB_LOCK:
        state = BUILD_STATE.get(job_id)
        if state:
            state["current_task"] = message
    _notify_listeners(job_id)


def set_total(job_id: str, total: int):
    with JOB_LOCK:
        state = BUILD_STATE.get(job_id)
        if state:
            state["total"] = total
    _notify_listeners(job_id)


def set_pr_url(job_id: str, url: str):
    with JOB_LOCK:
        state = BUILD_STATE.get(job_id)
        if state:
            state["pr_url"] = url
    _notify_listeners(job_id)


def set_pr_branch(job_id: str, pr_branch: str):
    with JOB_LOCK:
        state = BUILD_STATE.get(job_id)
        if state:
            state["pr_branch"] = pr_branch
    _notify_listeners(job_id)


def set_results_summary(job_id: str, summary: list):
    with JOB_LOCK:
        state = BUILD_STATE.get(job_id)
        if state:
            state["results_summary"] = list(summary)
    _notify_listeners(job_id)


def set_status(job_id: str, status: str):
    with JOB_LOCK:
        state = BUILD_STATE.get(job_id)
        if state:
            state["status"] = status
            state["current_task"] = "All tasks complete." if status == "completed" else f"Job {status}."
    _notify_listeners(job_id)


def get_build_state(job_id: str) -> Optional[dict]:
    with JOB_LOCK:
        state = BUILD_STATE.get(job_id)
        if not state:
            return None
        elapsed = time.monotonic() - state["start_time"]
        passed_count = len(state["passed"])
        failed_count = len(state["failed"])
        total = state["total"]
        processed = passed_count + failed_count
        pass_rate = round((passed_count / processed * 100) if processed > 0 else 0)
        return {
            "status": state["status"],
            "total": total,
            "processed": processed,
            "passed_count": passed_count,
            "failed_count": failed_count,
            "pass_rate": pass_rate,
            "elapsed": round(elapsed),
            "current_task": state["current_task"],
            "passed": list(state["passed"]),
            "failed": list(state["failed"]),
            "logs": list(state["logs"]),
            "pr_url": state.get("pr_url", ""),
            "pr_branch": state.get("pr_branch", ""),
            "results_summary": list(state.get("results_summary", [])),
        }


def is_cancelled(job_id: str) -> bool:
    with JOB_LOCK:
        return JOB_CANCEL_FLAGS.get(job_id, False)
