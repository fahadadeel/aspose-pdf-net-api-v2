"""
routers/jobs.py — Job management endpoints + SSE streaming.

POST /api/start
POST /api/start-tasks
GET  /api/status/{job_id}
GET  /api/stream/{job_id}   (SSE)
POST /api/cancel/{job_id}
POST /api/retry-pr/{job_id}
POST /api/update-repo-docs
GET  /api/repo-categories
POST /api/generate-category-docs
POST /api/generate-index-json
"""

import asyncio
import csv as csv_module
import io
import json
import threading
import uuid

from fastapi import APIRouter, Body, File, Form, UploadFile
from fastapi.responses import JSONResponse, StreamingResponse

from jobs import run_job, retry_pr, create_pr, update_repo_docs
from state import (
    JOB_CANCEL_FLAGS, JOB_LOCK,
    get_build_state, add_log,
    register_listener, unregister_listener,
)

router = APIRouter()

_FINISHED_STATUSES = frozenset({"completed", "failed", "cancelled"})


@router.post("/api/start")
async def api_start(
    mode: str = Form(...),
    prompt: str = Form(None),
    category: str = Form(None),
    product: str = Form("aspose.pdf"),
    repo_push: str = Form(""),
    force: str = Form("false"),
    api_url: str = Form(None),
    csv: UploadFile = File(None),
):
    if mode not in {"single", "csv"}:
        return JSONResponse({"error": "Invalid mode"}, status_code=400)

    repo_push_bool = repo_push.lower() == "true"
    force_bool = force == "true"
    job_id = str(uuid.uuid4())

    if mode == "single":
        prompt = (prompt or "").strip()
        category = (category or "").strip()
        product = (product or "aspose.pdf").strip() or "aspose.pdf"

        if not prompt:
            return JSONResponse({"error": "Prompt is required"}, status_code=400)

        thread = threading.Thread(
            target=run_job,
            args=(job_id, mode, prompt),
            kwargs={
                "category": category,
                "product": product,
                "repo_push": repo_push_bool,
                "force": force_bool,
                "api_url": api_url or None,
            },
            daemon=True,
        )
        thread.start()
        return {"job_id": job_id}

    # CSV mode
    if not csv or not csv.filename:
        return JSONResponse({"error": "CSV file is required"}, status_code=400)

    content = await csv.read()
    text = content.decode("utf-8-sig")
    reader = csv_module.DictReader(io.StringIO(text))
    prompts = []
    for row in reader:
        task = row.get("task") or row.get("prompt") or ""
        if task.strip():
            prompts.append({
                "prompt": task.strip(),
                "category": (row.get("category") or "").strip(),
                "product": (row.get("product") or "aspose.pdf").strip(),
            })

    if not prompts:
        return JSONResponse({"error": "CSV contains no valid prompts"}, status_code=400)

    thread = threading.Thread(
        target=run_job,
        args=(job_id, "csv"),
        kwargs={
            "prompts": prompts,
            "repo_push": repo_push_bool,
            "force": force_bool,
            "api_url": api_url or None,
        },
        daemon=True,
    )
    thread.start()
    return {"job_id": job_id}


@router.post("/api/start-tasks")
async def api_start_tasks(data: dict = Body(...)):
    """Start a job from selected tasks (Task Generator mode)."""
    tasks = data.get("tasks", [])
    repo_push = data.get("repo_push", False)
    force = data.get("force", False)
    api_url = data.get("api_url") or None

    if not tasks:
        return JSONResponse({"error": "No tasks selected"}, status_code=400)

    job_id = str(uuid.uuid4())

    prompts = []
    for task in tasks:
        if isinstance(task, str):
            task = {"task": task}
        prompt_text = task.get("task", "").strip()
        if prompt_text:
            prompts.append({
                "prompt": prompt_text,
                "category": (task.get("category") or "").strip(),
                "product": (task.get("product") or "aspose.pdf").strip(),
                "id": task.get("id", ""),
            })

    if not prompts:
        return JSONResponse({"error": "No valid tasks found"}, status_code=400)

    thread = threading.Thread(
        target=run_job,
        args=(job_id, "csv"),
        kwargs={
            "prompts": prompts,
            "repo_push": bool(repo_push),
            "force": bool(force),
            "api_url": api_url,
        },
        daemon=True,
    )
    thread.start()
    return {"job_id": job_id}


