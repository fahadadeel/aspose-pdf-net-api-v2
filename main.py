"""
main.py -- FastAPI application entry point.

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
from fastapi_mcp import FastApiMCP

load_dotenv()

from routers import categories, files, tasks, health, results
from routers import jobs as jobs_router
from routers import ui
from middleware.security import SecurityHeadersMiddleware, APIKeyMiddleware


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

_cors_env = os.getenv("CORS_ORIGINS", "")
_allowed_origins = (
    [o.strip() for o in _cors_env.split(",") if o.strip()]
    if _cors_env
    else ["http://localhost:7103", "http://127.0.0.1:7103"]
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=_allowed_origins,
    allow_methods=["GET", "POST", "DELETE"],
    allow_headers=["*"],
)
app.add_middleware(SecurityHeadersMiddleware)
app.add_middleware(APIKeyMiddleware)


@app.middleware("http")
async def _prometheus_request_middleware(request, call_next):
    """Record per-request metrics: count and end-to-end duration.

    Safe for streaming responses (SSE): we never iterate ``response.body``
    or buffer the response. We only record AFTER ``call_next`` returns.
    For SSE the response is returned immediately (status set, headers
    written) — the stream runs from a background generator. The duration
    captured here is therefore "time to first byte" for SSE, not the
    lifetime of the stream. That's what we want — streams can run for
    hours and we don't want unbounded histogram values.
    """
    import time as _t

    from metrics import REQUEST_DURATION, REQUESTS_TOTAL

    method = request.method
    start = _t.monotonic()
    code = "500"
    try:
        response = await call_next(request)
        code = str(response.status_code)
        return response
    finally:
        duration = _t.monotonic() - start
        # Route is populated by Starlette during dispatch, so we can read
        # the route template (e.g. /api/status/{job_id}) here AFTER the
        # call to avoid cardinality explosion on dynamic path segments.
        route = request.scope.get("route")
        path = route.path if route is not None else request.url.path
        try:
            REQUESTS_TOTAL.labels(method=method, path=path, code=code).inc()
            REQUEST_DURATION.labels(method=method, path=path).observe(duration)
        except Exception:
            pass


app.include_router(ui.router)
app.include_router(results.router)
app.include_router(health.router)
app.include_router(categories.router)
app.include_router(jobs_router.router)
app.include_router(files.router)
app.include_router(tasks.router)

# MCP server — exposes pipeline endpoints as standard MCP tools.
# Any MCP-compatible client can connect at /mcp (SSE transport).
# SSE stream and UI routes are excluded since they don't fit the request/response tool model.
mcp = FastApiMCP(
    app,
    name="Aspose Examples Generator",
    description=(
        "Controls the Aspose PDF .NET examples generation pipeline. "
        "Start and monitor code generation jobs, manage PRs, "
        "browse results, and trigger repo operations."
    ),
    exclude_operations=[
        "index__get",                             # HTML Build Monitor page
        "results_page_results_get",               # HTML Results page
        "results_v2_page_results_v2_get",         # HTML Results v2 page
        "api_stream_api_stream__job_id__get",     # SSE stream — push-only, not a tool
        "api_start_sweep_api_start_sweep_post",   # Deprecated, redirects to start-tasks
    ],
)
mcp.mount()


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=int(os.getenv("UI_PORT", "7103")),
        reload=True,
    )
