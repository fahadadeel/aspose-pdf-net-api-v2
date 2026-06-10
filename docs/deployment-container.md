# Container Deployment

The repo ships a reproducible Docker Compose stack alongside the existing Windows-VM-with-NSSM deployment (documented in [`docs/deployment.md`](./deployment.md)). The compose stack runs the service plus a Prometheus + Grafana sidecar, end to end, on any host with Docker.

> **Operational status:** Production today still runs on the Windows VM under NSSM. The container stack is the **reproducible alternative** — used for testing, staging, and as the migration path for future container-orchestrated environments. Both deployments produce identical service behaviour because they share `requirements.txt` and the same source tree.

## What's in the stack

| Container | Image | Port | Purpose |
|-----------|-------|------|---------|
| `app` | `aspose-pdf-api-v2:latest` (built from `Dockerfile`) | `7103` | The Examples Generator service |
| `prometheus` | `prom/prometheus:v3.0.1` | `9090` | Scrapes `app:7103/api/metrics/prometheus` every 30s |
| `grafana` | `grafana/grafana:11.3.1` | `3000` | Auto-provisioned with the Prometheus datasource and dashboards from [`docs/grafana/`](./grafana/) |

All three live on a private compose network (`aspose-net`); only the published ports (`7103`, `9090`, `3000`) are reachable from the host.

## Prerequisites

- Docker Engine 25.0+ (or Docker Desktop 4.30+)
- Docker Compose v2 (`docker compose` — note the space, not the deprecated `docker-compose`)
- ~4 GB of free disk for the image (sentence-transformers + .NET SDK base layer)
- `.env` file at the repo root with secrets (see [`.env.example`](../.env.example))

## Quick start

```bash
# From the repo root
cp .env.example .env
# Edit .env — fill in LITELLM_API_KEY, REPO_TOKEN, etc.

docker compose -f compose.production.yaml up --build
```

Once healthy (~60s for first boot — sentence-transformers warm-up):

| URL | What you'll see |
|-----|------------------|
| http://localhost:7103 | Build Monitor UI |
| http://localhost:7103/api/health/ready | Per-dependency deep health check |
| http://localhost:7103/api/metrics/prometheus | Prometheus scrape target |
| http://localhost:9090 | Prometheus UI — confirm the `app` target is `UP` under Status → Targets |
| http://localhost:3000 | Grafana — default login `admin / admin`, dashboard pre-loaded under **Dashboards → Aspose → Aspose PDF API v2 — Overview** |

## Persistent state

The compose file bind-mounts three directories from the host so service state survives container restarts:

| Host path | Container path | What lives there |
|-----------|----------------|------------------|
| `./results/` | `/app/results` | Disk-backed per-version task results (`_VERSION: 3` schema) |
| `./resources/` | `/app/resources` | Knowledge base + auto-learned rules (read+write) |
| `./logs/` | `/app/logs` | Service stdout / stderr capture |

In addition, Prometheus and Grafana keep their own state in named Docker volumes (`prometheus-data`, `grafana-data`) so dashboards and metric history survive `down`/`up` cycles.

> ⚠️ **Do not** delete `./resources/auto_*.json` while the stack is running — the pipeline appends to those files continuously. If you need a clean slate, stop the stack first.

## Environment configuration

All env vars documented in [`.claude/rules/env-vars.md`](../.claude/rules/env-vars.md) work identically under compose. Three deserve special note:

| Variable | Default in compose | Why it changes here |
|----------|--------------------|---------------------|
| `CORS_ORIGINS` | `http://localhost:7103,http://prometheus:9090,http://grafana:3000` | Compose sets this so Prometheus and Grafana can hit the service across the internal network. For external access via reverse proxy, override in `.env`. |
| `REPO_PATH` | (must be set in `.env`) | Points at the local clone of the examples repo. On the host this might be `/home/.../agentic-net-examples`; inside the container it's whatever you bind-mount. |
| `GRAFANA_ADMIN_USER` / `GRAFANA_ADMIN_PASSWORD` | `admin` / `admin` | Change these in `.env` before running publicly. |

## Health checks

Both the Dockerfile and compose.production.yaml define a container-level `HEALTHCHECK` that hits `/api/health/ready` every 30 seconds. Compose will mark the container `unhealthy` when:

