"""
jobs.py — Background worker (run_job, retry_pr, run_sweep, run_version_bump).

Runs in a daemon thread — NOT in the async event loop.
This keeps heavy CPU/IO work (dotnet build, ML models) off Uvicorn's event loop.

Fully in-memory — no database. Results tracked via state.BUILD_STATE.
"""

import subprocess
import time
import uuid
from pathlib import Path

import requests

from config import load_config
from pipeline.models import TaskInput
from pipeline.runner import PipelineRunner
from pipeline.usage_tracker import UsageTracker
from reporting import report_job_usage
from git_ops.repo import RepoManager
from git_ops.committer import CodeCommitter
from git_ops.pr import PRManager
from pipeline.llm_client import LLMClient
from state import (
    add_failed, add_log, add_passed, get_build_state, is_cancelled,
    init_build, set_current_task, set_pr_url, set_pr_branch,
    set_results_summary, set_status, set_total,
    set_category_branch, set_failed_tasks, set_repo_push,
    wait_if_paused, is_paused,
    JOB_CANCEL_FLAGS, JOB_LOCK,
)
from persistence import save_result, is_task_passed, load_cached_task, get_resume_stats


def _compute_badge(result) -> str:
    """Compute a display badge from the pipeline result."""
    if result.status == "FAILED":
        return "FAILED"

    stage_labels = {
        "baseline": "MCP",
        "pattern_fix": "MCP + Pattern Fix",
        "llm_fix": "MCP + LLM Fix",
        "regen": "MCP + Rules",
        "final_llm": "MCP + Final LLM",
    }
    label = stage_labels.get(result.stage, "MCP")
    return f"{label} - {result.stage}"


def _make_progress_callback(job_id: str):
    def callback(stage: str, message: str):
        add_log(job_id, message)
    return callback


def _setup_pr_workflow(config, job_id: str, notify):
    """Setup repo + PR branch. Returns (repo, committer, pr_manager) or None."""
    repo = RepoManager(
        repo_path=config.git.repo_path,
        repo_url=config.git.repo_url,
        repo_branch=config.git.repo_branch,
        repo_token=config.git.repo_token,
        repo_user=config.git.repo_user,
        notify=notify,
    )
    if not repo.ensure_ready():
        add_log(job_id, "Git repository not ready - PR will be skipped")
        return None, None, None

    branch_name = f"examples/batch-{job_id[:8]}"
    if not repo.setup_pr_branch(branch_name):
        add_log(job_id, "Could not create PR branch - pushing to default branch")
        return None, None, None

    add_log(job_id, f"PR branch created: {branch_name}")

    llm = LLMClient(config)
    committer = CodeCommitter(
        repo_path=config.git.repo_path,
        repo_push=True,
        pr_branch=repo.pr_branch,
        repo_branch=config.git.repo_branch,
        default_category=config.git.default_category,
        batch_git=True,
        notify=notify,
        llm_client=llm,
    )
    pr_manager = PRManager(config, repo, notify=notify, llm_client=llm)
    return repo, committer, pr_manager


def _run_rule_learning(job_id, config, failed_results, builder, notify):
    """Post-pipeline rule learning: analyze failed tasks with Anthropic Claude.

    For each failed task:
    1. Send original code + build error to Claude
    2. If Claude returns a fix, build+run it to verify
    3. If verified, save the extracted rule to auto_fixes.json
    """
    if not config.pipeline.learn_rules_from_failures:
        return

    import re
    from pipeline.anthropic_client import AnthropicClient
    from knowledge.auto_fixes import save_auto_fix, is_duplicate_rule
    from knowledge.error_fixes import load_error_fixes, match_error_fixes, format_error_fixes_for_prompt

    anthropic_client = AnthropicClient(config)
    # Load curated error fixes to provide as context to Claude
    all_fixes = load_error_fixes(config.error_fixes_path)
    if not anthropic_client.available:
        add_log(job_id, "Rule learning skipped: ANTHROPIC_API_KEY not configured")
        return

    learnable = [f for f in failed_results if f.get("code") and f.get("build_log")]
    if not learnable:
        add_log(job_id, "Rule learning: no failed tasks with code+errors to analyze")
        return

    add_log(job_id, f"Rule learning: analyzing {len(learnable)} failed task(s) with Claude...")
    set_current_task(job_id, "Learning rules from failures...")

    rules_learned = 0

    for idx, failure in enumerate(learnable, 1):
        if is_cancelled(job_id):
            break

        task_text = failure["task"]
        code = failure["code"]
        build_log = failure["build_log"]

        add_log(job_id, f"  Rule learning [{idx}/{len(learnable)}]: {task_text[:80]}...")

        # Find relevant existing fixes to give Claude proven patterns
        error_codes = re.findall(r"CS\d{4}", build_log)
        matched_fixes = match_error_fixes(all_fixes, build_log, error_codes)
        fixes_context = format_error_fixes_for_prompt(matched_fixes) if matched_fixes else ""

        result = anthropic_client.fix_and_extract_rule(task_text, code, build_log, fixes_context)
        if not result:
            add_log(job_id, f"  Claude could not fix task #{idx}")
            continue

        fixed_code = result["fixed_code"]
        rule_id = result["rule_id"]
        rule = result["rule"]

        if is_duplicate_rule(config.auto_fixes_path, rule_id, rule.get("errors", [])):
            add_log(job_id, f"  Rule '{rule_id}' is a duplicate — skipped")
            continue

        builder.write_program_cs(fixed_code)
        success, output = builder.build_and_run()

        if success:
            saved = save_auto_fix(config.auto_fixes_path, rule_id, rule)
            if saved:
                rules_learned += 1
                add_log(job_id, f"  Learned rule: '{rule_id}' (verified via build+run)")
            else:
                add_log(job_id, f"  Rule '{rule_id}' verified but save failed")
        else:
            # Determine error type and log useful context
            is_runtime = "--- RUNTIME OUTPUT ---" in output and "error CS" not in output.split("--- RUNTIME OUTPUT ---")[0]
            error_type = "runtime crash" if is_runtime else "compile error"
            error_lines = output.strip().split("\n") if output else ["(no output)"]
            error_preview = error_lines[-8:]
            add_log(job_id, f"  Claude's fix for task #{idx} failed ({error_type}) — rule discarded")
            for line in error_preview:
                stripped = line.strip()
                if stripped:
                    add_log(job_id, f"    | {stripped}")

    add_log(job_id, f"Rule learning complete: {rules_learned} new rule(s) saved to auto_fixes.json")


def _generate_agents_md_for_pending(job_id, config, committer):
    """Generate per-category agents.md files for all pending commits.

    Writes agents.md into each category folder on disk so that
    batch_commit_and_push() can stage them as sidecars.
    """
    from pathlib import Path as _Path
    from git_ops.committer import normalize_category
    from git_ops.repo_docs import generate_cumulative_category_agents_md
    from git_ops.agents_md import _generate_run_id

    groups = committer.get_pending_by_category()
    if not groups:
        return

    run_id = _generate_run_id()
    count = 0

    for cat_name, commits in groups.items():
        try:
            cat_slug = normalize_category(cat_name, config.git.default_category)
            cat_dir = _Path(config.git.repo_path) / cat_slug

            # Scan actual .cs files on disk for most accurate file list
            if cat_dir.exists():
                cs_files = sorted(f.name for f in cat_dir.iterdir() if f.is_file() and f.suffix == ".cs")
            else:
                cs_files = sorted(c["path"].name for c in commits)

            agents_content = generate_cumulative_category_agents_md(
                cat_name, cs_files, run_id,
                kb_path=config.rules_examples_path,
                repo_path=config.git.repo_path,
                tfm=config.build.tfm,
                nuget_version=config.build.nuget_version,
            )
            agents_path = cat_dir / "agents.md"
            agents_path.parent.mkdir(parents=True, exist_ok=True)
            agents_path.write_text(agents_content, encoding="utf-8")
            count += 1
        except Exception as e:
            add_log(job_id, f"[{cat_name}] agents.md generation failed: {str(e)[:80]}")

    if count:
        add_log(job_id, f"Generated agents.md for {count} category(ies)")


