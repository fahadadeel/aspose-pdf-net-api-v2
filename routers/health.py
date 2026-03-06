"""
routers/health.py — GET /api/health
"""

from fastapi import APIRouter

router = APIRouter()


@router.get("/api/health")
async def health():
    return {"status": "ok", "service": "aspose-examples-generator"}
