# Production image for the Aspose PDF Examples Generator service.
# Single-stage layout matches Dockerfile.ci for parity; the production
# image includes the full requirements.txt (sentence-transformers, scipy,
# numpy) which the CI image deliberately omits.
#
# Built and run via:
#   docker compose -f compose.production.yaml up --build
#
# Single worker is mandatory: in-memory BUILD_STATE is not shared between
# processes. Horizontal scaling is not supported.

FROM mcr.microsoft.com/dotnet/sdk:10.0

# ── Python 3.12 toolchain ────────────────────────────────────────────────────
RUN apt-get update && apt-get install -y --no-install-recommends \
    python3.12 \
    python3.12-venv \
    git \
    curl \
    && rm -rf /var/lib/apt/lists/*

RUN update-alternatives --install /usr/bin/python3 python3 /usr/bin/python3.12 1 \
 && update-alternatives --install /usr/bin/python python /usr/bin/python3.12 1

# Use a venv so we never touch the Debian system Python
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /app

# ── Python dependencies (cached layer) ───────────────────────────────────────
COPY requirements.txt .
RUN pip install --upgrade pip && pip install --no-cache-dir -r requirements.txt

# ── App source ───────────────────────────────────────────────────────────────
COPY . .

# ── Runtime configuration ────────────────────────────────────────────────────
EXPOSE 7103

# Built-in healthcheck — uses the deep health endpoint added in R-A so
# compose / orchestrators can mark the container unhealthy when MCP / LLM
# / disk / dotnet are degraded. 60s start period covers cold-start of
# sentence-transformers + tokenizer download.
HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=3 \
    CMD curl -fsS http://localhost:7103/api/health/ready > /dev/null || exit 1

# CRITICAL: --workers 1. BUILD_STATE is in-memory and not shared across
# worker processes — multiple workers would silently lose jobs. See
# CONTRIBUTING.md "Key Constraints" for details.
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "7103", "--workers", "1"]