def _split_commit_and_pr(job_id, config, repo, committer, pr_manager, results_summary, notify):
    """Commit and create one PR per category.

    Each category gets its own branch, commit, and PR.
    Includes agents.md and index.json alongside the .cs files.
    """
    import subprocess
    import json as _json
    from pathlib import Path as _Path
    from git_ops.repo import _git_lock
    from git_ops.committer import normalize_category
    from git_ops.repo_docs import generate_cumulative_category_agents_md
    from git_ops.agents_md import _generate_run_id

    groups = committer.get_pending_by_category()
    base_branch = config.git.effective_pr_target
    pr_urls = []
    run_id = _generate_run_id()

    for cat_name, commits in sorted(groups.items()):
        if is_cancelled(job_id):
            break

        branch_suffix = cat_name.lower().replace(" ", "-")[:30]
        cat_branch = f"examples/{job_id[:8]}-{branch_suffix}"
        add_log(job_id, f"[{cat_name}] Creating branch {cat_branch} ({len(commits)} file(s))...")
        set_current_task(job_id, f"PR: {cat_name}...")

        try:
            cat_slug = normalize_category(cat_name, config.git.default_category)
            cat_dir = _Path(config.git.repo_path) / cat_slug

            # Scan actual .cs files on disk — more reliable than commit path list
            # (filenames may differ if LLM provided a short name vs task-slug fallback)
            cs_files = sorted(f.name for f in cat_dir.iterdir() if f.is_file() and f.suffix == ".cs") if cat_dir.exists() else sorted(c["path"].name for c in commits)
            agents_content = generate_cumulative_category_agents_md(
                cat_name, cs_files, run_id,
                kb_path=config.rules_examples_path,
                repo_path=config.git.repo_path,
                tfm=config.build.tfm,
                nuget_version=config.build.nuget_version,
            )
            agents_path = cat_dir / "agents.md"
            agents_path.parent.mkdir(parents=True, exist_ok=True)
            agents_path.write_text(agents_content, encoding="utf-8")

            with _git_lock:
                # Create a fresh branch from base for this category
                subprocess.run(
                    ["git", "checkout", f"origin/{base_branch}"],
                    cwd=config.git.repo_path, check=True, capture_output=True, text=True,
                )
                subprocess.run(
                    ["git", "checkout", "-b", cat_branch],
                    cwd=config.git.repo_path, check=True, capture_output=True, text=True,
                )

                # Stage .cs files
                for c in commits:
                    subprocess.run(
                        ["git", "add", str(c["path"])],
                        cwd=config.git.repo_path, check=True, capture_output=True, text=True,
                    )

                # Stage index.json if it exists (written by commit_code → _write_category_index)
                index_path = cat_dir / "index.json"
                if index_path.exists():
                    subprocess.run(
                        ["git", "add", str(index_path)],
                        cwd=config.git.repo_path, check=True, capture_output=True, text=True,
                    )

                # Stage agents.md
                subprocess.run(
                    ["git", "add", str(agents_path)],
                    cwd=config.git.repo_path, check=True, capture_output=True, text=True,
                )

                subprocess.run(
                    ["git", "commit", "-m", f"Add {len(commits)} example(s) for {cat_name}"],
                    cwd=config.git.repo_path, check=True, capture_output=True, text=True,
                )
                subprocess.run(
                    ["git", "push", "-u", "origin", cat_branch],
                    cwd=config.git.repo_path, check=True, capture_output=True, text=True,
                    timeout=60,
                )

            # Record branch so retry-failed can push to it
            set_category_branch(job_id, cat_name, cat_branch)

            # Create PR for this category — build results_summary from commits for LLM description
            cat_results_summary = [
                {"task": c["prompt"], "category": cat_name, "status": "PASSED"}
                for c in commits
            ]
            repo.pr_branch = cat_branch
            pr_url = pr_manager.create_category_pr(cat_name, len(commits),
                                                    results_summary=cat_results_summary)
            if pr_url:
                pr_urls.append(pr_url)
                add_log(job_id, f"[{cat_name}] PR created: {pr_url}")
            else:
                add_log(job_id, f"[{cat_name}] PR creation failed")

        except subprocess.TimeoutExpired:
            add_log(job_id, f"[{cat_name}] Push timed out")
        except Exception as e:
            add_log(job_id, f"[{cat_name}] Error: {str(e)[:100]}")

    committer._pending_commits.clear()

    if pr_urls:
        set_pr_url(job_id, pr_urls[0])  # Show first PR in UI
        add_log(job_id, f"Created {len(pr_urls)} category PR(s)")
    else:
        add_log(job_id, "No category PRs created")


def _push_to_existing_branches(job_id, config, committer, results_summary, category_branches, notify):
    """Push retry examples to the existing category branches (Option B).

    Instead of creating new branches/PRs, commits are pushed directly onto
    the branches created by the original job.  GitHub automatically updates
    the open PR to reflect the new commits.
    """
    import subprocess as _sp
    from pathlib import Path as _Path
    from git_ops.repo import _git_lock
    from git_ops.committer import normalize_category
    from git_ops.repo_docs import generate_cumulative_category_agents_md
    from git_ops.agents_md import _generate_run_id
    from git_ops.github_api import GitHubAPI

    groups = committer.get_pending_by_category()
    run_id = _generate_run_id()
    pr_urls = []

    owner, repo_name = GitHubAPI.extract_repo_info(config.git.repo_url)

    for cat_name, commits in sorted(groups.items()):
        if is_cancelled(job_id):
            break

        existing_branch = category_branches.get(cat_name)
        if not existing_branch:
            add_log(job_id, f"[{cat_name}] No existing branch found — skipping {len(commits)} file(s)")
            continue

        add_log(job_id, f"[{cat_name}] Pushing {len(commits)} retry file(s) to {existing_branch}...")
        set_current_task(job_id, f"Retry PR: {cat_name}...")

        try:
            cat_slug = normalize_category(cat_name, config.git.default_category)
            cat_dir = _Path(config.git.repo_path) / cat_slug

            # Regenerate agents.md with updated file list
            cs_files = sorted(c["path"].name for c in commits)
            agents_content = generate_cumulative_category_agents_md(
                cat_name, cs_files, run_id,
                kb_path=config.rules_examples_path,
                repo_path=config.git.repo_path,
                tfm=config.build.tfm,
                nuget_version=config.build.nuget_version,
            )
            agents_path = cat_dir / "agents.md"
            agents_path.parent.mkdir(parents=True, exist_ok=True)
            agents_path.write_text(agents_content, encoding="utf-8")

            with _git_lock:
                # Fetch & checkout existing branch
                _sp.run(
                    ["git", "fetch", "origin", existing_branch],
                    cwd=config.git.repo_path, check=True, capture_output=True, text=True, timeout=30,
                )
                _sp.run(
                    ["git", "checkout", existing_branch],
                    cwd=config.git.repo_path, check=True, capture_output=True, text=True,
                )

                # Stage .cs files
                for c in commits:
                    _sp.run(
                        ["git", "add", str(c["path"])],
                        cwd=config.git.repo_path, check=True, capture_output=True, text=True,
                    )

                # Stage index.json
                index_path = cat_dir / "index.json"
                if index_path.exists():
                    _sp.run(
                        ["git", "add", str(index_path)],
                        cwd=config.git.repo_path, check=True, capture_output=True, text=True,
                    )

                # Stage agents.md
                _sp.run(
                    ["git", "add", str(agents_path)],
                    cwd=config.git.repo_path, check=True, capture_output=True, text=True,
                )

                _sp.run(
                    ["git", "commit", "-m", f"Add {len(commits)} retry example(s) for {cat_name}"],
                    cwd=config.git.repo_path, check=True, capture_output=True, text=True,
                )
                _sp.run(
                    ["git", "push", "origin", existing_branch],
                    cwd=config.git.repo_path, check=True, capture_output=True, text=True, timeout=60,
                )

            add_log(job_id, f"[{cat_name}] Pushed — PR auto-updated on {existing_branch}")

            # Look up the existing PR URL to show in UI
            if owner and repo_name and config.git.repo_token:
                gh = GitHubAPI(config.git.repo_token)
                base = config.git.effective_pr_target
                pr_url = gh.find_existing_pr(owner, repo_name, existing_branch, base)
                if pr_url:
                    pr_urls.append(pr_url)
                    add_log(job_id, f"[{cat_name}] PR: {pr_url}")

        except _sp.TimeoutExpired:
            add_log(job_id, f"[{cat_name}] Push timed out")
        except Exception as e:
            add_log(job_id, f"[{cat_name}] Error: {str(e)[:120]}")

    committer._pending_commits.clear()

    if pr_urls:
        set_pr_url(job_id, pr_urls[0])
        add_log(job_id, f"Updated {len(pr_urls)} existing PR(s)")
    else:
        add_log(job_id, "Retry commits pushed (check GitHub for PR updates)")


