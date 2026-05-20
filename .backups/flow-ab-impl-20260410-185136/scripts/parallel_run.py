#!/usr/bin/env python3
"""
parallel_run.py — Parallel orchestrator for Aspose.PDF example generation.

Spawns multiple uvicorn instances on different ports and distributes categories
across them. Supports natural language commands via LLM intent parsing.

Usage:
    python scripts/parallel_run.py "run all categories with 4 workers"
    python scripts/parallel_run.py "retry failed in tables and forms with 2 workers"
    python scripts/parallel_run.py --categories tables,forms --workers 3
    python scripts/parallel_run.py --all --workers 4
    python scripts/parallel_run.py --all-failed --workers 2

Zero code changes to the main app — uses the HTTP API as the coordination layer.
"""

import argparse
import json
import os
import signal
import subprocess
import sys
import textwrap
import threading
import time
from pathlib import Path

import requests
from dotenv import load_dotenv

# ── Load .env first (before reading any env vars) ─────────────────────────────
_project_root = Path(__file__).resolve().parent.parent
load_dotenv(_project_root / ".env")

# ── Constants ──────────────────────────────────────────────────────────────────
BASE_PORT = 7110
HEALTH_TIMEOUT = 60          # seconds to wait for each instance to start
POLL_INTERVAL = 3            # seconds between SSE reconnect attempts
TASKS_API = os.getenv("TASKS_API_URL", "http://172.20.1.175:7061/api/tasks")
CATEGORIES_API = os.getenv("CATEGORIES_API_URL", "http://172.20.1.175:7061/api/categories")
LLM_API_KEY = os.getenv("LITELLM_API_KEY", "")
LLM_API_BASE = os.getenv("LITELLM_API_BASE", "https://llm.professionalize.com/v1")
LLM_MODEL = "gpt-oss"


# ── LLM Intent Parsing ────────────────────────────────────────────────────────

def parse_intent_with_llm(user_input: str, available_categories: list[str]) -> dict:
    """Use LLM to parse natural language command into structured intent.

    Returns: {
        "action": "run" | "retry_failed" | "merge_release",
        "categories": [...] | "all" | "all_failed",
        "workers": int
    }
    """
    cat_list = "\n".join(f"  - {c}" for c in available_categories[:80])

    system_prompt = textwrap.dedent(f"""\
        You are a command parser for a code generation pipeline.
        Parse the user's natural language request into a JSON object.

        Available categories:
        {cat_list}

        Return ONLY valid JSON with these fields:
        - "action": one of:
            * "run"            — generate new examples
            * "retry_failed"   — retry failed tasks
            * "merge_release"  — update & merge open PRs targeting the release branch
        - "categories":
            * a list of category names, OR
            * the string "all" for all categories, OR
            * "all_failed" for all categories that have failures, OR
            * for "merge_release": "all" OR a list of PR numbers as strings
              like ["#192", "#207"]
        - "workers": integer number of parallel workers (default 4 if not specified;
          merge_release always uses 1)

        Rules:
        - Match category names loosely (e.g. "tables" → "Tables in PDF")
        - If user says "everything" or "all", set categories to "all"
        - If user says "retry all failed" or "all failed", set categories to "all_failed"
        - If user says "merge", "merge PRs", "merge release", "merge passing",
          "update and merge", "sync and merge" → action = "merge_release"
        - If user names specific PR numbers (e.g. "merge PR 192 and 207"),
          return them as strings in categories
        - If user doesn't specify workers, default to 4
        - Return ONLY the JSON object, no explanation
    """)

    try:
        resp = requests.post(
            f"{LLM_API_BASE}/chat/completions",
            headers={"Authorization": f"Bearer {LLM_API_KEY}"},
            json={
                "model": LLM_MODEL,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_input},
                ],
                "temperature": 0,
                "max_tokens": 500,
            },
            timeout=30,
        )
        resp.raise_for_status()
        content = resp.json()["choices"][0]["message"]["content"].strip()
        # Strip markdown code fence if present
        if content.startswith("```"):
            content = "\n".join(content.split("\n")[1:])
            if content.endswith("```"):
                content = content[:-3]
            content = content.strip()
        return json.loads(content)
    except Exception as e:
        print(f"⚠ LLM parsing failed: {e}")
        return None


