"""
jobs.py — Background worker (run_job, retry_pr).

Runs in a daemon thread — NOT in the async event loop.
This keeps heavy CPU/IO work (dotnet build, ML models) off Uvicorn's event loop.

Fully in-memory — no database. Results tracked via state.BUILD_STATE.
"""

import uuid

from config import load_config
from pipeline.models import TaskInput
from pipeline.runner import PipelineRunner
from git_ops.repo import RepoManager
from git_ops.committer import CodeCommitter
from git_ops.pr import PRManager
from pipeline.llm_client import LLMClient
from state import (
    add_failed, add_log, add_passed, is_cancelled,
    init_build, set_current_task, set_pr_url, set_pr_branch,
    set_results_summary, set_status, set_total,
    JOB_CANCEL_FLAGS, JOB_LOCK,
)


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
):
    """Run a test job. Called from a daemon thread."""
    notify = _make_progress_callback(job_id)
    config = load_config()

    # Override API URL if provided
    if api_url:
        config.mcp.generate_url = api_url

    try:
        if mode == "single":
            init_build(job_id, total=1)
            add_log(job_id, f"Testing: {prompt[:100]}...")
            set_current_task(job_id, prompt[:100])

            runner = PipelineRunner(config, progress_callback=notify)

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
                add_passed(job_id, "1", prompt[:100], badge, code=final_code, category=category or "", product=product or "")
                add_log(job_id, f"Passed ({badge})")
                # Commit code to repo
                if committer:
                    committer.commit_code(prompt, category or "", final_code)
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
                committer.batch_commit_and_push()
            if pr_manager and repo and repo.pr_branch:
                results_summary = [{"task": prompt[:100], "category": category or "", "status": status_str}]
                pr_url = pr_manager.create_pull_request(results_summary)
                if pr_url:
                    set_pr_url(job_id, pr_url)
                    add_log(job_id, f"Pull request created: {pr_url}")

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
            add_log(job_id, f"Starting batch: {total} task(s)")

            runner = PipelineRunner(config, progress_callback=notify)

            # Setup PR branch before running
            repo, committer, pr_manager = None, None, None
            if repo_push:
                repo, committer, pr_manager = _setup_pr_workflow(config, job_id, notify)
                if repo and repo.pr_branch:
                    set_pr_branch(job_id, repo.pr_branch)

            results_summary = []
            retry_queue = []  # Tasks to retry after transient failures
            failed_for_learning = []  # Collect failed tasks for post-pipeline rule learning
            max_retries = 3   # Max retry attempts for API_FAILED tasks

            for idx, p in enumerate(prompts, 1):
                if is_cancelled(job_id):
                    break

                task_text = p.get("prompt", p.get("task", ""))
                task_id = str(p.get("id", idx))
                task_display = task_text[:100] if task_text else f"Task {idx}"

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
                    add_passed(job_id, task_id, task_display, badge, code=final_code, category=p.get("category", ""), product=p.get("product", ""))
                    add_log(job_id, f"Task {task_id} passed ({badge})")
                    if committer:
                        committer.commit_code(task_text, p.get("category", ""), final_code)
                else:
                    add_failed(job_id, task_id, task_display, badge, code=final_code, category=p.get("category", ""), product=p.get("product", ""))
                    add_log(job_id, f"Task {task_id} failed ({badge})")
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
                        add_passed(job_id, task_id, task_display, badge, code=final_code, category=p.get("category", ""), product=p.get("product", ""))
                        add_log(job_id, f"Task {task_id} passed on retry ({badge})")
                        if committer:
                            committer.commit_code(task_text, p.get("category", ""), final_code)
                    else:
                        add_failed(job_id, task_id, task_display, badge, code=final_code, category=p.get("category", ""), product=p.get("product", ""))
                        add_log(job_id, f"Task {task_id} failed after retries ({badge})")
                        if result.build_log:
                            failed_for_learning.append({
                                "task": task_text,
                                "code": result.generated_code or "",
                                "build_log": result.build_log,
                            })

            # Persist results for PR retry
            set_results_summary(job_id, results_summary)

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
                add_log(job_id, f"Batch committing {len(committer._pending_commits)} file(s)...")
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

            with JOB_LOCK:
                was_cancelled = JOB_CANCEL_FLAGS.pop(job_id, False)

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
        committed = 0
        for item in passed_results:
            code = item.get("code", "")
            task = item.get("task", "")
            if not code or not task:
                continue
            # Find the category from results_summary
            category = ""
            for rs in results_summary:
                if rs.get("task", "") == task:
                    category = rs.get("category", "")
                    break
            committer.commit_code(task, category, code)
            committed += 1

        if committer._pending_commits:
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