def run_job(
    job_id: str,
    mode: str,
    prompt: str = None,
    prompts: list = None,
    category: str = None,
    product: str = None,
    repo_push: bool = False,
    force: bool = False,
    api_url: str = None,
    pr_target_branch: str = None,
):
    """Run a test job. Called from a daemon thread."""
    notify = _make_progress_callback(job_id)
    config = load_config()
    usage_tracker = UsageTracker()

    # Override API URL if provided
    if api_url:
        config.mcp.generate_url = api_url

    # Override PR target branch if provided
    if pr_target_branch:
        config.git.pr_target_branch = pr_target_branch

    try:
        if mode == "single":
            init_build(job_id, total=1)
            add_log(job_id, f"Testing: {prompt[:100]}...")
            set_current_task(job_id, prompt[:100])

            runner = PipelineRunner(config, progress_callback=notify, usage_tracker=usage_tracker)

            # Setup PR branch before running
            repo, committer, pr_manager = None, None, None
            if repo_push:
                repo, committer, pr_manager = _setup_pr_workflow(config, job_id, notify)

            task_input = TaskInput(
                task=prompt,
                category=category or "",
                product=product or config.git.default_product,
            )
            result = runner.execute(task_input)
            badge = _compute_badge(result)
            final_code = result.fixed_code or result.generated_code or ""
            status_str = "PASSED" if result.status == "SUCCESS" else "FAILED"

            if result.status == "SUCCESS":
                add_passed(job_id, "1", prompt[:100], badge, code=final_code, category=category or "", product=product or "", metadata=result.metadata)
                add_log(job_id, f"Passed ({badge})")
                # Commit code to repo
                if committer:
                    committer.commit_code(prompt, category or "", final_code, metadata=result.metadata)
            else:
                add_failed(job_id, "1", prompt[:100], badge, code=final_code, category=category or "", product=product or "")
                add_log(job_id, f"Failed ({badge})")
                # Post-pipeline rule learning for single task
                if result.build_log:
                    try:
                        _run_rule_learning(
                            job_id, config,
                            [{"task": prompt, "code": result.generated_code or "", "build_log": result.build_log}],
                            runner.builder, notify,
                        )
                    except Exception as e:
                        add_log(job_id, f"Rule learning error: {e}")

            # Batch commit + PR
            if committer and committer._pending_commits:
                _generate_agents_md_for_pending(job_id, config, committer)
                committer.batch_commit_and_push()
            if pr_manager and repo and repo.pr_branch:
                results_summary = [{"task": prompt[:100], "category": category or "", "status": status_str}]
                pr_url = pr_manager.create_pull_request(results_summary)
                if pr_url:
                    set_pr_url(job_id, pr_url)
                    add_log(job_id, f"Pull request created: {pr_url}")
                # Store branch for retry-failed
                if category:
                    set_category_branch(job_id, category, repo.pr_branch)

            # Report usage
            try:
                bs = get_build_state(job_id)
                report_job_usage(
                    config, job_id,
                    total=1,
                    passed=1 if result.status == "SUCCESS" else 0,
                    failed=0 if result.status == "SUCCESS" else 1,
                    elapsed_seconds=bs["elapsed"] if bs else 0,
                    usage_snapshot=usage_tracker.snapshot(),
                    status="success" if result.status == "SUCCESS" else "partial",
                )
            except Exception as e:
                print(f"[reporting] Error: {e}")

            set_status(job_id, "completed")
            add_log(job_id, "Pipeline complete.")
            return

        if mode == "csv":
            if not prompts:
                init_build(job_id, total=0)
                set_status(job_id, "completed")
                add_log(job_id, "No prompts to process.")
                return

            total = len(prompts)
            init_build(job_id, total=total)
            set_repo_push(job_id, repo_push)
            add_log(job_id, f"Starting batch: {total} task(s)")

            runner = PipelineRunner(config, progress_callback=notify, usage_tracker=usage_tracker)

            # Setup PR branch before running
            repo, committer, pr_manager = None, None, None
            if repo_push:
                repo, committer, pr_manager = _setup_pr_workflow(config, job_id, notify)
                if repo and repo.pr_branch:
                    set_pr_branch(job_id, repo.pr_branch)

            results_summary = []
            retry_queue = []       # Tasks to retry after transient failures
            failed_task_dicts = [] # Full task dicts for failed items (for retry-failed feature)
            failed_for_learning = []  # Collect failed tasks for post-pipeline rule learning
            max_retries = 3   # Max retry attempts for API_FAILED tasks

            # ── Resume stats: report how many tasks can be skipped ──
            if config.resume_batch:
                # Collect unique categories to report resume stats
                _resume_cats = set(p.get("category", "") for p in prompts)
                _total_cached = 0
                for _cat in _resume_cats:
                    _stats = get_resume_stats(config.results_dir, _cat)
                    _total_cached += _stats["passed"]
                if _total_cached:
                    add_log(job_id, f"Resume: {_total_cached} previously passed task(s) found on disk — will be skipped")

            for idx, p in enumerate(prompts, 1):
                if is_cancelled(job_id):
                    break

                # ── Pause check ──────────────────────────────────────
                if is_paused(job_id):
                    add_log(job_id, f"⏸ Paused after task {idx - 1}/{total}. Click Resume to continue.")
                    wait_if_paused(job_id)
                    if is_cancelled(job_id):
                        break
                    add_log(job_id, "▶ Resumed.")

                task_text = p.get("prompt", p.get("task", ""))
                task_id = str(p.get("id", idx))
                task_display = task_text[:100] if task_text else f"Task {idx}"

                # ── Resume check: skip tasks that already passed in a previous run ──
                if config.resume_batch and is_task_passed(config.results_dir, p.get("category", ""), task_id, task_text):
                    cached = load_cached_task(config.results_dir, p.get("category", ""), task_id, task_text)
                    if cached:
                        cached_code = cached["code"]
                        cached_badge = cached.get("badge", "CACHED")
                        cached_metadata = cached.get("metadata", {})
                        add_passed(job_id, task_id, task_display, f"{cached_badge} (cached)", code=cached_code, category=p.get("category", ""), product=p.get("product", ""), metadata=cached_metadata)
                        results_summary.append({"task": task_display, "category": p.get("category", ""), "status": "PASSED"})
                        # Re-commit to git so the code makes it into the PR
                        if committer:
                            committer.commit_code(task_text, p.get("category", ""), cached_code, metadata=cached_metadata)
                        add_log(job_id, f"Task {task_id} restored from cache (code + metadata)")
                        continue
                    # Code file missing — fall through to re-run the pipeline
                    add_log(job_id, f"Task {task_id} was cached but code file missing — re-running")

                separator = "=" * 60
                add_log(job_id, separator)
                add_log(job_id, f"Testing: {p.get('category', '')} - {task_display}")
                add_log(job_id, separator)
                cat_label = p.get("category", "")
                set_current_task(job_id, f"[{cat_label}] Processing task #{task_id} ({idx}/{total})..." if cat_label else f"Processing task #{task_id} ({idx}/{total})...")

                task_input = TaskInput(
                    task=task_text,
                    category=p.get("category", ""),
                    product=p.get("product", config.git.default_product),
                )
                result = runner.execute(task_input)
                badge = _compute_badge(result)
                final_code = result.fixed_code or result.generated_code or ""
                status_str = "PASSED" if result.status == "SUCCESS" else "FAILED"

                if result.status == "API_FAILED":
                    # Transient error (MCP timeout, network issue) — requeue
                    retry_count = p.get("_retry_count", 0)
                    if retry_count < max_retries:
                        p["_retry_count"] = retry_count + 1
                        retry_queue.append(p)
                        add_log(job_id, f"Task {task_id} hit a transient API error — queued for retry ({retry_count + 1}/{max_retries})")
                        continue
                    else:
                        add_log(job_id, f"Task {task_id} failed after {max_retries} retries (API unreachable)")

                results_summary.append({
                    "task": task_display,
                    "category": p.get("category", ""),
                    "status": status_str,
                })

                if result.status == "SUCCESS":
                    add_passed(job_id, task_id, task_display, badge, code=final_code, category=p.get("category", ""), product=p.get("product", ""), metadata=result.metadata)
                    add_log(job_id, f"Task {task_id} passed ({badge})")
                    save_result(config.results_dir, p.get("category", ""), task_id, task_text, "PASSED", stage=result.stage or "", badge=badge, code=final_code, metadata=result.metadata)
                    if committer:
                        committer.commit_code(task_text, p.get("category", ""), final_code, metadata=result.metadata)
                else:
                    add_failed(job_id, task_id, task_display, badge, code=final_code, category=p.get("category", ""), product=p.get("product", ""))
                    add_log(job_id, f"Task {task_id} failed ({badge})")
                    save_result(config.results_dir, p.get("category", ""), task_id, task_text, "FAILED", stage=result.stage or "", badge=badge, code=final_code, metadata=result.metadata)
                    # Store full task dict for retry-failed feature
                    failed_task_dicts.append({
                        "prompt": task_text,
                        "category": p.get("category", ""),
                        "product": p.get("product", config.git.default_product),
                        "id": task_id,
                    })
                    if result.build_log:
                        failed_for_learning.append({
                            "task": task_text,
                            "code": result.generated_code or "",
                            "build_log": result.build_log,
                        })

            # ── Process retry queue ──
            if retry_queue and not is_cancelled(job_id):
                add_log(job_id, f"Retrying {len(retry_queue)} task(s) that had transient API errors...")
                for p in retry_queue:
                    if is_cancelled(job_id):
                        break

                    task_text = p.get("prompt", p.get("task", ""))
                    task_id = str(p.get("id", ""))
                    task_display = task_text[:100] if task_text else "Task"
                    retry_num = p.get("_retry_count", 1)

                    cat_label = p.get("category", "")
                    add_log(job_id, f"Retry {retry_num}/{max_retries} for task #{task_id}")
                    set_current_task(job_id, f"[{cat_label}] Retrying task #{task_id}..." if cat_label else f"Retrying task #{task_id}...")

                    task_input = TaskInput(
                        task=task_text,
                        category=p.get("category", ""),
                        product=p.get("product", config.git.default_product),
                    )
                    result = runner.execute(task_input)
                    badge = _compute_badge(result)
                    final_code = result.fixed_code or result.generated_code or ""
                    status_str = "PASSED" if result.status == "SUCCESS" else "FAILED"

                    if result.status == "API_FAILED" and retry_num < max_retries:
                        p["_retry_count"] = retry_num + 1
                        retry_queue.append(p)
                        add_log(job_id, f"Task {task_id} still failing — queued again ({retry_num + 1}/{max_retries})")
                        continue

                    results_summary.append({
                        "task": task_display,
                        "category": p.get("category", ""),
                        "status": status_str,
                    })

                    if result.status == "SUCCESS":
                        add_passed(job_id, task_id, task_display, badge, code=final_code, category=p.get("category", ""), product=p.get("product", ""), metadata=result.metadata)
                        add_log(job_id, f"Task {task_id} passed on retry ({badge})")
                        save_result(config.results_dir, p.get("category", ""), task_id, task_text, "PASSED", stage=result.stage or "", badge=badge, code=final_code, metadata=result.metadata)
                        if committer:
                            committer.commit_code(task_text, p.get("category", ""), final_code, metadata=result.metadata)
                    else:
                        add_failed(job_id, task_id, task_display, badge, code=final_code, category=p.get("category", ""), product=p.get("product", ""))
                        add_log(job_id, f"Task {task_id} failed after retries ({badge})")
                        save_result(config.results_dir, p.get("category", ""), task_id, task_text, "FAILED", stage=result.stage or "", badge=badge, code=final_code, metadata=result.metadata)
                        failed_task_dicts.append({
                            "prompt": task_text,
                            "category": p.get("category", ""),
                            "product": p.get("product", config.git.default_product),
                            "id": task_id,
                        })
                        if result.build_log:
                            failed_for_learning.append({
                                "task": task_text,
                                "code": result.generated_code or "",
                                "build_log": result.build_log,
                            })

            # Persist results for PR retry and retry-failed feature
            set_results_summary(job_id, results_summary)
            set_failed_tasks(job_id, failed_task_dicts)

            # ── Post-pipeline rule learning ──
            if failed_for_learning and not is_cancelled(job_id):
                try:
                    _run_rule_learning(
                        job_id, config, failed_for_learning,
                        runner.builder, notify,
                    )
                except Exception as e:
                    add_log(job_id, f"Rule learning error: {e}")

            # Batch commit + PR
            if committer and committer._pending_commits:
                pending_count = len(committer._pending_commits)
                split_threshold = config.git.pr_split_threshold

                if split_threshold > 0 and pending_count > split_threshold:
                    # ── Split by category: one PR per category ──
                    add_log(job_id, f"Splitting {pending_count} file(s) into per-category PRs (threshold={split_threshold})...")
                    _split_commit_and_pr(job_id, config, repo, committer, pr_manager, results_summary, notify)
                else:
                    # ── Single PR (original behaviour) ──
                    _generate_agents_md_for_pending(job_id, config, committer)
                    add_log(job_id, f"Batch committing {pending_count} file(s)...")
                    committer.batch_commit_and_push()

                    if pr_manager and repo and repo.pr_branch and results_summary:
                        add_log(job_id, "Creating pull request...")
                        set_current_task(job_id, "Creating pull request...")
                        pr_url = pr_manager.create_pull_request(results_summary)
                        if pr_url:
                            set_pr_url(job_id, pr_url)
                            add_log(job_id, f"Pull request created: {pr_url}")
                        else:
                            add_log(job_id, "PR creation failed - changes are on the feature branch")

                    # Store the single branch under every category that was committed,
                    # so retry-failed can push to it (Option B)
                    if repo and repo.pr_branch:
                        groups = committer.get_pending_by_category() if committer._pending_commits else {}
                        committed_cats = set(groups.keys())
                        # If pending already cleared by batch_commit, derive from results_summary
                        if not committed_cats:
                            committed_cats = {r["category"] for r in results_summary if r["status"] == "PASSED" and r["category"]}
                        for cat in committed_cats:
                            set_category_branch(job_id, cat, repo.pr_branch)

            with JOB_LOCK:
                was_cancelled = JOB_CANCEL_FLAGS.pop(job_id, False)

            # Report usage
            try:
                bs = get_build_state(job_id)
                if bs:
                    r_status = "cancelled" if was_cancelled else (
                        "success" if bs["failed_count"] == 0 else "partial"
                    )
                    report_job_usage(
                        config, job_id,
                        total=bs["total"],
                        passed=bs["passed_count"],
                        failed=bs["failed_count"],
                        elapsed_seconds=bs["elapsed"],
                        usage_snapshot=usage_tracker.snapshot(),
                        status=r_status,
                    )
            except Exception as e:
                print(f"[reporting] Error: {e}")

            if was_cancelled:
                set_status(job_id, "cancelled")
                add_log(job_id, f"Job cancelled after {idx}/{total} task(s)")
            else:
                set_status(job_id, "completed")
                add_log(job_id, "Pipeline complete.")
            return

        # Unknown mode
        set_status(job_id, "failed")
        add_log(job_id, f"Invalid job mode: {mode}")

    except Exception as exc:
        with JOB_LOCK:
            JOB_CANCEL_FLAGS.pop(job_id, None)
        add_log(job_id, f"Job failed: {exc}")
        # Report failure
        try:
            bs = get_build_state(job_id)
            report_job_usage(
                config, job_id,
                total=bs["total"] if bs else 0,
                passed=bs["passed_count"] if bs else 0,
                failed=bs["failed_count"] if bs else 0,
                elapsed_seconds=bs["elapsed"] if bs else 0,
                usage_snapshot=usage_tracker.snapshot(),
                status="failed",
            )
        except Exception:
            pass
        set_status(job_id, "failed")