# ── External API Helpers ───────────────────────────────────────────────────────

def fetch_categories() -> list[dict]:
    """Fetch available categories + task counts from external API."""
    try:
        resp = requests.get(CATEGORIES_API, params={"product": "aspose.pdf"}, timeout=10)
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        print(f"⚠ Failed to fetch categories: {e}")
        return []

    # Normalize names
    names = []
    for item in data:
        if isinstance(item, dict):
            names.append(item.get("name", str(item)))
        else:
            names.append(str(item))

    # Fetch task counts in parallel for better bin-packing
    from concurrent.futures import ThreadPoolExecutor

    def _get_count(name: str) -> int:
        try:
            r = requests.get(
                TASKS_API,
                params={"product": "aspose.pdf", "category": name, "page": 1, "page_size": 1},
                timeout=10,
            )
            return r.json().get("total", 0) if r.status_code == 200 else 0
        except Exception:
            return 0

    print(f"  Fetching task counts for {len(names)} categories...")
    with ThreadPoolExecutor(max_workers=5) as pool:
        counts = list(pool.map(_get_count, names))

    return [{"name": n, "task_count": c} for n, c in zip(names, counts)]


def fetch_tasks_for_category(category: str) -> list[dict]:
    """Fetch all tasks for a category from the external API."""
    all_tasks = []
    page = 1
    page_size = 100
    while True:
        try:
            resp = requests.get(
                TASKS_API,
                params={
                    "product": "aspose.pdf",
                    "category": category,
                    "page": page,
                    "page_size": page_size,
                },
                timeout=15,
            )
            resp.raise_for_status()
            data = resp.json()
            items = data.get("items", [])
            all_tasks.extend(items)
            if page >= data.get("total_pages", 1):
                break
            page += 1
        except Exception as e:
            print(f"  ⚠ Failed to fetch tasks for {category} (page {page}): {e}")
            break
    return all_tasks


def fetch_disk_results() -> list[dict]:
    """Scan disk results to find categories with failures.

    Returns list of dicts: [{name, slug, failed_count}, ...]
    Reads directly from results JSON files for accurate category names.
    """
    import json as _json
    results_dir = _project_root / "results"
    # Find the latest version directory
    versions = sorted(results_dir.iterdir()) if results_dir.exists() else []
    if not versions:
        return []
    latest = versions[-1]

    results = []
    for json_file in sorted(latest.glob("*.json")):
        try:
            data = _json.loads(json_file.read_text(encoding="utf-8"))
            slug = json_file.stem
            name = data.get("category", slug)
            tasks = data.get("tasks", {})
            failed_count = sum(1 for t in tasks.values() if t.get("status") == "FAILED")
            if failed_count > 0:
                results.append({"name": name, "slug": slug, "task_count": failed_count})
        except Exception:
            continue
    return results


