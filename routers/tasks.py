"""
routers/tasks.py — GET /api/tasks

Proxy to external task-listing API.
"""

import requests
from fastapi import APIRouter

from config import load_config

router = APIRouter()

_EMPTY = {"items": [], "total": 0, "page": 1, "page_size": 50, "total_pages": 0}


@router.get("/api/tasks")
def api_tasks(
    product: str = "aspose.pdf",
    category: str = "",
    page: int = 1,
    page_size: int = 50,
):
    """Fetch tasks for a given category from the external API."""
    cfg = load_config()

    if not cfg.tasks_api_url:
        return _EMPTY

    try:
        response = requests.get(
            cfg.tasks_api_url,
            params={
                "product": product,
                "category": category,
                "page": page,
                "page_size": page_size,
            },
            timeout=10,
        )
        if response.status_code == 200:
            return response.json()
        return _EMPTY
    except Exception:
        return _EMPTY