def create_pr(job_id: str, passed_results: list, results_summary: list):
    """Create a fresh PR from code stored in state's passed results.

    This handles the case where the job ran WITHOUT repo_push=true,
    and the user clicks "Create PR" afterwards.
    Commits each passed result's code to a new branch, then creates a PR.
    """
    notify = _make_progress_callback(job_id)
    config = load_config()

    try:
        add_log(job_id, "Creating PR from results...")
        set_current_task(job_id, "Setting up repository...")

        repo = RepoManager(
            repo_path=config.git.repo_path,
            repo_url=config.git.repo_url,
            repo_branch=config.git.repo_branch,
            repo_token=config.git.repo_token,
            repo_user=config.git.repo_user,
            notify=notify,
        )
        if not repo.ensure_ready():
            add_log(job_id, "Git repository not ready - cannot create PR")
            set_current_task(job_id, "PR retry complete.")
            return

        branch_name = f"examples/batch-{job_id[:8]}"
        if not repo.setup_pr_branch(branch_name):
            add_log(job_id, "Could not create PR branch")
            set_current_task(job_id, "PR retry complete.")
            return

        set_pr_branch(job_id, branch_name)
        add_log(job_id, f"PR branch created: {branch_name}")

        llm = LLMClient(config)
        committer = CodeCommitter(
            repo_path=config.git.repo_path,
            repo_push=True,
            pr_branch=repo.pr_branch,
            repo_branch=config.git.repo_branch,
            default_category=config.git.default_category,
            batch_git=True,
            notify=notify,
            llm_client=llm,
        )

        # Commit each passed result's code
        # NOTE: category is already stored in each passed result by add_passed() —
        # no need to look it up from results_summary (which gets overwritten per category).
        committed = 0
        for item in passed_results:
            code = item.get("code", "")
            task = item.get("task", "")
            if not code or not task:
                continue
            category = item.get("category", "")
            metadata = item.get("metadata", {})
            committer.commit_code(task, category, code, metadata=metadata)
            committed += 1

        if committer._pending_commits:
            _generate_agents_md_for_pending(job_id, config, committer)
            add_log(job_id, f"Batch committing {committed} file(s)...")
            committer.batch_commit_and_push()
        else:
            add_log(job_id, "No files to commit")
            set_current_task(job_id, "PR retry complete.")
            return

        # Create PR
        add_log(job_id, "Creating pull request...")
        set_current_task(job_id, "Creating pull request...")
        pr_manager = PRManager(config, repo, notify=notify, llm_client=llm)
        pr_url = pr_manager.create_pull_request(results_summary)
        if pr_url:
            set_pr_url(job_id, pr_url)
            add_log(job_id, f"Pull request created: {pr_url}")
        else:
            add_log(job_id, "PR creation failed - changes are on the feature branch")

        # Store branch under each committed category so retry-failed can use Option B
        committed_cats = {item.get("category", "") for item in passed_results if item.get("category")}
        for cat in committed_cats:
            set_category_branch(job_id, cat, branch_name)
        set_repo_push(job_id, True)

        set_current_task(job_id, "PR retry complete.")

    except Exception as exc:
        add_log(job_id, f"PR creation failed: {exc}")
        set_current_task(job_id, "PR retry complete.")


def retry_pr(job_id: str, old_pr_branch: str, results_summary: list):
    """Create a new conflict-free PR from already-generated examples.

    Recovers .cs files from an existing old feature branch.
    """
    notify = _make_progress_callback(job_id)
    config = load_config()

    try:
        add_log(job_id, "PR retry started...")
        set_current_task(job_id, "Setting up repository...")

        repo = RepoManager(
            repo_path=config.git.repo_path,
            repo_url=config.git.repo_url,
            repo_branch=config.git.repo_branch,
            repo_token=config.git.repo_token,
            repo_user=config.git.repo_user,
            notify=notify,
        )

        llm = LLMClient(config)
        pr_manager = PRManager(config, repo, notify=notify, llm_client=llm)

        pr_url = pr_manager.retry_pr(old_pr_branch, results_summary)
        if pr_url:
            set_pr_url(job_id, pr_url)
            set_pr_branch(job_id, repo.pr_branch or "")
            add_log(job_id, f"Pull request created: {pr_url}")
        else:
            add_log(job_id, "PR retry failed - branch may have been pushed but no PR created")

        set_current_task(job_id, "PR retry complete.")

    except Exception as exc:
        add_log(job_id, f"PR retry failed: {exc}")


