"""
cli.py — CLI entry point for running tasks without a web server.

Usage:
    python cli.py --task "Convert PDF to HTML"
    python cli.py --csv tasks.csv --repo-push
    python cli.py --task "Merge PDFs" --tfm net10.0
"""

import argparse
import csv
import sys

from dotenv import load_dotenv
load_dotenv()

from config import load_config
from pipeline.models import TaskInput
from pipeline.runner import PipelineRunner
from git_ops.repo import RepoManager
from git_ops.committer import CodeCommitter
from git_ops.pr import PRManager
from pipeline.llm_client import LLMClient


def _progress(stage: str, message: str):
    print(f"  [{stage}] {message}")


def run_single(config, task: str, category: str, product: str, repo_push: bool):
    """Run a single task through the pipeline."""
    runner = PipelineRunner(config, progress_callback=_progress)
    task_input = TaskInput(task=task, category=category, product=product)

    print(f"\nTask: {task}")
    print(f"Category: {category or '(auto)'}")
    print(f"Product: {product}")
    print("-" * 60)

    result = runner.execute(task_input)

    print("-" * 60)
    print(f"Status: {result.status}")
    print(f"Stage: {result.stage}")

    if result.status == "SUCCESS":
        final_code = result.fixed_code or result.generated_code or ""
        print(f"Code length: {len(final_code)} chars")

        if repo_push:
            _commit_and_pr(config, task, category, final_code, [
                {"task": task[:100], "category": category, "status": "PASSED"}
            ])
    else:
        print("Pipeline failed - no successful code generated")

    return 0 if result.status == "SUCCESS" else 1


def run_csv(config, csv_path: str, repo_push: bool):
    """Run all tasks from a CSV file."""
    try:
        with open(csv_path, "r", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            tasks = []
            for row in reader:
                task_text = row.get("task") or row.get("prompt") or ""
                if task_text.strip():
                    tasks.append({
                        "task": task_text.strip(),
                        "category": (row.get("category") or "").strip(),
                        "product": (row.get("product") or config.git.default_product).strip(),
                    })
    except FileNotFoundError:
        print(f"Error: CSV file not found: {csv_path}")
        return 1

    if not tasks:
        print("No valid tasks found in CSV")
        return 1

    print(f"\nBatch: {len(tasks)} task(s) from {csv_path}")
    print("=" * 60)

    runner = PipelineRunner(config, progress_callback=_progress)
    results_summary = []
    passed = 0
    failed = 0
    commit_items = []

    for idx, t in enumerate(tasks, 1):
        print(f"\n[{idx}/{len(tasks)}] {t['task'][:80]}...")
        task_input = TaskInput(
            task=t["task"],
            category=t["category"],
            product=t["product"],
        )
        result = runner.execute(task_input)
        final_code = result.fixed_code or result.generated_code or ""
        status_str = "PASSED" if result.status == "SUCCESS" else "FAILED"

        results_summary.append({
            "task": t["task"][:100],
            "category": t["category"],
            "status": status_str,
        })

        if result.status == "SUCCESS":
            passed += 1
            print(f"  PASSED (stage: {result.stage})")
            commit_items.append((t["task"], t["category"], final_code))
        else:
            failed += 1
            print(f"  FAILED (stage: {result.stage})")

    print("\n" + "=" * 60)
    print(f"Results: {passed} passed, {failed} failed out of {len(tasks)}")

    if repo_push and commit_items:
        _batch_commit_and_pr(config, commit_items, results_summary)

    return 0 if failed == 0 else 1


def _commit_and_pr(config, task, category, code, results_summary):
    """Commit a single result and create a PR."""
    notify = lambda s, m: print(f"  [{s}] {m}")
    llm = LLMClient(config)

    repo = RepoManager(
        repo_path=config.git.repo_path,
        repo_url=config.git.repo_url,
        repo_branch=config.git.repo_branch,
        repo_token=config.git.repo_token,
        repo_user=config.git.repo_user,
        notify=notify,
    )
    if not repo.ensure_ready():
        print("Git repository not ready")
        return

    import uuid
    branch = f"examples/cli-{uuid.uuid4().hex[:8]}"
    repo.setup_pr_branch(branch)

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
    committer.commit_code(task, category, code)
    committer.batch_commit_and_push()

    pr_manager = PRManager(config, repo, notify=notify, llm_client=llm)
    pr_url = pr_manager.create_pull_request(results_summary)
    if pr_url:
        print(f"\nPR created: {pr_url}")


def _batch_commit_and_pr(config, commit_items, results_summary):
    """Batch commit multiple results and create a PR."""
    notify = lambda s, m: print(f"  [{s}] {m}")
    llm = LLMClient(config)

    repo = RepoManager(
        repo_path=config.git.repo_path,
        repo_url=config.git.repo_url,
        repo_branch=config.git.repo_branch,
        repo_token=config.git.repo_token,
        repo_user=config.git.repo_user,
        notify=notify,
    )
    if not repo.ensure_ready():
        print("Git repository not ready")
        return

    import uuid
    branch = f"examples/cli-batch-{uuid.uuid4().hex[:8]}"
    repo.setup_pr_branch(branch)

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

    for task, category, code in commit_items:
        committer.commit_code(task, category, code)

    committer.batch_commit_and_push()

    pr_manager = PRManager(config, repo, notify=notify, llm_client=llm)
    pr_url = pr_manager.create_pull_request(results_summary)
    if pr_url:
        print(f"\nPR created: {pr_url}")


def main():
    parser = argparse.ArgumentParser(description="Aspose Examples Generator CLI")
    parser.add_argument("--task", type=str, help="Single task to process")
    parser.add_argument("--csv", type=str, help="CSV file with tasks")
    parser.add_argument("--category", type=str, default="", help="Category override (single mode)")
    parser.add_argument("--product", type=str, default="aspose.pdf", help="Product name")
    parser.add_argument("--repo-push", action="store_true", help="Commit results and create PR")
    parser.add_argument("--tfm", type=str, help="Override .NET target framework (e.g., net10.0)")

    args = parser.parse_args()

    if not args.task and not args.csv:
        parser.error("Either --task or --csv is required")

    config = load_config()

    if args.tfm:
        config.build.tfm = args.tfm

    if args.task:
        sys.exit(run_single(config, args.task, args.category, args.product, args.repo_push))
    elif args.csv:
        sys.exit(run_csv(config, args.csv, args.repo_push))


if __name__ == "__main__":
    main()
