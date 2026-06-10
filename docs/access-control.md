# Access Control

Who can do what to this service, the source repos, and the production deployment. This document is the operator-readable companion to the machine-readable [`policy/`](../policy/) artifacts and the [`.github/CODEOWNERS`](../.github/CODEOWNERS) file.

Treat it as **engineering-grade access documentation** — honest about what we control via tooling and what relies on operator discipline. Not a SOC 2 access-control attestation.

## Scope

| In scope | Out of scope |
|----------|--------------|
| Access to the running service (`/api/*`) | Access to Aspose corporate systems |
| Access to the source repositories (GitLab origin, GitHub mirror) | Access to the LiteLLM / MCP upstream systems (owned by other teams) |
| Access to the production Windows VM | Access to contributor laptops |
| Access to the published `aspose-pdf/agentic-net-examples` repo | Aspose internal directory / SSO |

## Identity sources

| Surface | Identity comes from |
|---------|--------------------|
| GitLab repo (`gitlab.recruitize.ai`) | GitLab username + 2FA, plus project access tokens for automation |
| GitHub mirror (`fahadadeel/aspose-pdf-net-api-v2`) | GitHub username + 2FA |
| GitHub output repo (`aspose-pdf/agentic-net-examples`) | Aspose GitHub org membership |
| Production Windows VM | Aspose IT-managed account (RDP) |
| Service API (`/api/*`) | Optional bearer / `X-API-Key` token via the `API_KEY` env var. When unset, the API is open (current state on the Windows VM, fronted by network ACLs) |

## Roles

| Role | Held by | What it can do |
|------|---------|----------------|
| **Project owner** | Fahad Adeel | All of the below. Last word on architecture, releases, and policy changes |
| **Pipeline operator** | Fahad Adeel | Trigger / monitor / cancel pipeline jobs via UI or `/api/start*`. Approve auto-learned rules. Run version bumps and promotes |
| **Source repo maintainer** | Fahad Adeel (project access token: `policy-drift-check`) | Merge MRs on GitLab, configure CI variables, manage branch protection. CODEOWNERS-approved reviews |
| **GitHub output repo admin** | Aspose GitHub org admins + Fahad Adeel | Manage branch protection on `aspose-pdf/agentic-net-examples`. Apply policy from `policy/branch-protection-main.json` |
| **Deployment admin** | Fahad Adeel | RDP into the Windows VM. Stop/start the NSSM service. Edit `.env.production`. Future: manage the container deployment |
| **External contributor** | Anyone with a GitLab / GitHub account | Open MRs/PRs. Cannot bypass CI gates or branch protection |

There is intentionally no separation between "developer" and "operator" today — this is a single-maintainer project. If a second person joins, the role split would be: project owner unchanged, second person picks up either pipeline-operator or deployment-admin.

## Resource × action matrix

✅ = permitted, ⛔ = blocked by tooling, ⚠️ = permitted but logged / discouraged.

| Action | Project owner | Source repo maintainer | Pipeline operator | Deployment admin | External contributor |
|--------|:-:|:-:|:-:|:-:|:-:|
| Read source repo | ✅ | ✅ | ✅ | ✅ | ✅ (public history) |
| Push to a feature branch | ✅ | ✅ | ⛔ | ⛔ | ✅ via fork |
| Direct push to `main` | ⛔ branch protection | ⛔ branch protection | ⛔ | ⛔ | ⛔ |
| Force push to `main` | ⛔ except for documented secret-scrub bypass | ⛔ | ⛔ | ⛔ | ⛔ |
| Merge an MR / PR to `main` | ✅ (CODEOWNERS + CI gates required) | ✅ | ⛔ | ⛔ | ⛔ |
| Change CI variables (`POLICY_DRIFT_TOKEN`, `LITELLM_API_KEY`) | ✅ | ✅ | ⛔ | ⛔ | ⛔ |
| Change branch protection / policy JSON | ✅ via MR + apply | ✅ via MR + apply | ⛔ | ⛔ | ⛔ (review only) |
| Trigger a pipeline job | ✅ | ✅ | ✅ | ⛔ | ⛔ |
| Cancel / pause / resume a job | ✅ | ✅ | ✅ | ⛔ | ⛔ |
| Approve an auto-learned rule | ✅ | ✅ | ✅ | ⛔ | ⛔ |
| Run a version bump or promote-to-main | ✅ | ✅ | ✅ | ⛔ | ⛔ |
| Push directly to `aspose-pdf/agentic-net-examples` `main` | ⛔ branch protection | ⛔ branch protection | ✅ via `Update README` / `Update Docs` API (bot token bypass — documented) | ⛔ | ⛔ |
| Read production logs | ✅ via RDP | ⛔ | ⛔ | ✅ | ⛔ |
| Start / stop / restart NSSM service | ✅ | ⛔ | ⛔ | ✅ | ⛔ |
| Edit `.env.production` | ✅ via RDP | ⛔ | ⛔ | ✅ | ⛔ |
| Rotate secrets | ✅ | ✅ (the policy-drift token) | ⛔ | ✅ for `.env.production` | ⛔ |

## API access (`/api/*`)