def update_repo_docs(job_id: str, update_readme: bool = False):
    """Scan the repo and create a PR with cumulative agents.md (+ optional README update).

    Runs in a background thread. Creates a fresh branch, commits all
    generated docs, and opens a PR.
    """
    import subprocess
    import uuid as _uuid
    from git_ops.repo import _git_lock
    from git_ops.repo_docs import (
        normalize_repo_folders,
        scan_repo,
        generate_cumulative_agents_md,
        generate_cumulative_category_agents_md,
        generate_index_json,
        update_readme_categories,
    )
    from git_ops.agents_md import _generate_run_id

    notify = _make_progress_callback(job_id)
    config = load_config()

    try:
        init_build(job_id, total=0)
        add_log(job_id, "Repo docs: starting...")
        set_current_task(job_id, "Scanning repository...")

        repo = RepoManager(
            repo_path=config.git.repo_path,
            repo_url=config.git.repo_url,
            repo_branch=config.git.repo_branch,
            repo_token=config.git.repo_token,
            repo_user=config.git.repo_user,
            notify=notify,
        )
        if not repo.ensure_ready():
            add_log(job_id, "Repository not ready")
            set_status(job_id, "failed")
            return

        # Scan repo on main branch
        scan = scan_repo(config.git.repo_path)
        total_files = sum(len(files) for files in scan.values())
        add_log(job_id, f"Found {total_files} .cs file(s) across {len(scan)} categories")

        if not scan:
            add_log(job_id, "No .cs files found — nothing to do")
            set_status(job_id, "completed")
            return

        # Create docs branch
        branch_name = f"docs/update-{_uuid.uuid4().hex[:8]}"
        if not repo.setup_pr_branch(branch_name):
            add_log(job_id, "Could not create docs branch")
            set_status(job_id, "failed")
            return

        # Normalize folder names (e.g. "Working with Attachment" → "working-with-attachment")
        set_current_task(job_id, "Normalizing folder names...")
        renamed = normalize_repo_folders(config.git.repo_path)
        if renamed:
            add_log(job_id, f"Renamed {len(renamed)} folder(s): {', '.join(f'{k} → {v}' for k, v in renamed.items())}")
            # Re-scan after renames
            scan = scan_repo(config.git.repo_path)
            total_files = sum(len(files) for files in scan.values())
            add_log(job_id, f"Re-scanned: {total_files} .cs file(s) across {len(scan)} categories")

        run_id = _generate_run_id()
        repo_path = config.git.repo_path

        # Generate and write root agents.md (enhanced with resource content)
        set_current_task(job_id, "Generating agents.md...")
        agents_content = generate_cumulative_agents_md(
            scan, tfm=config.build.tfm,
            nuget_version=config.build.nuget_version, run_id=run_id,
            error_catalog_path=config.error_catalog_path,
            error_fixes_path=config.error_fixes_path,
            kb_path=config.rules_examples_path,
        )
        agents_path = Path(repo_path) / "agents.md"
        agents_path.write_text(agents_content, encoding="utf-8")
        add_log(job_id, f"Root agents.md: {total_files} examples, {len(scan)} categories (enhanced)")

        # Generate per-category agents.md (with category-specific tips)
        for cat_name, files in sorted(scan.items()):
            cat_agents = generate_cumulative_category_agents_md(
                cat_name, files, run_id,
                kb_path=config.rules_examples_path,
                repo_path=config.git.repo_path,
                tfm=config.build.tfm,
                nuget_version=config.build.nuget_version,
            )
            cat_path = Path(repo_path) / cat_name / "agents.md"
            cat_path.parent.mkdir(parents=True, exist_ok=True)
            cat_path.write_text(cat_agents, encoding="utf-8")

        add_log(job_id, f"Generated {len(scan)} category agents.md files")

        # Generate index.json (machine-readable manifest)
        set_current_task(job_id, "Generating index.json...")
        index_content = generate_index_json(
            scan,
            tfm=config.build.tfm,
            nuget_version=config.build.nuget_version,
            repo_path=config.git.repo_path,
        )
        index_path = Path(repo_path) / "index.json"
        index_path.write_text(index_content, encoding="utf-8")
        add_log(job_id, f"index.json: {len(scan)} categories, {total_files} examples")

        # Optionally update README.md
        if update_readme:
            set_current_task(job_id, "Updating README.md...")
            readme_path = Path(repo_path) / "README.md"
            if readme_path.exists():
                readme_content = readme_path.read_text(encoding="utf-8")
                updated = update_readme_categories(readme_content, scan)
                if updated != readme_content:
                    readme_path.write_text(updated, encoding="utf-8")
                    add_log(job_id, "README.md category listing updated")
                else:
                    add_log(job_id, "README.md unchanged (category section not found or identical)")
            else:
                add_log(job_id, "README.md not found — skipping")

        # Commit and push
        set_current_task(job_id, "Committing docs...")
        try:
            with _git_lock:
                subprocess.run(
                    ["git", "add", "-A"],
                    cwd=repo_path, check=True, capture_output=True, text=True,
                )
                subprocess.run(
                    ["git", "commit", "-m", f"Update repo docs ({total_files} examples, {len(scan)} categories)"],
                    cwd=repo_path, check=True, capture_output=True, text=True,
                )
                subprocess.run(
                    ["git", "push", "-u", "origin", branch_name],
                    cwd=repo_path, check=True, capture_output=True, text=True, timeout=30,
                )
        except subprocess.TimeoutExpired:
            add_log(job_id, "Push timed out")
            set_status(job_id, "failed")
            return

        # Create PR
        set_current_task(job_id, "Creating PR...")
        from git_ops.github_api import GitHubAPI
        gh = GitHubAPI(config.git.repo_token)
        owner, repo_name = GitHubAPI.extract_repo_info(config.git.repo_url)
        base = config.git.repo_branch or "main"

        title = f"Update repo docs ({total_files} examples)"
        body = (
            f"## Repository Documentation Update\n\n"
            f"Cumulative agents.md generated from repo scan.\n\n"
            f"- **{total_files}** examples across **{len(scan)}** categories\n"
            f"- Root agents.md updated\n"
            f"- {len(scan)} category agents.md files updated\n"
            + (f"- README.md category listing updated\n" if update_readme else "")
            + f"\n---\n*Generated by Examples Generator*"
        )

        pr_url = gh.create_pull_request(owner, repo_name, title, body, branch_name, base)
        if pr_url:
            set_pr_url(job_id, pr_url)
            add_log(job_id, f"Docs PR created: {pr_url}")
        else:
            add_log(job_id, "PR creation failed — docs are on the branch")

        set_status(job_id, "completed")
        set_current_task(job_id, "Repo docs update complete.")
        add_log(job_id, "Done.")

    except Exception as exc:
        add_log(job_id, f"Repo docs update failed: {exc}")
        set_status(job_id, "failed")
        set_current_task(job_id, "Repo docs update failed.")


def _fetch_tasks_for_category(config, category: str) -> list:
    """Fetch all tasks for a category from the external tasks API (paginated)."""
    if not config.tasks_api_url:
        return []
    tasks = []
    page = 1
    while True:
        try:
            resp = requests.get(
                config.tasks_api_url,
                params={"product": "aspose.pdf", "category": category, "page": page, "page_size": 50},
                timeout=15,
            )
            if resp.status_code != 200:
                break
            data = resp.json()
            items = data.get("items", [])
            if not items:
                break
            tasks.extend(items)
            if page >= data.get("total_pages", 1):
                break
            page += 1
        except Exception:
            break
    return tasks


