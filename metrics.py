"""
metrics.py -- Prometheus metric definitions for /api/metrics/prometheus.

Counters and gauges declared here are imported by:
    state.py   -- increments JOBS_ACTIVE / JOBS_TOTAL / EXAMPLES_PROCESSED
    main.py    -- HTTP request middleware increments REQUESTS_TOTAL +
                  observes REQUEST_DURATION
    routers/health.py -- serves the prometheus text format

Metric names follow Prometheus conventions:
    - snake_case
    - unit suffix on counters/histograms when the unit isn't obvious
    - `_total` suffix for counter metrics
"""

from prometheus_client import Counter, Gauge, Histogram

# ── Process / service-level ────────────────────────────────────────────────

UPTIME_SECONDS = Gauge(
    "service_uptime_seconds",
    "Seconds since the service process started.",
)

# ── Pipeline job lifecycle ─────────────────────────────────────────────────

JOBS_ACTIVE = Gauge(
    "pipeline_jobs_active",
    "Number of pipeline jobs currently in flight.",
)

JOBS_TOTAL = Counter(
    "pipeline_jobs_total",
    "Cumulative count of pipeline jobs that reached a terminal status.",
    labelnames=["final_status"],
)

EXAMPLES_PROCESSED = Counter(
    "pipeline_examples_total",
    "Cumulative count of examples processed by the pipeline, by outcome.",
    labelnames=["outcome"],
)

# ── Self-learning convergence ──────────────────────────────────────────────
# These reflect the state of resources/auto_patterns.json. Refreshed on
# every /api/metrics/prometheus scrape so external dashboards can chart
# whether the self-learning loop is converging (hit_rate trending up) or
# producing rules that nothing ever uses (hit_rate flat / falling).

PATTERN_HIT_RATE = Gauge(
    "pipeline_pattern_hit_rate",
    "Fraction of promoted auto-learned patterns that have fired at least once (0.0 to 1.0).",
)

PATTERN_TOTAL = Gauge(
    "pipeline_pattern_total",
    "Number of promoted auto-learned patterns currently stored.",
)

PATTERN_HITS = Counter(
    "pipeline_pattern_hits_total",
    "Cumulative auto-learned pattern firings since process start. Not "
    "the same as the on-disk hit_count — this is a process-lifetime "
    "counter that resets when the service restarts, useful for "
    "rate() queries in Prometheus.",
)

# ── HTTP layer ─────────────────────────────────────────────────────────────

REQUESTS_TOTAL = Counter(
    "http_requests_total",
    "Cumulative HTTP requests handled by the service.",
    labelnames=["method", "path", "code"],
)

REQUEST_DURATION = Histogram(
    "http_request_duration_seconds",
    "End-to-end HTTP request duration in seconds.",
    labelnames=["method", "path"],
    # Buckets tuned for a fast JSON API; SSE streams will land in +Inf.
    buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0),
)

# Terminal job statuses we want to count separately. set_status() with any
# other value won't emit a counter increment (avoids cardinality explosion
# from typos / new statuses).
_TERMINAL_STATUSES = frozenset({"completed", "done", "failed", "cancelled"})


def is_terminal_status(status: str) -> bool:
    """Return True if the given status counts as a terminal job state."""
    return status in _TERMINAL_STATUSES