@router.get("/api/status/{job_id}")
async def api_status(job_id: str):
    state = get_build_state(job_id)
    if not state:
        return JSONResponse({"error": "Job not found"}, status_code=404)
    return state


@router.get("/api/stream/{job_id}")
async def api_stream(job_id: str):
    """SSE endpoint — pushes build state updates in real time."""
    state = get_build_state(job_id)
    if not state:
        return JSONResponse({"error": "Job not found"}, status_code=404)

    async def event_generator():
        evt = register_listener(job_id)
        last_passed = 0
        last_failed = 0
        last_logs = 0
        try:
            while True:
                current = get_build_state(job_id)
                if not current:
                    break

                new_passed = current["passed"][last_passed:]
                new_failed = current["failed"][last_failed:]
                new_logs = current["logs"][last_logs:]
                last_passed = len(current["passed"])
                last_failed = len(current["failed"])
                last_logs = len(current["logs"])

                payload = {
                    "status": current["status"],
                    "total": current["total"],
                    "processed": current["processed"],
                    "passed_count": current["passed_count"],
                    "failed_count": current["failed_count"],
                    "pass_rate": current["pass_rate"],
                    "elapsed": current["elapsed"],
                    "current_task": current["current_task"],
                    "new_passed": new_passed,
                    "new_failed": new_failed,
                    "new_logs": new_logs,
                    "pr_url": current.get("pr_url", ""),
                }
                yield f"data: {json.dumps(payload, default=str)}\n\n"

                if current["status"] in _FINISHED_STATUSES:
                    yield f"event: done\ndata: {json.dumps({'status': current['status']})}\n\n"
                    break

                evt.clear()
                try:
                    await asyncio.wait_for(
                        asyncio.get_event_loop().run_in_executor(None, evt.wait, 5.0),
                        timeout=6.0,
                    )
                except asyncio.TimeoutError:
                    pass
        finally:
            unregister_listener(job_id, evt)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.post("/api/retry-pr/{job_id}")
async def api_retry_pr(job_id: str):
    """Create or re-create a PR for already-generated examples.

    If a PR branch already exists (job ran with repo_push=true), uses retry_pr
    to recover files from the old branch. Otherwise uses create_pr to commit
    the code stored in the passed results directly.
    """
    state = get_build_state(job_id)
    if not state:
        return JSONResponse({"error": "Job not found"}, status_code=404)
    if state["status"] == "running":
        return JSONResponse({"error": "Job is still running"}, status_code=400)

    passed_results = state.get("passed", [])
    results_summary = state.get("results_summary", [])

    if not passed_results:
        return JSONResponse({"error": "No passed results to create PR from"}, status_code=400)

    # Build results_summary from passed/failed if not already stored
    if not results_summary:
        for item in passed_results:
            results_summary.append({
                "task": item.get("task", ""),
                "category": "",
                "status": "PASSED",
            })
        for item in state.get("failed", []):
            results_summary.append({
                "task": item.get("task", ""),
                "category": "",
                "status": "FAILED",
            })

    pr_branch = state.get("pr_branch", "")

    if pr_branch:
        # Job ran with repo_push — retry by recovering from old branch
        thread = threading.Thread(
            target=retry_pr,
            args=(job_id, pr_branch, results_summary),
            daemon=True,
        )
        thread.start()
        return {"status": "retrying", "old_branch": pr_branch}
    else:
        # Job ran without repo_push — fresh commit from in-memory code
        thread = threading.Thread(
            target=create_pr,
            args=(job_id, passed_results, results_summary),
            daemon=True,
        )
        thread.start()
        return {"status": "creating", "mode": "fresh"}