def run_sweep(
    job_id: str,
    categories: list,
    repo_push: bool = False,
    api_url: str = None,
    pr_target_branch: str = None,
):
    """Run all tasks across selected categories, one category at a time.

    Per-category: usage report + optional PR.
    Single job with unified monitor.
    """
    from git_ops.repo import _git_lock

    notify = _make_progress_callback(job_id)
    config = load_config()

    if api_url:
        config.mcp.generate_url = api_url

    if pr_target_branch:
        config.git.pr_target_branch = pr_target_branch

    try:
        # ── Phase 1: Fetch all tasks upfront ──
        add_log(job_id, f"Sweep: fetching tasks for {len(categories)} category/ies...")
        init_build(job_id, total=0)
        set_current_task(job_id, "Fetching tasks...")

        all_category_tasks = {}
        for cat in categories:
            tasks = _fetch_tasks_for_category(config, cat)
            if tasks:
                all_category_tasks[cat] = tasks
                add_log(job_id, f"  {cat}: {len(tasks)} task(s)")
            else:
                add_log(job_id, f"  {cat}: no tasks found — skipping")

        grand_total = sum(len(t) for t in all_category_tasks.values())
        if grand_total == 0:
            add_log(job_id, "No tasks found across selected categories.")
            set_status(job_id, "completed")
            return

        set_total(job_id, grand_total)
        add_log(job_id, f"Sweep: {grand_total} total task(s) across {len(all_category_tasks)} category/ies")

        # ── Phase 2: Process each category ──
        global_idx = 0
        all_pr_urls = []

        # Setup repo, committer, pr_manager ONCE for the whole sweep.
        # The sweep handles per-category branching itself — we do NOT
        # need _setup_pr_workflow (which creates a single branch that
        # collides on the second category).
        repo, committer, pr_manager = None, None, None
        if repo_push:
            repo = RepoManager(
                repo_path=config.git.repo_path,
                repo_url=config.git.repo_url,
                repo_branch=config.git.repo_branch,
                repo_token=config.git.repo_token,
                repo_user=config.git.repo_user,
                notify=notify,
            )
            if repo.ensure_ready():
                llm = LLMClient(config)
                committer = CodeCommitter(
                    repo_path=config.git.repo_path,
                    repo_push=True,
                    pr_branch=None,  # sweep creates per-category branches
                    repo_branch=config.git.repo_branch,
                    default_category=config.git.default_category,
                    batch_git=True,
                    notify=notify,
                    llm_client=llm,
                )
                pr_manager = PRManager(config, repo, notify=notify, llm_client=llm)
                add_log(job_id, "Git repo ready for per-category PRs")
            else:
                add_log(job_id, "Git repository not ready - PRs will be skipped")
                repo = None

        for cat_name, tasks in all_category_tasks.items():
            if is_cancelled(job_id):
                break

            cat_tracker = UsageTracker()
            runner = PipelineRunner(config, progress_callback=notify, usage_tracker=cat_tracker)
            cat_start = time.monotonic()
            cat_passed = 0
            cat_failed = 0
            cat_results = []
            retry_queue = []
            max_retries = 3

            separator = "=" * 60
            add_log(job_id, separator)
            add_log(job_id, f"Category: {cat_name} ({len(tasks)} tasks)")
            add_log(job_id, separator)

            for task_obj in tasks:
                if is_cancelled(job_id):
                    break

                global_idx += 1
                task_text = task_obj.get("task", "")
                task_id = str(task_obj.get("id", global_idx))
                task_display = task_text[:100] if task_text else f"Task {global_idx}"

                set_current_task(job_id, f"[{cat_name}] Task {global_idx}/{grand_total}")

                # ── Resume check: skip tasks that already passed ──
                if config.resume_batch and is_task_passed(config.results_dir, cat_name, task_id, task_text):
                    cached = load_cached_task(config.results_dir, cat_name, task_id, task_text)
                    if cached:
                        cached_code = cached["code"]
                        cached_badge = cached.get("badge", "CACHED")
                        cached_metadata = cached.get("metadata", {})
                        add_passed(job_id, task_id, task_display, f"{cached_badge} (cached)", code=cached_code, category=cat_name, product=task_obj.get("product", ""), metadata=cached_metadata)
                        cat_results.append({"task": task_display, "category": cat_name, "status": "PASSED"})
                        cat_passed += 1
                        if committer:
                            committer.commit_code(task_text, cat_name, cached_code, metadata=cached_metadata)
                        add_log(job_id, f"Task {task_id} restored from cache (code + metadata)")
                        continue

                task_input = TaskInput(
                    task=task_text,
                    category=cat_name,
                    product=task_obj.get("product", config.git.default_product),
                )
                result = runner.execute(task_input)
                badge = _compute_badge(result)
                final_code = result.fixed_code or result.generated_code or ""

                if result.status == "API_FAILED":
                    retry_count = task_obj.get("_retry_count", 0)
                    if retry_count < max_retries:
                        task_obj["_retry_count"] = retry_count + 1
                        retry_queue.append(task_obj)
                        add_log(job_id, f"Task {task_id} API error — queued for retry ({retry_count + 1}/{max_retries})")
                        continue
                    else:
                        add_log(job_id, f"Task {task_id} failed after {max_retries} retries (API unreachable)")

                cat_results.append({"task": task_display, "category": cat_name, "status": "PASSED" if result.status == "SUCCESS" else "FAILED"})

                if result.status == "SUCCESS":
                    cat_passed += 1
                    add_passed(job_id, task_id, task_display, badge, code=final_code, category=cat_name, product=task_obj.get("product", ""), metadata=result.metadata)
                    add_log(job_id, f"Task {task_id} passed ({badge})")
                    save_result(config.results_dir, cat_name, task_id, task_text, "PASSED", stage=result.stage or "", badge=badge, code=final_code, metadata=result.metadata)
                    if committer:
                        committer.commit_code(task_text, cat_name, final_code, metadata=result.metadata)
                else:
                    cat_failed += 1
                    add_failed(job_id, task_id, task_display, badge, code=final_code, category=cat_name, product=task_obj.get("product", ""))
                    add_log(job_id, f"Task {task_id} failed ({badge})")
                    save_result(config.results_dir, cat_name, task_id, task_text, "FAILED", stage=result.stage or "", badge=badge, code=final_code, metadata=result.metadata)

            # ── Retry queue for this category ──
            for task_obj in retry_queue:
                if is_cancelled(job_id):
                    break
                global_idx += 1
                task_text = task_obj.get("task", "")
                task_id = str(task_obj.get("id", global_idx))
                task_display = task_text[:100] if task_text else "Task"

                set_current_task(job_id, f"[{cat_name}] Retrying task #{task_id}")
                task_input = TaskInput(task=task_text, category=cat_name, product=task_obj.get("product", config.git.default_product))
                result = runner.execute(task_input)
                badge = _compute_badge(result)
                final_code = result.fixed_code or result.generated_code or ""

                cat_results.append({"task": task_display, "category": cat_name, "status": "PASSED" if result.status == "SUCCESS" else "FAILED"})
                if result.status == "SUCCESS":
                    cat_passed += 1
                    add_passed(job_id, task_id, task_display, badge, code=final_code, category=cat_name, product=task_obj.get("product", ""), metadata=result.metadata)
                    add_log(job_id, f"Task {task_id} passed on retry ({badge})")
                    save_result(config.results_dir, cat_name, task_id, task_text, "PASSED", stage=result.stage or "", badge=badge, code=final_code, metadata=result.metadata)
                    if committer:
                        committer.commit_code(task_text, cat_name, final_code, metadata=result.metadata)
                else:
                    cat_failed += 1
                    add_failed(job_id, task_id, task_display, badge, code=final_code, category=cat_name, product=task_obj.get("product", ""))
                    add_log(job_id, f"Task {task_id} failed after retries ({badge})")
                    save_result(config.results_dir, cat_name, task_id, task_text, "FAILED", stage=result.stage or "", badge=badge, code=final_code, metadata=result.metadata)

            # ── Per-category PR ──
            if committer and committer._pending_commits:
                from git_ops.committer import normalize_category
                from git_ops.repo_docs import generate_cumulative_category_agents_md
                from git_ops.agents_md import _generate_run_id as _gen_rid

                cat_slug_dir = normalize_category(cat_name, config.git.default_category)
                cat_dir = Path(config.git.repo_path) / cat_slug_dir
                cat_slug = cat_name.lower().replace(" ", "-")[:30]
                cat_branch = f"examples/{job_id[:8]}-{cat_slug}"
                pending_count = len(committer._pending_commits)
                add_log(job_id, f"[{cat_name}] Creating PR ({pending_count} file(s))...")
                set_current_task(job_id, f"PR: {cat_name}...")

                try:
                    # Generate agents.md before staging
                    cs_files = sorted(f.name for f in cat_dir.iterdir() if f.is_file() and f.suffix == ".cs") if cat_dir.exists() else sorted(c["path"].name for c in committer._pending_commits)
                    agents_content = generate_cumulative_category_agents_md(
                        cat_name, cs_files, _gen_rid(),
                        kb_path=config.rules_examples_path,
                        repo_path=config.git.repo_path,
                        tfm=config.build.tfm,
                        nuget_version=config.build.nuget_version,
                    )
                    agents_path = cat_dir / "agents.md"
                    agents_path.parent.mkdir(parents=True, exist_ok=True)
                    agents_path.write_text(agents_content, encoding="utf-8")

                    with _git_lock:
                        base_branch = config.git.effective_pr_target
                        subprocess.run(["git", "checkout", f"origin/{base_branch}"], cwd=config.git.repo_path, check=True, capture_output=True, text=True)
                        subprocess.run(["git", "checkout", "-b", cat_branch], cwd=config.git.repo_path, check=True, capture_output=True, text=True)
                        for c in committer._pending_commits:
                            subprocess.run(["git", "add", str(c["path"])], cwd=config.git.repo_path, check=True, capture_output=True, text=True)
                        # Stage index.json if it exists
                        index_path = cat_dir / "index.json"
                        if index_path.exists():
                            subprocess.run(["git", "add", str(index_path)], cwd=config.git.repo_path, check=True, capture_output=True, text=True)
                        # Stage agents.md
                        subprocess.run(["git", "add", str(agents_path)], cwd=config.git.repo_path, check=True, capture_output=True, text=True)
                        subprocess.run(["git", "commit", "-m", f"Add {pending_count} example(s) for {cat_name}"], cwd=config.git.repo_path, check=True, capture_output=True, text=True)
                        subprocess.run(["git", "push", "-u", "origin", cat_branch], cwd=config.git.repo_path, check=True, capture_output=True, text=True, timeout=60)

                    sweep_results_summary = [
                        {"task": c["prompt"], "category": cat_name, "status": "PASSED"}
                        for c in committer._pending_commits
                    ]
                    repo.pr_branch = cat_branch
                    pr_url = pr_manager.create_category_pr(cat_name, pending_count,
                                                           results_summary=sweep_results_summary)
                    # Record branch so retry-failed can push to it
                    set_category_branch(job_id, cat_name, cat_branch)
                    if pr_url:
                        all_pr_urls.append(pr_url)
                        add_log(job_id, f"[{cat_name}] PR created: {pr_url}")
                    else:
                        add_log(job_id, f"[{cat_name}] PR creation failed")
                except subprocess.TimeoutExpired:
                    add_log(job_id, f"[{cat_name}] Push timed out")
                except Exception as e:
                    add_log(job_id, f"[{cat_name}] PR error: {str(e)[:100]}")

                committer._pending_commits.clear()

            # ── Per-category usage report ──
            cat_elapsed = time.monotonic() - cat_start
            cat_slug = cat_name.lower().replace(" ", "-")[:30]
            try:
                report_job_usage(
                    config, f"{job_id}-{cat_slug}",
                    total=len(tasks), passed=cat_passed, failed=cat_failed,
                    elapsed_seconds=cat_elapsed,
                    usage_snapshot=cat_tracker.snapshot(),
                    status="success" if cat_failed == 0 else "partial",
                )
            except Exception as e:
                print(f"[reporting] Category report error: {e}")

            add_log(job_id, f"[{cat_name}] Done: {cat_passed} passed, {cat_failed} failed")

        # ── Finalize ──
        if all_pr_urls:
            set_pr_url(job_id, all_pr_urls[0])

        with JOB_LOCK:
            was_cancelled = JOB_CANCEL_FLAGS.pop(job_id, False)

        if was_cancelled:
            set_status(job_id, "cancelled")
            add_log(job_id, "Sweep cancelled.")
        else:
            set_status(job_id, "completed")
            add_log(job_id, "Sweep complete.")

    except Exception as exc:
        with JOB_LOCK:
            JOB_CANCEL_FLAGS.pop(job_id, None)
        add_log(job_id, f"Sweep failed: {exc}")
        set_status(job_id, "failed")