The service supports an optional bearer-token gate. See [`middleware/security.py::APIKeyMiddleware`](../middleware/security.py).

| Mode | When | Effect |
|------|------|--------|
| Open (no `API_KEY` set) | Current Windows VM deployment | All `/api/*` endpoints reachable from anyone on the network. Acceptable because the service binds to a private subnet (`172.20.1.x`) with no public ingress |
| Gated (`API_KEY` env var set) | Future / staging / container deployments behind a public ingress | Every `/api/*` request must include `X-API-Key: <key>` or `Authorization: Bearer <key>`. Public paths (`/api/health`, `/api/health/ready`, `/api/metrics/prometheus`, the UI, `/results`, `/results-v2`) stay reachable — standard practice for liveness probes and monitoring |

When `API_KEY` is set, share the token only with operators in the **pipeline operator** role. Rotate on a calendar or on suspected compromise.

## Repo access enforced by branch protection

The live branch protection on both GitLab and GitHub is the **machine-readable source of truth** for who can write to `main`. The text below is descriptive — refer to the JSON artefacts for the exact policy.

- **GitLab `main`** (`policy/gitlab-branch-protection-main.json`): push and merge restricted to **Maintainers** (access level 40). Force push disabled. Pipeline must succeed. Discussions must be resolved before merge.
- **GitHub `main`** on the generator mirror (`policy/github-branch-protection-main.json`): direct pushes blocked, `test` status check required, force pushes and deletions blocked, conversation resolution required.
- **GitHub `main`** on `aspose-pdf/agentic-net-examples` (`policy/branch-protection-main.json` inside that repo): direct pushes blocked, `Build & Run changed examples` status check required, force pushes blocked, conversation resolution required.

Drift between the JSON files and the live config is detected automatically by `scripts/check_policy_drift.py` running on every CI build with the `POLICY_DRIFT_TOKEN` CI variable.

## Audit trail

| What | Where it's recorded |
|------|---------------------|
| Source-code changes | git history on GitLab + GitHub. Every MR has an author and merger |
| Branch protection changes | git history of `policy/*.json` + the live API logs (GitHub / GitLab provide tamper-evident audit history for repo settings) |
| CI variable changes | GitLab CI/CD Variables page audit log (visible to maintainers+) |
| Pipeline jobs run | `BUILD_STATE` (in-memory), `usage_reports.jsonl` (on disk), `pipeline_jobs_total{final_status}` Prometheus counter (30-day TSDB retention in the container deployment) |
| Secret rotation events | Manual — recorded in CHANGELOG under `Security` |
| Production deployments | NSSM event log on the Windows VM. Container deployments: `docker compose` exit / restart events |
| Policy drift detections | CI job logs, archived for 30 days as job artefacts |

## Onboarding a new operator

If a second person needs **pipeline-operator** role:

1. Add them as a Developer on the GitLab project. Confirm they can clone, push feature branches, and open MRs
2. If GitHub PRs are needed (no longer the standard workflow — we're GitLab-only since June 2026), add them as a collaborator on the generator mirror with **write** but not **admin**
3. Walk them through [`CONTRIBUTING.md`](../CONTRIBUTING.md) and [`docs/runbook.md`](./runbook.md)
4. Share the GitLab Pipeline Schedules they should be aware of (see the runbook's Monitoring section)
5. **Do not** share the `LITELLM_API_KEY`, `REPO_TOKEN`, or `POLICY_DRIFT_TOKEN` — those stay with the maintainer
6. If they need to trigger jobs against the running service, share an API key (if `API_KEY` is enabled) — never the bearer of the original CI variables

For **deployment-admin** role:

1. Aspose IT grants RDP access to the production Windows VM
2. Share the location of `.env.production` and walk through which variables are safe to edit
3. Demonstrate the NSSM service lifecycle (`status`, `stop`, `start`, `restart`)
4. Walk through [`docs/runbook.md`](./runbook.md) Common Failure Scenarios
5. Share read-access to the Grafana dashboard (or stand up a personal Grafana with the dashboard imported)

## Offboarding

| Action | Owner | Timing |
|--------|-------|--------|
| Remove from GitLab project | Project owner | Same day as departure |
| Remove from GitHub collaborators | Project owner | Same day |
| Revoke any GitLab project access tokens they created | Project owner | Same day |
| Revoke any GitHub personal access tokens shared with them | The departing operator owns this; project owner verifies | Same day |
| Rotate `LITELLM_API_KEY`, `REPO_TOKEN`, `POLICY_DRIFT_TOKEN`, `API_KEY` | Project owner | Within 7 days if they ever had access; immediately if access was suspected to be compromised |
| Revoke RDP / VM access | Aspose IT | Same day |
| Update `docs/ownership.md` and `docs/access-control.md` (this file) | Project owner | Within 1 week |
| Audit recent commits and pipeline runs from their identity for anything unusual | Project owner | Within 2 weeks |

## Changes to this document

This file is reviewed alongside any change that:
- Adds or removes a role
- Adds or removes a resource that's subject to access control
- Changes branch-protection policy
- Adds a new identity source

CHANGELOG entries that touch any of those should include a note that this document was reviewed and either left unchanged or updated.
