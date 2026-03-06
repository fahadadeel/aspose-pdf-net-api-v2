"""
routers/ui.py — Serves the Build Monitor HTML UI.
"""

from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from config import load_config

router = APIRouter()
templates = Jinja2Templates(directory=str(Path(__file__).resolve().parent.parent / "templates"))


@router.get("/", response_class=HTMLResponse)
async def index(request: Request):
    cfg = load_config()
    default_api_url = cfg.mcp.generate_url

    repo_url = cfg.git.repo_url
    repo_branch = cfg.git.repo_branch
    repo_display = ""
    if repo_url:
        repo_display = (
            repo_url.rstrip("/").removesuffix(".git").split("github.com/")[-1]
            if "github.com" in repo_url
            else repo_url
        )

    return templates.TemplateResponse(
        "index.html",
        {
            "request": request,
            "default_api_url": default_api_url,
            "repo_display": repo_display,
            "repo_branch": repo_branch,
        },
    )
