"""
routers/categories.py — GET /api/categories
"""

import requests
from fastapi import APIRouter

from config import load_config

router = APIRouter()

_FALLBACK_CATEGORIES = ["uncategorized", "Facades - AcroForms", "Basic Operations"]


@router.get("/api/categories")
def api_categories(product: str = "aspose.pdf"):
    """Fetch categories from external API with fallback."""
    cfg = load_config()

    if not cfg.categories_api_url:
        return {"categories": _FALLBACK_CATEGORIES, "source": "fallback"}

    try:
        response = requests.get(
            cfg.categories_api_url,
            params={"product": product},
            timeout=5,
        )
        if response.status_code == 200:
            categories = response.json()
            if isinstance(categories, list) and len(categories) > 0:
                return {"categories": categories, "source": "api"}
        return {"categories": _FALLBACK_CATEGORIES, "source": "fallback"}
    except Exception:
        return {"categories": _FALLBACK_CATEGORIES, "source": "fallback"}