@router.post("/api/cancel/{job_id}")
async def api_cancel(job_id: str):
    state = get_build_state(job_id)
    if not state:
        return JSONResponse({"error": "Job not found"}, status_code=404)
    if state["status"] != "running":
        return JSONResponse({"error": f"Job is already {state['status']}"}, status_code=400)
    with JOB_LOCK:
        JOB_CANCEL_FLAGS[job_id] = True
    add_log(job_id, "Cancellation requested - finishing current task...")
    return {"status": "cancel_requested"}


@router.post("/api/update-repo-docs")
async def api_update_repo_docs(data: dict = Body(None)):
    """Scan the repo and create a PR with cumulative agents.md + optional README update."""
    update_readme = False
    if data:
        update_readme = bool(data.get("update_readme", False))

    job_id = str(uuid.uuid4())

    thread = threading.Thread(
        target=update_repo_docs,
        args=(job_id,),
        kwargs={"update_readme": update_readme},
        daemon=True,
    )
    thread.start()
    return {"job_id": job_id}


@router.get("/api/repo-categories")
async def api_repo_categories():
    """List all category folders in the repo with their file counts."""
    from config import load_config
    from git_ops.repo_docs import scan_repo

    config = load_config()
    scan = scan_repo(config.git.repo_path)
    return {
        "categories": [
            {"name": cat, "file_count": len(files)}
            for cat, files in sorted(scan.items())
        ]
    }


@router.post("/api/generate-category-docs")
async def api_generate_category_docs(
    data: dict = Body(
        ...,
        examples=[{"category": "working-with-xml", "create_pr": True}],
    ),
):
    """Generate agents.md for a single category and push it via PR.

    Returns the generated agents.md content and PR URL (if create_pr=true).
    """
    from config import load_config
    from git_ops.repo_docs import scan_repo, generate_cumulative_category_agents_md
    from git_ops.github_api import GitHubAPI

    category = data.get("category", "").strip()
    create_pr = data.get("create_pr", True)

    if not category:
        return JSONResponse({"error": "category is required"}, status_code=400)

    config = load_config()

    # Scan the repo to find the category
    scan = scan_repo(config.git.repo_path)

    # Case-insensitive match
    matched_cat = None
    for cat_name in scan:
        if cat_name.lower() == category.lower():
            matched_cat = cat_name
            break

    if not matched_cat:
        return JSONResponse(
            {"error": f"Category '{category}' not found. Available: {sorted(scan.keys())}"},
            status_code=404,
        )

    files = scan[matched_cat]

    # Generate agents.md content
    agents_md = generate_cumulative_category_agents_md(
        matched_cat, files, run_id=None,
        kb_path=config.rules_examples_path,
        repo_path=config.git.repo_path,
        tfm=config.build.tfm,
        nuget_version=config.build.nuget_version,
    )

    result = {
        "category": matched_cat,
        "files": files,
        "agents_md": agents_md,
        "file_count": len(files),
    }

    # Push via GitHub API if requested
    if create_pr and config.git.repo_token:
        gh = GitHubAPI(config.git.repo_token)
        owner, repo_name = GitHubAPI.extract_repo_info(config.git.repo_url)
        base = config.git.repo_branch or "main"

        if not owner or not repo_name:
            result["error"] = "Could not parse repo URL"
            return result

        # Get base branch SHA and create a new branch
        base_sha = gh.get_branch_sha(owner, repo_name, base)
        if not base_sha:
            result["error"] = f"Could not get SHA for branch '{base}'"
            return result

        branch_name = f"docs/category-{matched_cat}-{uuid.uuid4().hex[:6]}"
        if not gh.create_branch(owner, repo_name, branch_name, base_sha):
            result["error"] = "Could not create branch"
            return result

        # Check if file already exists (need SHA for update)
        file_path = f"{matched_cat}/agents.md"
        existing = gh.get_file(owner, repo_name, file_path, base)
        file_sha = existing.get("sha") if existing else None

        # Push the file
        commit_msg = f"Update {matched_cat}/agents.md ({len(files)} examples)"
        if not gh.create_or_update_file(
            owner, repo_name, file_path,
            agents_md, commit_msg, branch_name,
            sha=file_sha,
        ):
            result["error"] = "Could not push agents.md file"
            return result

        # Create PR
        pr_title = f"Update {matched_cat}/agents.md"
        pr_body = (
            f"## Category Documentation Update\n\n"
            f"Updated `agents.md` for **{matched_cat}** category.\n\n"
            f"- **{len(files)}** example(s) in this category\n"
            f"- Category-specific tips from knowledge base\n"
            f"\n---\n*Generated by Examples Generator*"
        )
        pr_url = gh.create_pull_request(owner, repo_name, pr_title, pr_body, branch_name, base)
        result["pr_url"] = pr_url or ""

    return result


