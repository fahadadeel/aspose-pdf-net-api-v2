"""
main.py — FastAPI application entry point.

Start with:
    uvicorn main:app --host 0.0.0.0 --port 7103 --reload      # development
    uvicorn main:app --host 0.0.0.0 --port 7103 --workers 1   # production

Always use --workers 1.
BUILD_STATE and JOB_CANCEL_FLAGS are in-process dicts.
Multiple workers would give each process its own copy.
"""

import os
from contextlib import asynccontextmanager

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

load_dotenv()

from routers import categories, files, tasks, health, results
from routers import jobs as jobs_router
from routers import ui


def _prewarm_models():
    """Pre-load the SentenceTransformer model at startup."""
    rules_path = os.getenv("RULES_EXAMPLES_PATH")
    if not rules_path:
        return
    try:
        from sentence_transformers import SentenceTransformer
        SentenceTransformer("all-MiniLM-L6-v2")
        print("Sentence-transformer model pre-loaded")
    except Exception as exc:
        print(f"Model pre-warm skipped: {exc}")


@asynccontextmanager
async def lifespan(app: FastAPI):
    print("Starting Examples Generator API...")
    _prewarm_models()
    yield
    print("Shutting down")


app = FastAPI(
    title="Aspose Examples Generator",
    description="Automated code generation and testing pipeline.",
    version="2.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET", "POST", "DELETE"],
    allow_headers=["*"],
)

app.include_router(ui.router)
app.include_router(results.router)
app.include_router(health.router)
app.include_router(categories.router)
app.include_router(jobs_router.router)
app.include_router(files.router)
app.include_router(tasks.router)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=int(os.getenv("UI_PORT", "7103")),
        reload=True,
    )