- the deep health check returns 503 (any dependency unhealthy)
- the endpoint itself doesn't respond within 10 seconds

Wire this into an orchestrator's restart policy (Kubernetes liveness probe, Nomad `check`, etc.) as appropriate. The `restart: unless-stopped` policy in the compose file restarts the container on crashes but not after a manual `docker compose stop`.

## Updating the dashboard JSON

Dashboards are mounted **read-only** from `docs/grafana/` into Grafana. The `updateIntervalSeconds: 30` setting in [`deploy/grafana/dashboards.yaml`](../deploy/grafana/dashboards.yaml) tells Grafana to re-scan that directory every 30 seconds. So:

1. Edit and commit a dashboard JSON file under `docs/grafana/`
2. `docker compose -f compose.production.yaml restart grafana` (or wait 30s)
3. The new dashboard appears in the **Aspose** folder

UI edits inside Grafana are disabled (`editable: false`) — the JSON is the source of truth.

## Image build details

The production image is single-stage and ~2.5 GB built. Layers ordered for cache friendliness:

1. Base: `mcr.microsoft.com/dotnet/sdk:10.0`
2. Python 3.12 + venv
3. `pip install -r requirements.txt` (the slow layer — cached unless `requirements.txt` changes)
4. App source

If you need a smaller image, the next step is a multi-stage build that copies only `/opt/venv`, the compiled `*.pyc` bytecode, and the app sources into a slim runtime stage. Not done by default because the size is dominated by the .NET SDK (~1.3 GB) which is needed at runtime for `dotnet build`.

## Comparison with the Windows VM deployment

| | Windows VM (NSSM) | Docker Compose |
|---|-------------------|----------------|
| Service identity | NSSM service `AsposePdfApi` | Container `aspose-pdf-api-v2` |
| Start / stop | `nssm start AsposePdfApi` | `docker compose up / down` |
| Logs | `logs/service.log` (file) | `docker compose logs -f app` |
| Restart on crash | NSSM `AppExit Default Restart` | `restart: unless-stopped` |
| State location | `C:\fahad\aspose-pdf-net-api-v2\results\` | `./results/` (bind-mounted) |
| Health endpoint | Same (`:7103/api/health/ready`) | Same |
| Monitoring | None (manual) | Prometheus + Grafana included |

Both deployments use the same `requirements.txt` and pass the same tests, so behaviour is identical. The compose stack is **strictly additive** — it never changes how the Windows VM runs.

## Migration path

If you ever want to move production off Windows VM + NSSM onto containers:

1. **Test the compose stack on staging** for one release cycle to confirm parity
2. **Backup `./results/` and `./resources/auto_*.json`** from the Windows VM
3. **Copy the backups to the new host** under the same bind-mount paths
4. **Start the compose stack** — the service finds the existing state and continues from where the Windows VM left off (results are versioned; auto-learned rules are append-only)
5. **Cut over DNS / load balancer** to the new host
6. **Decommission the Windows VM** after one full release cycle of clean operation

The persistence layer (`persistence.py`) and rule files are deployment-agnostic — there's no migration to write.

## Troubleshooting

| Symptom | Likely cause | Fix |
|---------|--------------|-----|
| `app` container restarts every ~60s | `/api/health/ready` returns 503 — a dependency probe fails | Hit the URL directly: `curl http://localhost:7103/api/health/ready \| jq` and look at which `checks.*` is unhealthy |
| Prometheus shows `app` target as `DOWN` | `app` is healthy but unreachable from the prometheus container | Check the network: `docker compose -f compose.production.yaml exec prometheus wget -O- http://app:7103/api/metrics/prometheus` |
| Grafana dashboard empty / "No data" | Datasource misconfigured or no scrapes yet | Hit Prometheus UI at 9090 → Status → Targets; if `UP` but Grafana is empty, recreate the datasource: `docker compose restart grafana` |
| `pip install` fails on build | Likely a network proxy or DNS issue inside the build context | Try `docker build --network host -t aspose-pdf-api-v2:latest .` and re-run compose |
| `dotnet build` errors at runtime | The .NET SDK in the image is wrong version | Check `docker compose exec app dotnet --version`; should be `10.0.x` |

For incidents that don't match these, see [`docs/runbook.md`](./runbook.md).
