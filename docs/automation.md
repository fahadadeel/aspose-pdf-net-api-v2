# Automation

How the service runs autonomously — what triggers it, where the work happens, and what to do when something needs attention.

## Two paths

There are two ways the pipeline can run end-to-end. Both exist in `.gitlab-ci.yml`. They produce identical output (a set of validated C# examples committed to `aspose-pdf/agentic-net-examples`) but differ in where the work happens and where learned state lives.

| | **Path A — runner-side** (`generate-examples` job) | **Path B — VM-side** (`scheduled-sweep` job) ⭐ preferred |
|---|---|---|
| Where the pipeline runs | Inside the GitLab CI runner (fresh container each time) | On the production Windows VM via `/api/start-tasks` |
| Where `auto_fixes.json` / `auto_patterns.json` live | Ephemeral unless explicitly committed back | Persistent on the VM — accumulates across runs |
| Where job state lives | Ephemeral | In-memory `BUILD_STATE` on the VM (visible in Build Monitor UI) |
| Sentence-transformer model | Cold-loaded every run | Stays warm |
| Real-time progress | CI logs only | Build Monitor SSE stream + CI logs |
| When to use | VM is down / one-off experiment | Default for routine runs |

**This document focuses on Path B.** Path A is documented inline in `.gitlab-ci.yml` and kept as a fallback.

## Path B — how it works

```
GitLab Pipeline Schedule (cron)
   │
   ▼
CI runner spawns alpine container
   │
   ├── apk add curl jq bc
   ├── runs scripts/ci/scheduled-sweep.sh
   │      │
   │      ├── 1. GET  $VM_BASE_URL/api/health/ready    (pre-flight)
   │      ├── 2. GET  $VM_BASE_URL/api/categories       (fetch list)
   │      ├── 3. POST $VM_BASE_URL/api/start-tasks      (start sweep)
   │      ├── 4. loop: GET /api/status/$JOB_ID          (poll every 60s)
   │      └── 5. compare pass_rate to threshold
   │
   ▼
VM does the actual generation (same code path as the "Run All" button in the UI)
   │
   ▼
PRs land on aspose-pdf/agentic-net-examples
```

Two important properties:

1. **The VM does the actual work.** Same in-memory `BUILD_STATE`, same auto-learning, same model warm-up. The CI job is just a calendar with an HTTP client.
2. **The CI job is synchronous.** It blocks until the VM job finishes (up to the 6h timeout). This gives a single GitLab pipeline status that reflects "did the sweep succeed", which is what you want for alerting.

## Required CI/CD variables

Set under **Settings → CI/CD → Variables**:

| Key | Example value | Flags | Why |
|-----|---------------|-------|-----|
| `VM_BASE_URL` | `http://172.20.1.175:7103` | Protected | Where the scheduled job sends HTTP calls. Use the internal IP because GitLab runners reach the internal subnet (proven by the existing `generate-examples` job). Use the public port 7003 instead if you want traffic to traverse nginx |
| `VM_API_KEY` | (generated value matching `API_KEY` env var on VM) | **Masked**, Protected | Bearer key the script sends as `X-API-Key`. Must match the VM's `API_KEY` env var |
| `SWEEP_PASS_RATE_THRESHOLD` | `0.95` | Protected | Pass-rate floor — below this the CI job exits non-zero and the pipeline goes red |

Optional tuning variables (defaults shown):

| Key | Default | Effect |
|-----|---------|--------|
| `SWEEP_POLL_INTERVAL_SECONDS` | `60` | Status poll cadence |
| `SWEEP_REPO_PUSH` | `true` | If `false`, the sweep generates examples but doesn't commit/push them |
| `SWEEP_PR_STYLE` | `per-category` | Or `single` for one big PR |
| `SWEEP_PRODUCT` | `aspose.pdf` | Forwarded to the categories fetch |

## Activating the schedule

Once the variables are set and the MR is merged:

1. Go to **Project → Build → Pipeline Schedules**
2. Click **New schedule**:

   | Field | Value |
   |-------|-------|
   | Description | `Weekly full sweep` |
   | Interval Pattern | Custom (Cron) — `13 21 * * 0` (Sunday 02:13 PKT) |
   | Cron Timezone | UTC (the cron is written in UTC; convert local times accordingly) |
   | Target Branch | `main` |
   | Variables | Add `TRIGGER_SWEEP` = `true` |
   | Activated | ✓ |

3. Click **Save pipeline schedule**

> **Why minute 13?** GitLab's pipeline-schedule worker only wakes at minutes matching `3-59/10 * * * *` (i.e. 3, 13, 23, 33, 43, 53). A cron with minute `0` is rejected as "syntax invalid". See `docs/mutation-testing.md` for the same constraint.

## Manual smoke test before going live

Before waiting for the next Sunday, run the schedule manually once:

1. **Project → Build → Pipeline Schedules → ▶ Play** on the new schedule
2. Watch the pipeline. The `scheduled-sweep` job appears under the `trigger` stage
3. Open the job log — you should see (in order):
   - "Pre-flight: checking VM deep health..." + JSON of the response
   - "Got N categories"
   - "Sweep started: job_id=..."
   - Periodic "status=running processed=X/Y passed=A failed=B" lines
   - Final "Sweep completed" or "Sweep ended with status 'failed'"
4. After completion, download the `sweep_result.json` artifact for the full final state

If the smoke test fails:

| Symptom | Likely cause | Fix |
|---------|--------------|-----|
| Pre-flight fails with timeout | Runner can't reach the VM | Confirm `VM_BASE_URL` is correct, and the runner subnet has access |
| Pre-flight returns 401 / 403 | `VM_API_KEY` doesn't match the VM's `API_KEY` env var | Re-check both values; restart the VM service after editing `.env.production` |
| Pre-flight returns `status: unhealthy` | A VM dependency probe failed | Hit the URL directly: `curl $VM_BASE_URL/api/health/ready` and look at the `checks` block |
| `/api/categories` returns empty | The external Tasks/Categories API at `172.20.1.175:7061` is down | Wait or use Path A as a fallback |
| Sweep starts but never moves | The VM's `BUILD_STATE` is in a weird state | Cancel the job from the Build Monitor UI; restart the service if needed |

## What happens on a normal Sunday

Without anyone clicking anything:

| Time | What | Where |
|------|------|-------|
| 02:13 PKT | Pipeline Schedule fires | GitLab |
| 02:13 PKT | `scheduled-sweep` job starts | alpine container on a runner |
| 02:13 PKT | Pre-flight passes; sweep is started on VM | VM gets POST `/api/start-tasks` |
| 02:14–06:00 PKT (varies) | Sweep runs through all categories | VM |
| 02:13–06:00 PKT | CI job polls `/api/status` every 60s | runner |
| ~06:00 PKT | Sweep completes | VM commits + pushes per-category PRs |
| ~06:00 PKT | CI job evaluates pass rate vs threshold | runner |
| ~06:00 PKT | Pipeline turns green (≥ threshold) or red (< threshold) | GitLab |
| Whenever you check Monday morning | Read CI status + Slack notification | You |

When the pipeline goes red:
1. Click into the failed `scheduled-sweep` job
2. Download `sweep_result.json` from the artifacts
3. Open the Results Dashboard on the VM to inspect failed categories
4. Decide whether to retry, skip, or fix

## Future automation built on top of this

Once Path B is running reliably, these are the planned next layers:

- **Auto-retry failed categories**: if pass rate < threshold, schedule a follow-up CI job that re-runs only the failed ones with exponential backoff
- **Auto-promote with safety gate**: after a clean sweep, auto-call `/api/promote-to-main` if pass rate ≥ threshold; hold for manual review if below
- **Auto-curate auto-learned rules**: nightly job moves hit-tested rules from `resources/auto_fixes.json` to `resources/error_fixes.json` with dedup
- **NuGet release detection**: poll the NuGet API for new Aspose.PDF versions; trigger version-bump on change

Each is a separate MR that wires into the existing Pipeline Schedule infrastructure.

## See also

- [`scripts/ci/scheduled-sweep.sh`](../scripts/ci/scheduled-sweep.sh) — the shell logic
- [`.gitlab-ci.yml`](../.gitlab-ci.yml) — the job definition (stage `trigger`)
- [`docs/runbook.md`](./runbook.md) — incident response when the sweep fails
- [`docs/observability.md`](./observability.md) — Prometheus / Grafana view of sweep activity
- [`docs/access-control.md`](./access-control.md) — who can change `VM_API_KEY`