def fetch_failed_tasks(category_slug: str, port: int = 7103) -> list[dict]:
    """Fetch failed tasks for a category from the main instance."""
    try:
        resp = requests.get(
            f"http://localhost:{port}/api/failed-tasks/{category_slug}",
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()
        return data.get("failed", [])
    except Exception:
        return []


# ── Worker Management ──────────────────────────────────────────────────────────

class Worker:
    """Represents a uvicorn instance running on a specific port."""

    def __init__(self, worker_id: int, port: int, project_root: Path):
        self.worker_id = worker_id
        self.port = port
        self.project_root = project_root
        self.process: subprocess.Popen | None = None
        self.job_id: str | None = None
        self.categories: list[str] = []
        self.status = "idle"
        self.progress = {}

    def start(self) -> bool:
        """Start uvicorn instance and wait for health check."""
        env = os.environ.copy()
        env["UI_PORT"] = str(self.port)

        self.process = subprocess.Popen(
            [
                sys.executable, "-m", "uvicorn", "main:app",
                "--host", "0.0.0.0",
                "--port", str(self.port),
                "--workers", "1",
            ],
            cwd=str(self.project_root),
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

        # Wait for health check
        start_time = time.time()
        while time.time() - start_time < HEALTH_TIMEOUT:
            try:
                resp = requests.get(f"http://localhost:{self.port}/api/health", timeout=2)
                if resp.status_code == 200:
                    return True
            except Exception:
                pass
            time.sleep(1)

        print(f"  ✗ Worker {self.worker_id} (port {self.port}) failed to start")
        self.stop()
        return False

    def stop(self):
        """Stop the uvicorn instance."""
        if self.process:
            self.process.terminate()
            try:
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.process.kill()
            self.process = None

    def submit_job(self, categories: list[str]) -> str | None:
        """Submit a category sweep job to this worker."""
        self.categories = categories
        try:
            resp = requests.post(
                f"http://localhost:{self.port}/api/start-tasks",
                json={
                    "categories": categories,
                    "repo_push": False,
                    "pr_style": "per-category",
                },
                timeout=30,
            )
            resp.raise_for_status()
            data = resp.json()
            self.job_id = data.get("job_id")
            self.status = "running"
            return self.job_id
        except Exception as e:
            print(f"  ✗ Worker {self.worker_id}: job submit failed: {e}")
            self.status = "error"
            return None

    def submit_retry_job(self, tasks: list[dict]) -> str | None:
        """Submit a retry job with specific failed tasks."""
        try:
            resp = requests.post(
                f"http://localhost:{self.port}/api/start-tasks",
                json={
                    "tasks": tasks,
                    "repo_push": False,
                    "pr_style": "per-category",
                },
                timeout=30,
            )
            resp.raise_for_status()
            data = resp.json()
            self.job_id = data.get("job_id")
            self.status = "running"
            return self.job_id
        except Exception as e:
            print(f"  ✗ Worker {self.worker_id}: retry submit failed: {e}")
            self.status = "error"
            return None

    def poll_status(self) -> dict:
        """Poll job status (fallback when SSE isn't practical)."""
        if not self.job_id:
            return {}
        try:
            resp = requests.get(
                f"http://localhost:{self.port}/api/status/{self.job_id}",
                timeout=5,
            )
            if resp.status_code == 200:
                self.progress = resp.json()
                if self.progress.get("status") in ("completed", "failed", "cancelled"):
                    self.status = "done"
                return self.progress
        except Exception:
            pass
        return self.progress


# ── Category Balancing ─────────────────────────────────────────────────────────

def balance_categories(categories: list[dict], num_workers: int) -> list[list[str]]:
    """Greedy bin-packing: distribute categories across workers by task count.

    Sort by task_count desc, assign each to the lightest bucket.
    """
    sorted_cats = sorted(categories, key=lambda c: c.get("task_count", 0), reverse=True)
    buckets: list[list[str]] = [[] for _ in range(num_workers)]
    bucket_weights = [0] * num_workers

    for cat in sorted_cats:
        lightest = min(range(num_workers), key=lambda i: bucket_weights[i])
        buckets[lightest].append(cat["name"])
        bucket_weights[lightest] += cat.get("task_count", 1)

    return buckets


def split_tasks_across_workers(categories: list[dict], num_workers: int) -> list[list[dict]]:
    """Fetch all tasks for given categories, then round-robin split across workers.

    Used when num_workers > num_categories to split individual tasks.
    Returns a list of task lists (one per worker).
    """
    all_tasks = []
    for cat in categories:
        print(f"  Fetching tasks for {cat['name']}...")
        tasks = fetch_tasks_for_category(cat["name"])
        all_tasks.extend(tasks)

    if not all_tasks:
        return []

    print(f"  Total tasks fetched: {len(all_tasks)}")

    # Round-robin distribute for even split
    buckets: list[list[dict]] = [[] for _ in range(num_workers)]
    for i, task in enumerate(all_tasks):
        buckets[i % num_workers].append(task)

    return buckets


def slugify(name: str) -> str:
    """Convert category name to disk slug."""
    return name.lower().replace(" ", "_").replace("-", "_")


# ── Terminal Dashboard ─────────────────────────────────────────────────────────

def clear_screen():
    """Move cursor to top-left and clear screen. Works on macOS/Linux terminals."""
    sys.stdout.write("\033[2J\033[H")
    sys.stdout.flush()


def render_dashboard(workers: list[Worker], start_time: float):
    """Render a compact terminal dashboard showing worker progress."""
    # Build full output as a single string, then write + flush once to avoid flicker
    out = []
    elapsed = time.time() - start_time
    mins, secs = divmod(int(elapsed), 60)

    out.append(f"{'═' * 72}")
    out.append(f"  Parallel Run — {len(workers)} workers — elapsed {mins}m {secs}s")
    out.append(f"{'═' * 72}")

    total_passed = 0
    total_failed = 0
    total_tasks = 0
    total_processed = 0

    for w in workers:
        p = w.progress
        status = p.get("status", w.status)
        processed = p.get("processed", 0)
        total = p.get("total", 0)
        passed = p.get("passed_count", 0)
        failed = p.get("failed_count", 0)
        pass_rate = p.get("pass_rate", 0)
        current = (p.get("current_task") or "")[:40]
        cats = ", ".join(w.categories[:3])
        if len(w.categories) > 3:
            cats += f" +{len(w.categories) - 3}"

        total_passed += passed
        total_failed += failed
        total_tasks += total
        total_processed += processed

        # Status indicator
        if status in ("completed", "done"):
            icon = "✓"
        elif status == "running":
            icon = "▶"
        elif status == "error":
            icon = "✗"
        else:
            icon = "○"

        bar_len = 20
        if total > 0:
            filled = int(bar_len * processed / total)
            bar = "█" * filled + "░" * (bar_len - filled)
            pct = f"{processed}/{total}"
        else:
            bar = "░" * bar_len
            pct = "0/0"

        out.append(f"")
        out.append(f"  {icon} Worker {w.worker_id} (:{w.port})  [{bar}] {pct}")
        out.append(f"    ✓ {passed}  ✗ {failed}  rate: {pass_rate}%  |  {cats}")
        if current and status == "running":
            out.append(f"    → {current}")

    # Summary
    overall_rate = round(total_passed / total_processed * 100, 1) if total_processed > 0 else 0
    out.append(f"")
    out.append(f"{'─' * 72}")
    out.append(f"  Total: {total_processed}/{total_tasks}  |  ✓ {total_passed}  ✗ {total_failed}  |  {overall_rate}%")
    out.append(f"{'─' * 72}")

    active = sum(1 for w in workers if w.status == "running")
    if active > 0:
        out.append(f"")
        out.append(f"  {active} worker(s) still running. Press Ctrl+C to cancel.")
    else:
        out.append(f"")
        out.append(f"  All workers finished.")

    # Write entire frame at once — cursor home + content + clear-to-end
    frame = "\033[H" + "\n".join(out) + "\033[J"
    sys.stdout.write(frame)
    sys.stdout.flush()


# ── Monitoring Thread ──────────────────────────────────────────────────────────

def monitor_workers(workers: list[Worker], start_time: float, stop_event: threading.Event):
    """Poll worker status and update the dashboard."""
    while not stop_event.is_set():
        all_done = True
        for w in workers:
            if w.status == "running":
                w.poll_status()
                if w.status != "done":
                    all_done = False

        render_dashboard(workers, start_time)

        if all_done:
            break

        stop_event.wait(POLL_INTERVAL)


# ── Main ───────────────────────────────────────────────────────────────────────

def resolve_intent(intent: dict, all_categories: list[dict]) -> tuple[str, list[dict], int]:
    """Resolve LLM intent into (action, category_list, num_workers).

    Returns category dicts with 'name' and 'task_count'.
    """
    action = intent.get("action", "run")
    categories_spec = intent.get("categories", "all")
    num_workers = int(intent.get("workers", 4))

    if categories_spec == "all":
        return action, all_categories, num_workers

    if categories_spec == "all_failed":
        # Scan disk results for categories with failures
        failed_cats = fetch_disk_results()
        return action, failed_cats, num_workers

    # Specific categories
    if isinstance(categories_spec, list):
        matched = []
        cat_names_lower = {c["name"].lower(): c for c in all_categories}
        for spec in categories_spec:
            spec_lower = spec.lower()
            # Exact match first
            if spec_lower in cat_names_lower:
                matched.append(cat_names_lower[spec_lower])
                continue
            # Partial match
            found = False
            for name_lower, cat in cat_names_lower.items():
                if spec_lower in name_lower or name_lower in spec_lower:
                    matched.append(cat)
                    found = True
                    break
            if not found:
                print(f"  ⚠ Category not found: '{spec}'")
        return action, matched, num_workers

    return action, all_categories, num_workers


def print_plan(action: str, buckets: list[list[str]], categories: list[dict], base_port: int = BASE_PORT):
    """Print the execution plan for user confirmation."""
    total_tasks = sum(c.get("task_count", 0) for c in categories)
    print(f"\n{'═' * 60}")
    print(f"  Execution Plan")
    print(f"{'═' * 60}")
    print(f"  Action:     {action}")
    print(f"  Categories: {len(categories)}")
    print(f"  Tasks:      ~{total_tasks}")
    print(f"  Workers:    {len(buckets)}")
    print()

    for i, bucket in enumerate(buckets):
        task_sum = sum(
            next((c.get("task_count", 0) for c in categories if c["name"] == name), 0)
            for name in bucket
        )
        print(f"  Worker {i + 1} (port {base_port + i}): {len(bucket)} categories, ~{task_sum} tasks")
        for name in bucket[:5]:
            print(f"    • {name}")
        if len(bucket) > 5:
            print(f"    ... +{len(bucket) - 5} more")
    print(f"\n{'═' * 60}")


def _run_merge_release(intent: dict, args) -> None:
    """Dispatch the Flow A merge-release flow.

    Loads config, instantiates bot + merge-acct GitHubAPI clients,
    fetches mergeable PRs, optionally filters by explicit PR numbers,
    prints the plan, confirms, and runs the batch. Exits the process
    with an appropriate status code.
    """
    # Make project root importable so the local packages resolve
    sys.path.insert(0, str(_project_root))
    from config import load_config
    from git_ops.github_api import GitHubAPI
    from scripts.merge_release_prs import (
        fetch_mergeable_prs,
        filter_by_numbers,
        print_merge_plan,
        run_merge_batch,
    )

    cfg = load_config()
    if not cfg.git.repo_token:
        print("✗ REPO_TOKEN not configured — cannot call GitHub API.")
        sys.exit(1)

    gh_bot = GitHubAPI(cfg.git.repo_token)
    gh_personal = GitHubAPI(cfg.git.personal_token or cfg.git.repo_token)
    owner, repo = GitHubAPI.extract_repo_info(cfg.git.repo_url)
    if not owner or not repo:
        print(f"✗ Could not parse repo URL: {cfg.git.repo_url}")
        sys.exit(1)

    base_branch = cfg.git.effective_pr_target
    bot_login = cfg.git.bot_login or None

    if not cfg.git.personal_token:
        print("⚠ MERGE_ACCT_GITHUB_TOKEN not set — merges will be attributed to the bot.")

    print(f"\n  Fetching open PRs targeting {base_branch} (author: {bot_login or 'any'})...")
    prs = fetch_mergeable_prs(gh_bot, owner, repo, base_branch, bot_login)

    # Honor explicit PR numbers from intent or --pr flag
    wanted = intent.get("categories")
    if isinstance(wanted, list) and wanted:
        before = len(prs)
        prs = filter_by_numbers(prs, wanted)
        print(f"  Filtered to {len(prs)}/{before} matching requested PR numbers: {wanted}")

    print_merge_plan(prs, base_branch)

    if not prs:
        sys.exit(0)

    if getattr(args, "dry_run", False):
        print("  --dry-run: exiting without merging.")
        sys.exit(0)

    if not args.yes:
        answer = input("  Merge these PRs? [Y/n] ").strip().lower()
        if answer and answer != "y":
            print("  Cancelled.")
            sys.exit(0)

    summary = run_merge_batch(prs, gh_bot, gh_personal, owner, repo)
    print(
        f"\n  ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"  Merged:  {summary['merged']}\n"
        f"  Skipped: {summary['skipped']}\n"
        f"  Failed:  {summary['failed']}\n"
        f"  ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    )
    sys.exit(0 if summary["failed"] == 0 else 1)


def main():
    parser = argparse.ArgumentParser(
        description="Parallel orchestrator for Aspose.PDF example generation",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=textwrap.dedent("""\
            Examples:
              %(prog)s "run all categories with 4 workers"
              %(prog)s "retry failed in tables and forms"
              %(prog)s --categories "Tables in PDF,Forms" --workers 3
              %(prog)s --all --workers 4
              %(prog)s --all-failed --workers 2
        """),
    )
    parser.add_argument("command", nargs="?", help="Natural language command (parsed by LLM)")
    parser.add_argument("--categories", help="Comma-separated category names")
    parser.add_argument("--all", action="store_true", help="Run all available categories")
    parser.add_argument("--all-failed", action="store_true", help="Retry all categories with failures")
    parser.add_argument("--workers", "-w", type=int, default=4, help="Number of parallel workers (default: 4)")
    parser.add_argument("--base-port", type=int, default=BASE_PORT, help=f"Starting port (default: {BASE_PORT})")
    parser.add_argument("--yes", "-y", action="store_true", help="Skip confirmation prompt")
    parser.add_argument("--retry", action="store_true", help="Retry failed tasks instead of running new")
    parser.add_argument("--merge-release", action="store_true",
        help="Merge all green bot-authored PRs targeting the release branch")
    parser.add_argument("--pr", action="append", default=[],
        help="Specific PR number(s) to merge (repeatable); implies --merge-release")
    parser.add_argument("--dry-run", action="store_true",
        help="For --merge-release: print the merge plan and exit without merging")
    args = parser.parse_args()

    base_port = args.base_port

    # ── Step 0: Validate environment ──
    if not LLM_API_KEY and args.command:
        print("⚠ LITELLM_API_KEY not set — natural language mode requires it.")
        print("  Set it in .env or use --categories/--all/--all-failed instead.")
        sys.exit(1)

    # ── Shortcut: Explicit --merge-release / --pr flags ──
    # Handled before fetching categories since merge flow is independent.
    if args.merge_release or args.pr:
        intent = {
            "action": "merge_release",
            "categories": args.pr if args.pr else "all",
            "workers": 1,
        }
        _run_merge_release(intent, args)
        return  # _run_merge_release exits

    # ── Step 1: Fetch available categories ──
    print("Fetching available categories...")
    all_categories = fetch_categories()
    if not all_categories:
        print("✗ No categories available. Check the external API.")
        sys.exit(1)
    cat_names = [c["name"] for c in all_categories]
    print(f"  Found {len(all_categories)} categories\n")

    # ── Step 2: Determine intent ──
    intent = None

    if args.command:
        # Natural language mode
        print(f"Parsing command: \"{args.command}\"")
        intent = parse_intent_with_llm(args.command, cat_names)
        if intent:
            print(f"  Parsed: {json.dumps(intent, indent=2)}")
        else:
            print("  ⚠ Could not parse command. Use --categories or --all instead.")
            sys.exit(1)
    elif args.all:
        intent = {"action": "run", "categories": "all", "workers": args.workers}
    elif args.all_failed:
        intent = {"action": "retry_failed", "categories": "all_failed", "workers": args.workers}
    elif args.categories:
        cat_list = [c.strip() for c in args.categories.split(",") if c.strip()]
        action = "retry_failed" if args.retry else "run"
        intent = {"action": action, "categories": cat_list, "workers": args.workers}
    else:
        parser.print_help()
        sys.exit(0)

    # ── Step 2b: Dispatch merge_release early if parsed from NL ──
    if intent.get("action") == "merge_release":
        _run_merge_release(intent, args)
        return  # _run_merge_release exits

    # ── Step 3: Resolve intent to actual categories ──
    action, resolved_cats, num_workers = resolve_intent(intent, all_categories)

    if not resolved_cats:
        print("✗ No matching categories found.")
        sys.exit(1)

    # ── Step 4: Decide distribution mode ──
    # If workers > categories, split tasks across workers (task-level splitting)
    # Otherwise, distribute categories across workers (category-level splitting)
    task_split_mode = num_workers > len(resolved_cats)
    task_buckets: list[list[dict]] | None = None  # only used in task-split mode
    cat_buckets: list[list[str]] | None = None     # only used in category mode

    if task_split_mode:
        print(f"\n  {num_workers} workers > {len(resolved_cats)} categories → splitting tasks across workers")
        task_buckets = split_tasks_across_workers(resolved_cats, num_workers)
        # Remove empty buckets
        task_buckets = [b for b in task_buckets if b]
        num_workers = len(task_buckets)
        if not task_buckets:
            print("✗ No tasks found to split.")
            sys.exit(1)
    else:
        cat_buckets = balance_categories(resolved_cats, num_workers)
        # Remove empty buckets
        cat_buckets = [b for b in cat_buckets if b]
        num_workers = len(cat_buckets)

    # ── Step 5: Print plan & confirm ──
    if task_split_mode:
        total_tasks = sum(len(b) for b in task_buckets)
        cat_names_str = ", ".join(c["name"] for c in resolved_cats)
        print(f"\n{'═' * 60}")
        print(f"  Execution Plan (task-split mode)")
        print(f"{'═' * 60}")
        print(f"  Action:     {action}")
        print(f"  Categories: {cat_names_str}")
        print(f"  Tasks:      {total_tasks}")
        print(f"  Workers:    {num_workers}")
        print()
        for i, bucket in enumerate(task_buckets):
            cats_in_bucket = sorted(set(t.get("category", "?") for t in bucket))
            print(f"  Worker {i + 1} (port {base_port + i}): {len(bucket)} tasks")
            for cn in cats_in_bucket[:3]:
                count = sum(1 for t in bucket if t.get("category") == cn)
                print(f"    • {cn} ({count} tasks)")
        print(f"\n{'═' * 60}")
    else:
        print_plan(action, cat_buckets, resolved_cats, base_port=base_port)

    if not args.yes:
        answer = input("\n  Proceed? [Y/n] ").strip().lower()
        if answer and answer != "y":
            print("  Cancelled.")
            sys.exit(0)

    # ── Step 6: Spawn workers ──
    print(f"\nStarting {num_workers} workers...")
    workers: list[Worker] = []

    effective_buckets = task_buckets if task_split_mode else cat_buckets
    for i in range(num_workers):
        port = base_port + i
        print(f"  Starting worker {i + 1} on port {port}...")
        w = Worker(i + 1, port, _project_root)
        if w.start():
            print(f"  ✓ Worker {i + 1} ready")
            workers.append(w)
        else:
            print(f"  ✗ Worker {i + 1} failed to start — redistributing tasks")
            # Redistribute this worker's items to remaining workers
            if workers and effective_buckets and i < len(effective_buckets):
                items = effective_buckets[i]
                for j, item in enumerate(items):
                    target_idx = j % len(workers)
                    if task_split_mode and target_idx < len(task_buckets):
                        task_buckets[target_idx].append(item)
                    elif cat_buckets and target_idx < len(cat_buckets):
                        cat_buckets[target_idx].append(item)

    if not workers:
        print("✗ No workers started. Exiting.")
        sys.exit(1)

    # ── Step 7: Submit jobs ──
    print(f"\nSubmitting {action} jobs...")
    for i, w in enumerate(workers):
        if task_split_mode:
            # Task-split mode — submit individual tasks
            tasks_for_worker = task_buckets[i] if i < len(task_buckets) else []
            if not tasks_for_worker:
                w.status = "done"
                continue

            cat_names_in = sorted(set(t.get("category", "?") for t in tasks_for_worker))
            w.categories = cat_names_in
            job_id = w.submit_retry_job(tasks_for_worker)  # submit_retry_job sends {"tasks": [...]}
            if job_id:
                print(f"  ✓ Worker {w.worker_id}: job {job_id[:8]}... ({len(tasks_for_worker)} tasks)")

        elif action == "retry_failed":
            # Category mode retry — collect failed tasks per category
            target_cats = cat_buckets[i] if i < len(cat_buckets) else []
            if not target_cats:
                continue
            all_failed_tasks = []
            for cat_name in target_cats:
                slug = slugify(cat_name)
                tasks = fetch_failed_tasks(slug)
                if tasks:
                    all_failed_tasks.extend(tasks)
                    print(f"  Worker {w.worker_id}: {len(tasks)} failed tasks for {cat_name}")
                else:
                    print(f"  Worker {w.worker_id}: no failed tasks for {cat_name}")
            if all_failed_tasks:
                w.categories = target_cats
                job_id = w.submit_retry_job(all_failed_tasks)
                if job_id:
                    print(f"  ✓ Worker {w.worker_id}: job {job_id[:8]}... ({len(all_failed_tasks)} tasks)")
            else:
                w.status = "done"
        else:
            # Category mode run — submit categories for sweep
            target_cats = cat_buckets[i] if i < len(cat_buckets) else []
            if not target_cats:
                continue
            w.categories = target_cats
            job_id = w.submit_job(target_cats)
            if job_id:
                total = sum(
                    next((c.get("task_count", 0) for c in resolved_cats if c["name"] == name), 0)
                    for name in target_cats
                )
                print(f"  ✓ Worker {w.worker_id}: job {job_id[:8]}... ({len(target_cats)} categories, ~{total} tasks)")

    # ── Step 8: Monitor progress ──
    stop_event = threading.Event()
    start_time = time.time()

    # Handle Ctrl+C gracefully
    def signal_handler(sig, frame):
        print("\n\n  ⚠ Cancelling all jobs...")
        stop_event.set()
        for w in workers:
            if w.job_id and w.status == "running":
                try:
                    requests.post(f"http://localhost:{w.port}/api/cancel/{w.job_id}", timeout=5)
                except Exception:
                    pass
            w.stop()
        sys.exit(0)

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    # Start monitoring
    monitor_thread = threading.Thread(
        target=monitor_workers,
        args=(workers, start_time, stop_event),
        daemon=True,
    )
    monitor_thread.start()
    monitor_thread.join()

    # ── Step 9: Final summary ──
    elapsed = time.time() - start_time
    mins, secs = divmod(int(elapsed), 60)

    total_passed = sum(w.progress.get("passed_count", 0) for w in workers)
    total_failed = sum(w.progress.get("failed_count", 0) for w in workers)
    total_processed = total_passed + total_failed

    print(f"\n{'═' * 60}")
    print(f"  COMPLETE — {mins}m {secs}s")
    print(f"  Processed: {total_processed}  |  ✓ {total_passed}  ✗ {total_failed}")
    if total_processed > 0:
        print(f"  Pass rate: {round(total_passed / total_processed * 100, 1)}%")
    print(f"{'═' * 60}")

    # Per-worker breakdown
    for w in workers:
        p = w.progress
        cats = ", ".join(w.categories[:3])
        if len(w.categories) > 3:
            cats += f" +{len(w.categories) - 3}"
        print(f"  Worker {w.worker_id}: ✓ {p.get('passed_count', 0)}  ✗ {p.get('failed_count', 0)}  |  {cats}")

    # ── Step 10: Clean up ──
    print("\nShutting down workers...")
    for w in workers:
        w.stop()
    print("Done.")


if __name__ == "__main__":
    main()
