# Observability

The service exposes two telemetry surfaces:

| Surface | Path | Format | Purpose |
|---------|------|--------|---------|
| **Dashboard JSON** | `GET /api/metrics` | application/json | Build Monitor UI, ad-hoc curl, simple status pages |
| **Prometheus scrape** | `GET /api/metrics/prometheus` | text/plain (Prometheus exposition) | Prometheus / VictoriaMetrics / Mimir / Thanos scraping for Grafana / Alertmanager |
| **Deep health check** | `GET /api/health/ready` | application/json | Per-dependency status (MCP, LLM, disk, dotnet, REPO_PATH) for liveness + readiness probes |
| **Lightweight health** | `GET /api/health` | application/json | Single-shot "is the process alive" for load balancers |

All four are **public** — they don't require the `API_KEY` even when one is configured (standard practice for monitoring endpoints).

## Wire up Prometheus

Add a scrape job to your Prometheus config (`prometheus.yml`):

```yaml
scrape_configs:
  - job_name: aspose-pdf-api-v2
    metrics_path: /api/metrics/prometheus
    scrape_interval: 30s
    scrape_timeout: 10s
    static_configs:
      - targets: ["host:7103"]
        labels:
          service: aspose-pdf-api-v2
          env: production    # change per environment
```

Reload Prometheus (`SIGHUP` or `/-/reload`). The service should appear as **UP** within one scrape interval.

## Wire up Grafana

1. In Grafana, **Dashboards → New → Import**
2. Upload [`docs/grafana/aspose-pdf-api-v2-overview.json`](./grafana/aspose-pdf-api-v2-overview.json) (or paste its contents)
3. Pick your Prometheus datasource for the `DS_PROMETHEUS` variable
4. Click **Import**

The dashboard has six panels:

| # | Panel | Metric / Query |
|---|-------|----------------|
| 1 | Service uptime | `service_uptime_seconds` |
| 2 | Active pipeline jobs | `pipeline_jobs_active` |
| 3 | Examples processed (rate, by outcome) | `sum by (outcome) (rate(pipeline_examples_total[5m]))` |
| 4 | HTTP request rate (by status code) | `sum by (code) (rate(http_requests_total[5m]))` |
| 5 | HTTP latency p50 / p95 / p99 | `histogram_quantile(.5, sum by (le) (rate(http_request_duration_seconds_bucket[5m])))` etc. |
| 6 | Pipeline jobs by final status (rate) | `sum by (final_status) (rate(pipeline_jobs_total[5m]))` |

## Metrics reference

### Service health

| Metric | Type | Labels | Notes |
|--------|------|--------|-------|
| `service_uptime_seconds` | gauge | — | Refreshed on every scrape |

### Pipeline

| Metric | Type | Labels | Notes |
|--------|------|--------|-------|
| `pipeline_jobs_active` | gauge | — | In-flight pipeline jobs |
| `pipeline_jobs_total` | counter | `final_status` | Increments only on terminal states (`completed`, `done`, `failed`, `cancelled`) — typos in `set_status()` won't blow up cardinality |
| `pipeline_examples_total` | counter | `outcome` | `outcome ∈ {passed, failed}` |

### HTTP layer

| Metric | Type | Labels | Notes |
|--------|------|--------|-------|
| `http_requests_total` | counter | `method, path, code` | `path` is the route TEMPLATE (e.g. `/api/status/{job_id}`), not the rendered URL — bounded cardinality |
| `http_request_duration_seconds` | histogram | `method, path` | Buckets tuned for fast JSON APIs (5ms → 10s). SSE streams measured as time-to-first-byte, not stream lifetime |

## Suggested alert rules

Drop into `prometheus-alerts.yml` (adjust thresholds to your traffic):

```yaml
groups:
  - name: aspose-pdf-api-v2
    interval: 30s
    rules:
      - alert: ServiceDown
        expr: up{job="aspose-pdf-api-v2"} == 0
        for: 2m
        labels:
          severity: P1
        annotations:
          summary: "Examples Generator is unreachable"
          runbook: "https://gitlab.recruitize.ai/sialkot/faisalabad-openize/aspose-pdf-net-api-v2/-/blob/main/docs/runbook.md"

      - alert: HighErrorRate
        expr: |
          (
            sum(rate(http_requests_total{code=~"5.."}[5m]))
            /
            sum(rate(http_requests_total[5m]))
          ) > 0.05
        for: 5m
        labels:
          severity: P2
        annotations:
          summary: "5xx error rate above 5% for 5 minutes"

      - alert: PipelineFailureRateHigh
        expr: |
          (
            sum(rate(pipeline_examples_total{outcome="failed"}[15m]))
            /
            sum(rate(pipeline_examples_total[15m]))
          ) > 0.30
        for: 15m
        labels:
          severity: P2
        annotations:
          summary: "Pipeline failure rate above 30% for 15 minutes — check MCP/LLM/dotnet health"

      - alert: NoActivity
        expr: sum(rate(pipeline_examples_total[30m])) == 0 and pipeline_jobs_active > 0
        for: 30m
        labels:
          severity: P3
        annotations:
          summary: "Pipeline job active for 30+ min with zero example throughput — likely stuck"

      - alert: P99LatencyHigh
        expr: histogram_quantile(0.99, sum by (le) (rate(http_request_duration_seconds_bucket[5m]))) > 2
        for: 10m
        labels:
          severity: P3
        annotations:
          summary: "P99 HTTP latency above 2s for 10 minutes"
```

The runbook annotations should point at [`docs/runbook.md`](./runbook.md) — paths already wired up to expect this.

## Local Prometheus + Grafana stack

For developers who want to see the dashboard locally before shipping to production:

```yaml
# compose.observability.yaml — run alongside the service
services:
  prometheus:
    image: prom/prometheus:latest
    volumes:
      - ./prometheus.yml:/etc/prometheus/prometheus.yml:ro
    ports: ["9090:9090"]

  grafana:
    image: grafana/grafana:latest
    environment:
      - GF_SECURITY_ADMIN_PASSWORD=admin
    volumes:
      - ./docs/grafana:/etc/grafana/provisioning/dashboards:ro
    ports: ["3000:3000"]
```

Start with `docker compose -f compose.observability.yaml up`, open `http://localhost:3000` (admin/admin), import the dashboard JSON.

## Tracing — out of scope

This service intentionally does **not** wire OpenTelemetry / Jaeger / Tempo. The pipeline stages already log per-stage progress to job state via `add_log()`, which the Build Monitor renders as a per-job timeline. If distributed tracing becomes a need, the right hook point is the existing stage boundaries in `pipeline/runner.py`; the `prometheus-client` library is on the dependency tree so adding `opentelemetry-api` later is straightforward.

## What the deep health check does NOT cover

`GET /api/health/ready` does **not** verify:

- That the MCP server can actually generate code (it just checks the server root responds)
- That the LLM proxy can complete an LLM call (it just lists models)
- That git operations against `aspose-pdf/agentic-net-examples` will succeed (token validation costs an API call and would be noisy on rate limits)

These are intentional trade-offs — the health check has a < 6-second total budget. For end-to-end verification, the `scripts/verify_passed.py` post-build script and the `validate-pr.yml` workflow in the examples repo do the deep validation. Production monitoring should rely on the **failure-rate alert** above, which catches "MCP/LLM is responding but producing broken code" through its downstream impact on `pipeline_examples_total{outcome="failed"}`.
