"""
routers/results.py — Serves the standalone Results Dashboard UI.
"""

from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from config import load_config

router = APIRouter()
templates = Jinja2Templates(directory=str(Path(__file__).resolve().parent.parent / "templates"))


@router.get("/results", response_class=HTMLResponse)
async def results_page(request: Request):
    cfg = load_config()
    pr_target_branch = cfg.git.pr_target_branch or ""
    nuget_version = cfg.build.nuget_version

    return templates.TemplateResponse(
        request=request,
        name="results.html",
        context={
            "pr_target_branch": pr_target_branch,
            "nuget_version": nuget_version,
        },
    )


@router.get("/results-v2", response_class=HTMLResponse)
async def results_v2_page(request: Request):
    """Redesigned Results Dashboard (v2)."""
    cfg = load_config()
    pr_target_branch = cfg.git.pr_target_branch or ""
    nuget_version = cfg.build.nuget_version

    return templates.TemplateResponse(
        request=request,
        name="results-v2.html",
        context={
            "pr_target_branch": pr_target_branch,
            "nuget_version": nuget_version,
        },
    )