@router.post("/api/generate-index-json")
async def api_generate_index_json(
    data: dict = Body(
        default={"create_pr": True},
        examples=[{"create_pr": True}],
    ),
):
    """Generate index.json for the repository and push it via PR.

    Scans the repo, extracts per-category metadata (files, namespaces, key APIs),
    and returns the index.json content. Optionally creates a PR (default: true).
    """
    from config import load_config
    from git_ops.repo_docs import scan_repo, generate_index_json
    from git_ops.github_api import GitHubAPI

    create_pr = data.get("create_pr", True) if data else True
    config = load_config()

    if not config.git.repo_path:
        return JSONResponse({"error": "REPO_PATH not configured"}, status_code=400)

    scan = scan_repo(config.git.repo_path)
    if not scan:
        return JSONResponse({"error": "No categories found in repo"}, status_code=404)

    total = sum(len(files) for files in scan.values())
    index_content = generate_index_json(
        scan,
        tfm=config.build.tfm,
        nuget_version=config.build.nuget_version,
        repo_path=config.git.repo_path,
    )

    # Write to local disk
    from pathlib import Path
    index_path = Path(config.git.repo_path) / "index.json"
    index_path.write_text(index_content, encoding="utf-8")

    result = {
        "total_examples": total,
        "total_categories": len(scan),
        "index_json": json.loads(index_content),
    }

    # Push via GitHub API if requested
    if create_pr and config.git.repo_token:
        gh = GitHubAPI(config.git.repo_token)
        owner, repo_name = GitHubAPI.extract_repo_info(config.git.repo_url)
        base = config.git.repo_branch or "main"

        if not owner or not repo_name:
            result["error"] = "Could not parse repo URL"
            return result

        base_sha = gh.get_branch_sha(owner, repo_name, base)
        if not base_sha:
            result["error"] = f"Could not get SHA for branch '{base}'"
            return result

        branch_name = f"docs/index-json-{uuid.uuid4().hex[:6]}"
        if not gh.create_branch(owner, repo_name, branch_name, base_sha):
            result["error"] = "Could not create branch"
            return result

        # Check if index.json already exists (need SHA for update)
        file_path = "index.json"
        existing = gh.get_file(owner, repo_name, file_path, base)
        file_sha = existing.get("sha") if existing else None

        commit_msg = f"Update index.json ({len(scan)} categories, {total} examples)"
        if not gh.create_or_update_file(
            owner, repo_name, file_path,
            index_content, commit_msg, branch_name,
            sha=file_sha,
        ):
            result["error"] = "Could not push index.json file"
            return result

        pr_title = f"Update index.json ({total} examples)"
        pr_body = (
            f"## Repository Index Update\n\n"
            f"Updated `index.json` — machine-readable manifest of the repository.\n\n"
            f"- **{total}** total examples across **{len(scan)}** categories\n"
            f"- Includes per-category: files, required namespaces, key APIs\n"
            f"\n---\n*Generated by Examples Generator*"
        )
        pr_url = gh.create_pull_request(owner, repo_name, pr_title, pr_body, branch_name, base)
        result["pr_url"] = pr_url or ""

    return result
