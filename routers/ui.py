"""
routers/ui.py -- Serves the Build Monitor HTML UI.
"""

import os
from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from config import load_config

router = APIRouter()
templates = Jinja2Templates(directory=str(Path(__file__).resolve().parent.parent / "templates"))


def _api_key_for_ui() -> str:
    """Return the API_KEY env var so templates can embed it for fetch calls.

    The UI is served behind VPN; embedding the key lets browser-driven
    write actions (Create PR, Update README, etc.) work without manual
    auth, while CI and other external callers still gate through the
    same key. When API_KEY is unset (dev), this returns an empty string
    and the UI behaves identically to before — no header sent.
    """
    return os.getenv("API_KEY", "")


@router.get("/", response_class=HTMLResponse)
async def index(request: Request):
    cfg = load_config()
    default_api_url = cfg.mcp.generate_url

    repo_url = cfg.git.repo_url
    repo_branch = cfg.git.repo_branch
    pr_target_branch = cfg.git.pr_target_branch or ""
    repo_display = ""
    if repo_url:
        repo_display = (
            repo_url.rstrip("/").removesuffix(".git").split("github.com/")[-1]
            if "github.com" in repo_url
            else repo_url
        )

    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context={
            "default_api_url": default_api_url,
            "repo_display": repo_display,
            "repo_branch": repo_branch,
            "pr_target_branch": pr_target_branch,
            "nuget_version": cfg.build.nuget_version,
            "api_key": _api_key_for_ui(),
        },
    )
