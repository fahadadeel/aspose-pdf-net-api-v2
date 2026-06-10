# Operations Runbook

Operational runbook for the Aspose PDF Examples Generator service. Covers on-call procedures, escalation, common failure scenarios, and SLAs.

## Service Overview

| Field | Value |
|-------|-------|
| Service name | Aspose PDF Examples Generator |
| Tier | Internal tooling — Tier 2 |
| Runtime | Python 3.12 / FastAPI / uvicorn (single worker) |
| Production host | Windows VM at `C:\fahad\aspose-pdf-net-api-v2` (NSSM service) |
| UI port | `7103` |
| Output | GitHub PRs to `aspose-pdf/agentic-net-examples` |

## SLA Targets

| Metric | Target |
|--------|--------|
| Availability (business hours) | 99% |
| Time to acknowledge incident | 30 minutes |
| Time to mitigate (P1) | 4 hours |
| Time to mitigate (P2) | 1 business day |
| Time to RCA publish | 3 business days |

## Severity Definitions

- **P1 — Critical**: Service completely down, or generating broken PRs that have shipped to the public examples repo
- **P2 — High**: Pipeline failing for all jobs but no public impact yet; or specific category 100% failing
- **P3 — Medium**: Specific tasks failing intermittently; partial degradation
- **P4 — Low**: Cosmetic UI issues, log noise, non-blocking errors

## On-Call

| Role | Contact |
|------|---------|
| Primary on-call | Fahad Adeel — fahadadeel@gmail.com |
| Secondary on-call | Team lead (Faisalabad Openize) |
| Escalation | Aspose engineering management |

On-call window is informal — best-effort during business hours (PKT). For after-hours P1 incidents, page the primary via email/Slack.

## First Response (Any Incident)

1. **Acknowledge** the alert/report within 30 minutes
2. **Check the Build Monitor UI** (`http://<host>:7103/`) — is the service responding?
3. **Run the deep health check** to localize the failure:
   ```bash
   curl -s http://<host>:7103/api/health/ready | python -m json.tool
   ```
   Returns per-dependency status (`mcp`, `llm`, `disk`, `dotnet`, `repo_path`). HTTP 503 = at least one dependency is unhealthy; 200 + `status: degraded` = soft issue worth investigating.
4. **Tail the service logs**:
   ```powershell
   nssm status AsposePdfApi
   Get-Content C:\fahad\aspose-pdf-net-api-v2\logs\service.log -Tail 200
   ```
5. **Classify severity** (P1-P4) and document in the incident channel
6. **Mitigate before investigating** — see scenarios below

## Common Failure Scenarios

### Pipeline jobs failing for all tasks

**Symptoms**: 100% failure rate across categories, log shows the same error pattern.

**Mitigation**:
1. Check MCP server reachability: `curl http://172.20.1.175:7050/health`
2. Check LiteLLM proxy: `curl https://llm.professionalize.com/v1/models -H "Authorization: Bearer $LITELLM_API_KEY"`
3. If both up, check `.env` for missing/expired secrets
4. Restart the service: `nssm restart AsposePdfApi`

### "Warnings too long" / scipy crash

**Symptoms**: Stage 3+ jobs crashing with `AssertionError: Warnings too long` from `scipy/_lib/_array_api.py`.

**Mitigation**: Pin scipy `<1.16.0`:
```bash
pip install "scipy>=1.11.4,<1.16.0"
```
Already pinned in `requirements.txt`. If reappears, check installed version: `pip show scipy`.

### Job thread dies silently

**Symptoms**: Job goes to `running` but never completes; no log entries after a certain stage.

**Mitigation**:
1. `execute()` in `pipeline/runner.py` wraps everything in try/except — check job log for the traceback
2. If no traceback, the issue is upstream of `execute()` — check `jobs.py` thread spawning
3. Cancel the job via UI and re-run

### GitHub PR creation failing

**Symptoms**: Jobs pass but PRs are not created; logs show `403` or `422` from GitHub API.

**Mitigation**:
1. Check `REPO_TOKEN` is set and has `repo` scope
2. Check branch protection on target branch — release branches need bypass
3. Check rate limit: `gh api rate_limit`
4. If `MERGE_ACCT_GITHUB_TOKEN` is being used for approvals, verify it too

### Memory usage growing unbounded

**Symptoms**: Service RAM climbing past 2 GB over hours.

**Mitigation**:
1. `_MAX_LOGS = 500` in `state.py` caps log buffer — verify this is in effect
2. Check for stuck jobs in `BUILD_STATE` — restart the service to clear in-memory state (no persistence loss for already-completed jobs)
3. Restart on a schedule if needed (NSSM can do daily restarts)

### Examples repo out of sync

**Symptoms**: README shows wrong stats; index.json missing categories.

**Mitigation**: Use the Results Dashboard at `/results-v2`:
1. Click **Update Docs** — regenerates agents.md and index.json via PR
2. Click **Update README** — pushes README directly (no PR)

## Rollback Procedure

If a bad release/promote is pushed to `aspose-pdf/agentic-net-examples`:

```bash
# View snapshots (created automatically before each merge/promote)
python scripts/rollback.py list

# Revert the most recent snapshot
python scripts/rollback.py revert <snapshot-id> --confirm
```

See `scripts/rollback_snapshot.py` for atomic snapshot details.

## Secret Rotation

If a secret is exposed:

1. **Immediately revoke** the old credential in the source system (LiteLLM dashboard, GitHub PAT settings, etc.)
2. Generate a new credential
3. Update `.env.production` on the Windows VM
4. Restart the service: `nssm restart AsposePdfApi`
5. If the secret was committed to git history, use `git filter-repo --replace-text` to scrub it from history, then force-push. This requires temporarily lifting force-push protection — see the bypass procedure in [`docs/branch-protection.md`](./branch-protection.md#bypass-procedure-force-push)

## Related Compliance Docs

- [`docs/data-handling.md`](./data-handling.md) — data inventory, retention, deletion procedures, compliance posture (what's satisfied, what isn't)
- [`docs/access-control.md`](./access-control.md) — roles × resources matrix, onboarding / offboarding procedures
- [`docs/branch-protection.md`](./branch-protection.md) — branch-protection policy and the documented bypass procedure for secret scrubs
- [`docs/ownership.md`](./ownership.md) — RACI matrix and escalation path

## Monitoring

The service exposes a Prometheus scrape endpoint at `/api/metrics/prometheus` and a deep health check at `/api/health/ready`. See [`docs/observability.md`](./observability.md) for:

- Prometheus scrape config snippet
- Grafana dashboard JSON (`docs/grafana/aspose-pdf-api-v2-overview.json`)
- Suggested alert rules (`ServiceDown`, `HighErrorRate`, `PipelineFailureRateHigh`, `NoActivity`, `P99LatencyHigh`)
- Local Prometheus + Grafana docker-compose stack for testing

Each alert above maps to a section in this runbook — when one fires, find the matching scenario under **Common Failure Scenarios** below.

## Useful Commands

```bash
# Quick health check
curl http://localhost:7103/api/health

# Active jobs
curl http://localhost:7103/api/jobs

# Recent logs (Windows)
Get-Content C:\fahad\aspose-pdf-net-api-v2\logs\service.log -Tail 100 -Wait

# Restart (Windows)
nssm restart AsposePdfApi

# Run tests locally before pushing a fix
make check
```

## Post-Incident

1. Create a brief RCA within 3 business days for P1/P2 incidents
2. Link the RCA in the commit message or PR description
3. Add any new failure patterns to this runbook
4. Add a regression test if the root cause was code