def _update_env_file(key: str, value: str):
    """Update or add a key=value line in .env file."""
    env_path = Path(".env")
    lines = env_path.read_text(encoding="utf-8").splitlines() if env_path.exists() else []
    found = False
    new_lines = []
    for line in lines:
        if line.startswith(f"{key}=") or line.startswith(f"{key} ="):
            new_lines.append(f"{key}={value}")
            found = True
        else:
            new_lines.append(line)
    if not found:
        new_lines.append(f"{key}={value}")
    env_path.write_text("\n".join(new_lines) + "\n", encoding="utf-8")


def run_version_bump(job_id: str, new_version: str, repo_push: bool = True):
    """Version bump setup:

    1. Tag current main as v{old_version} + create GitHub Release
    2. Create empty orphan release/{new_version} branch on remote
    3. Update .env: NUGET_VERSION, PR_TARGET_BRANCH, REPO_BRANCH
    4. Update runtime config

    Does NOT run sweep — user triggers sweeps per category manually.
    """
    from git_ops.github_api import GitHubAPI

    notify = _make_progress_callback(job_id)
    config = load_config()
    old_version = config.build.nuget_version
    staging_branch = f"release/{new_version}"

    try:
        init_build(job_id, total=0)
        add_log(job_id, f"Version bump setup: {old_version} → {new_version}")

        if not config.git.repo_token:
            add_log(job_id, "ERROR: REPO_TOKEN not configured")
            set_status(job_id, "failed")
            return

        gh = GitHubAPI(config.git.repo_token)
        owner, repo_name = GitHubAPI.extract_repo_info(config.git.repo_url)
        if not owner or not repo_name:
            add_log(job_id, "ERROR: Could not parse repo URL")
            set_status(job_id, "failed")
            return

        # ── Phase 1: Tag + Release current main ──
        set_current_task(job_id, f"Tagging v{old_version}...")
        add_log(job_id, f"Phase 1: Tagging v{old_version} on main")

        main_sha = gh.get_branch_sha(owner, repo_name, "main")
        if not main_sha:
            add_log(job_id, "ERROR: Could not get SHA for main")
            set_status(job_id, "failed")
            return

        tag_name = f"v{old_version}"
        if gh.create_tag(owner, repo_name, tag_name, main_sha):
            add_log(job_id, f"✓ Created tag: {tag_name}")
        else:
            add_log(job_id, f"Tag {tag_name} may already exist — continuing")

        release_body = (
            f"Examples generated for **Aspose.PDF for .NET {old_version}**.\n\n"
            f"- Target framework: `{config.build.tfm}`\n"
            f"- NuGet package: `Aspose.PDF {old_version}`\n"
        )
        release_url = gh.create_release(
            owner, repo_name, tag_name,
            f"Aspose.PDF {old_version} Examples", release_body,
        )
        if release_url:
            add_log(job_id, f"✓ GitHub Release created: {release_url}")
        else:
            add_log(job_id, "Release creation failed — continuing anyway")

        # ── Phase 2: Create empty orphan staging branch ──
        set_current_task(job_id, f"Creating {staging_branch}...")
        add_log(job_id, f"Phase 2: Creating empty orphan branch: {staging_branch}")

        if gh.get_branch_sha(owner, repo_name, staging_branch):
            add_log(job_id, f"Branch {staging_branch} already exists — skipping creation")
        elif gh.create_empty_branch(
            owner, repo_name, staging_branch,
            log_fn=lambda msg: add_log(job_id, msg),
        ):
            add_log(job_id, f"✓ Created empty branch: {staging_branch}")
        else:
            add_log(job_id, f"ERROR: Could not create branch {staging_branch}")
            add_log(job_id, "  Check: REPO_TOKEN has 'repo' (contents write) scope")
            add_log(job_id, f"  Repo:  {config.git.repo_url}")
            set_status(job_id, "failed")
            return

        # ── Phase 3: Update .env and runtime config ──
        set_current_task(job_id, "Updating config...")
        add_log(job_id, "Phase 3: Updating .env configuration")

        _update_env_file("NUGET_VERSION", new_version)
        _update_env_file("PR_TARGET_BRANCH", staging_branch)
        _update_env_file("REPO_BRANCH", staging_branch)

        config.build.nuget_version = new_version
        config.git.pr_target_branch = staging_branch
        config.git.repo_branch = staging_branch

        add_log(job_id, f"✓ .env updated: NUGET_VERSION={new_version}")
        add_log(job_id, f"✓ .env updated: PR_TARGET_BRANCH={staging_branch}")
        add_log(job_id, f"✓ .env updated: REPO_BRANCH={staging_branch}")
        add_log(job_id, "")
        add_log(job_id, "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
        add_log(job_id, f"✅ Version bump setup complete!")
        add_log(job_id, f"   Old version tagged: {tag_name}")
        add_log(job_id, f"   Staging branch:     {staging_branch}")
        add_log(job_id, f"   New NuGet version:  {new_version}")
        add_log(job_id, "")
        add_log(job_id, "Next steps:")
        add_log(job_id, "  1. Restart the app to load new .env settings")
        add_log(job_id, "  2. Run Sweep per category — PRs will target " + staging_branch)
        add_log(job_id, "  3. Review and merge each category PR on GitHub")
        add_log(job_id, "  4. Click 'Promote to Main' when all categories are done")
        add_log(job_id, "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")

        set_status(job_id, "completed")

    except Exception as exc:
        add_log(job_id, f"Version bump failed: {exc}")
        set_status(job_id, "failed")


def run_promote_to_main(job_id: str, staging_branch: str, new_version: str):
    """Promote staging branch to main:

    1. Create PR staging_branch → main
    2. Merge the PR
    3. Tag main as v{new_version} + create GitHub Release
    4. Update .env: reset PR_TARGET_BRANCH and REPO_BRANCH to main
    5. Delete staging branch
    """
    from git_ops.github_api import GitHubAPI

    notify = _make_progress_callback(job_id)
    config = load_config()

    try:
        init_build(job_id, total=0)
        add_log(job_id, f"Promoting {staging_branch} → main")

        if not config.git.repo_token:
            add_log(job_id, "ERROR: REPO_TOKEN not configured")
            set_status(job_id, "failed")
            return

        gh = GitHubAPI(config.git.repo_token)
        owner, repo_name = GitHubAPI.extract_repo_info(config.git.repo_url)
        if not owner or not repo_name:
            add_log(job_id, "ERROR: Could not parse repo URL")
            set_status(job_id, "failed")
            return

        # ── Phase 1: Create PR staging → main ──
        set_current_task(job_id, f"Creating PR {staging_branch} → main...")
        add_log(job_id, f"Phase 1: Creating PR {staging_branch} → main")

        pr_title = f"Release Aspose.PDF {new_version} Examples"
        pr_body = (
            f"## Aspose.PDF {new_version} Examples\n\n"
            f"This PR promotes all generated examples for **Aspose.PDF for .NET {new_version}** "
            f"from `{staging_branch}` to `main`.\n\n"
            f"- NuGet package: `Aspose.PDF {new_version}`\n"
            f"- All categories have been generated and reviewed\n"
        )

        pr_url = gh.create_pull_request(owner, repo_name, pr_title, pr_body, staging_branch, "main")
        if not pr_url:
            add_log(job_id, "ERROR: Could not create PR")
            set_status(job_id, "failed")
            return
        add_log(job_id, f"✓ PR created: {pr_url}")
        set_pr_url(job_id, pr_url)

        # ── Phase 2: Merge the PR ──
        set_current_task(job_id, "Merging PR...")
        add_log(job_id, "Phase 2: Merging PR into main")

        pr_number = gh.get_pr_number(owner, repo_name, staging_branch, "main")
        if not pr_number:
            add_log(job_id, "Could not find PR number — please merge manually via GitHub")
            add_log(job_id, f"PR URL: {pr_url}")
            set_status(job_id, "completed")
            return

        if gh.merge_pull_request(owner, repo_name, pr_number,
                                  f"Release Aspose.PDF {new_version} examples"):
            add_log(job_id, f"✓ PR merged into main")
        else:
            add_log(job_id, "Auto-merge failed — please merge manually via GitHub")
            add_log(job_id, f"PR URL: {pr_url}")
            set_status(job_id, "completed")
            return

        # ── Phase 3: Tag main as new version ──
        set_current_task(job_id, f"Tagging v{new_version}...")
        add_log(job_id, f"Phase 3: Tagging main as v{new_version}")

        import time as _time
        _time.sleep(2)  # brief pause for GitHub to finalize merge
        main_sha = gh.get_branch_sha(owner, repo_name, "main")
        if main_sha:
            tag_name = f"v{new_version}"
            if gh.create_tag(owner, repo_name, tag_name, main_sha):
                add_log(job_id, f"✓ Created tag: {tag_name}")

            release_body = (
                f"Examples generated for **Aspose.PDF for .NET {new_version}**.\n\n"
                f"- Target framework: `{config.build.tfm}`\n"
                f"- NuGet package: `Aspose.PDF {new_version}`\n"
            )
            release_url = gh.create_release(
                owner, repo_name, tag_name,
                f"Aspose.PDF {new_version} Examples", release_body,
            )
            if release_url:
                add_log(job_id, f"✓ GitHub Release created: {release_url}")

        # ── Phase 4: Update .env — reset back to main ──
        set_current_task(job_id, "Updating config...")
        add_log(job_id, "Phase 4: Resetting .env to main")

        _update_env_file("NUGET_VERSION", new_version)
        _update_env_file("PR_TARGET_BRANCH", "")
        _update_env_file("REPO_BRANCH", "main")

        add_log(job_id, "✓ .env updated: REPO_BRANCH=main")
        add_log(job_id, "✓ .env updated: PR_TARGET_BRANCH= (cleared)")

        # ── Phase 5: Delete staging branch ──
        set_current_task(job_id, "Cleaning up...")
        add_log(job_id, f"Phase 5: Deleting staging branch {staging_branch}")
        if gh.delete_branch(owner, repo_name, staging_branch):
            add_log(job_id, f"✓ Deleted {staging_branch}")
        else:
            add_log(job_id, f"Could not delete {staging_branch} — remove manually if needed")

        add_log(job_id, "")
        add_log(job_id, "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
        add_log(job_id, f"✅ Promotion complete!")
        add_log(job_id, f"   main now has: Aspose.PDF {new_version} examples")
        add_log(job_id, f"   Tagged:        v{new_version}")
        add_log(job_id, "   Restart the app to load updated .env settings")
        add_log(job_id, "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")

        set_status(job_id, "completed")

    except Exception as exc:
        add_log(job_id, f"Promote to main failed: {exc}")
        set_status(job_id, "failed")


def run_retry_failed(
    job_id: str,
    original_job_id: str,
    failed_tasks: list,
    repo_push: bool = False,
    api_url: str = None,
    pr_target_branch: str = None,
):
    """Re-run failed tasks from a previous job.

    If the original job used repo_push and created category branches,
    new passing examples are pushed to those same branches (Option B —
    same branch, same PR updated automatically on GitHub).
    """
    notify = _make_progress_callback(job_id)
    config = load_config()
    usage_tracker = UsageTracker()

    if api_url:
        config.mcp.generate_url = api_url
    if pr_target_branch:
        config.git.pr_target_branch = pr_target_branch

    total = len(failed_tasks)
    init_build(job_id, total=total)
    set_repo_push(job_id, repo_push)
    add_log(job_id, f"Retrying {total} failed task(s) from job {original_job_id[:8]}...")

    # Get category→branch mapping from original job for Option B
    original_state = get_build_state(original_job_id)
    category_branches = original_state.get("category_branches", {}) if original_state else {}
    if category_branches:
        add_log(job_id, f"Found {len(category_branches)} existing branch(es) — will push to them")
    else:
        add_log(job_id, "No existing branches from original job — new branches will be created")

    try:
        runner = PipelineRunner(config, progress_callback=notify, usage_tracker=usage_tracker)

        # Setup repo for committing
        repo, committer, pr_manager = None, None, None
        if repo_push:
            if category_branches:
                # Option B: use repo without creating a new PR branch — we'll push to existing branches
                repo = RepoManager(
                    repo_path=config.git.repo_path,
                    repo_url=config.git.repo_url,
                    repo_branch=config.git.repo_branch,
                    repo_token=config.git.repo_token,
                    repo_user=config.git.repo_user,
                    notify=notify,
                )
                if repo.ensure_ready():
                    from git_ops.llm_client import LLMClient as _LLC
                    llm = _LLC(config)
                    committer = CodeCommitter(
                        repo_path=config.git.repo_path,
                        repo_push=True,
                        pr_branch=None,
                        repo_branch=config.git.repo_branch,
                        default_category=config.git.default_category,
                        batch_git=True,
                        notify=notify,
                        llm_client=llm,
                    )
                    pr_manager = PRManager(config, repo, notify=notify, llm_client=llm)
                else:
                    add_log(job_id, "Git repository not ready — commits will be skipped")
                    repo = None
            else:
                # No existing branches — create new ones via normal workflow
                repo, committer, pr_manager = _setup_pr_workflow(config, job_id, notify)
                if repo and repo.pr_branch:
                    set_pr_branch(job_id, repo.pr_branch)

        results_summary = []
        failed_task_dicts = []
        failed_for_learning = []

        for idx, p in enumerate(failed_tasks, 1):
            if is_cancelled(job_id):
                break

            # ── Pause check ──
            if is_paused(job_id):
                add_log(job_id, f"⏸ Paused after task {idx - 1}/{total}. Click Resume to continue.")
                wait_if_paused(job_id)
                if is_cancelled(job_id):
                    break
                add_log(job_id, "▶ Resumed.")

            task_text = p.get("prompt", p.get("task", ""))
            task_id = str(p.get("id", idx))
            category = p.get("category", "")
            task_display = task_text[:100] if task_text else f"Task {idx}"

            separator = "=" * 60
            add_log(job_id, separator)
            add_log(job_id, f"Retry [{idx}/{total}]: {category} - {task_display}")
            add_log(job_id, separator)
            set_current_task(job_id, f"[{category}] Retrying {idx}/{total}..." if category else f"Retrying {idx}/{total}...")

            task_input = TaskInput(
                task=task_text,
                category=category,
                product=p.get("product", config.git.default_product),
            )
            result = runner.execute(task_input)
            badge = _compute_badge(result)
            final_code = result.fixed_code or result.generated_code or ""
            status_str = "PASSED" if result.status == "SUCCESS" else "FAILED"

            results_summary.append({"task": task_display, "category": category, "status": status_str})

            if result.status == "SUCCESS":
                add_passed(job_id, task_id, task_display, badge, code=final_code,
                           category=category, product=p.get("product", ""), metadata=result.metadata)
                add_log(job_id, f"✓ Task {task_id} now passes ({badge})")
                if committer:
                    committer.commit_code(task_text, category, final_code, metadata=result.metadata)
            else:
                add_failed(job_id, task_id, task_display, badge, code=final_code,
                           category=category, product=p.get("product", ""))
                add_log(job_id, f"✗ Task {task_id} still failing ({badge})")
                failed_task_dicts.append({
                    "prompt": task_text,
                    "category": category,
                    "product": p.get("product", config.git.default_product),
                    "id": task_id,
                })
                if result.build_log:
                    failed_for_learning.append({
                        "task": task_text,
                        "code": result.generated_code or "",
                        "build_log": result.build_log,
                    })

        set_results_summary(job_id, results_summary)
        set_failed_tasks(job_id, failed_task_dicts)

        # ── Commit & PR ──
        if committer and committer._pending_commits:
            if category_branches:
                # Option B — push to existing branches
                _push_to_existing_branches(
                    job_id, config, committer, results_summary, category_branches, notify,
                )
            else:
                # No existing branches — split or single PR
                pending_count = len(committer._pending_commits)
                split_threshold = config.git.pr_split_threshold
                if split_threshold > 0 and pending_count > split_threshold:
                    _split_commit_and_pr(job_id, config, repo, committer, pr_manager, results_summary, notify)
                else:
                    _generate_agents_md_for_pending(job_id, config, committer)
                    committer.batch_commit_and_push()
                    if pr_manager and repo and repo.pr_branch and results_summary:
                        pr_url = pr_manager.create_pull_request(results_summary)
                        if pr_url:
                            set_pr_url(job_id, pr_url)
                            add_log(job_id, f"Pull request created: {pr_url}")
                        # Store branch for retry-failed
                        committed_cats = {r["category"] for r in results_summary if r["status"] == "PASSED" and r.get("category")}
                        for cat in committed_cats:
                            set_category_branch(job_id, cat, repo.pr_branch)

        # ── Rule learning ──
        if failed_for_learning and not is_cancelled(job_id):
            try:
                _run_rule_learning(job_id, config, failed_for_learning, runner.builder, notify)
            except Exception as e:
                add_log(job_id, f"Rule learning error: {e}")

        with JOB_LOCK:
            was_cancelled = JOB_CANCEL_FLAGS.pop(job_id, False)

        # Report usage
        try:
            bs = get_build_state(job_id)
            if bs:
                r_status = "cancelled" if was_cancelled else (
                    "success" if bs["failed_count"] == 0 else "partial"
                )
                report_job_usage(
                    config, job_id,
                    total=bs["total"],
                    passed=bs["passed_count"],
                    failed=bs["failed_count"],
                    elapsed_seconds=bs["elapsed"],
                    usage_snapshot=usage_tracker.snapshot(),
                    status=r_status,
                )
        except Exception as e:
            print(f"[reporting] Error: {e}")

        if was_cancelled:
            set_status(job_id, "cancelled")
            add_log(job_id, "Retry job cancelled.")
        else:
            set_status(job_id, "completed")
            bs = get_build_state(job_id)
            if bs:
                add_log(job_id, f"Retry complete: {bs['passed_count']} passed, {bs['failed_count']} still failing.")
            else:
                add_log(job_id, "Retry complete.")

    except Exception as exc:
        with JOB_LOCK:
            JOB_CANCEL_FLAGS.pop(job_id, None)
        add_log(job_id, f"Retry job failed: {exc}")
        set_status(job_id, "failed")
