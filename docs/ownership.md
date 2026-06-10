# Ownership & RACI

Operational accountability for the Aspose PDF Examples Generator. Roles map to actual people via the matrix below; broader on-call procedures are in [`docs/runbook.md`](./runbook.md).

## Team

| Role | Name | Contact |
|------|------|---------|
| Project owner | Fahad Adeel | fahadadeel@gmail.com |
| Engineering lead | Fahad Adeel | fahadadeel@gmail.com |
| Backup / secondary on-call | Faisalabad Openize team | via Slack |
| Stakeholder (product) | Aspose.PDF product team | via Aspose internal channels |

## Component Owners

Each subsystem has a primary owner responsible for code review, design decisions, and incident response within that area. See [`.github/CODEOWNERS`](../.github/CODEOWNERS) for the machine-readable form enforced on PRs.

| Component | Path | Primary owner |
|-----------|------|---------------|
| Pipeline (generation, build, fix loop) | `pipeline/` | Fahad Adeel |
| Knowledge base (rules, catalog, learning) | `knowledge/`, `resources/*.json` | Fahad Adeel |
| Git operations (commit, PR, release) | `git_ops/` | Fahad Adeel |
| FastAPI service surface | `routers/`, `main.py` | Fahad Adeel |
| CI/CD configuration | `.github/`, `.gitlab-ci.yml` | Fahad Adeel |
| Security policy | `SECURITY.md`, `bandit.yaml` | Fahad Adeel |
| Documentation | `docs/`, `README.md`, `CHANGELOG.md` | Fahad Adeel |

## RACI Matrix

R = Responsible, A = Accountable, C = Consulted, I = Informed.

| Activity | Owner | Eng Lead | Stakeholder |
|----------|-------|----------|-------------|
| Code change merge | R | A | I |
| Release / version bump | R | A | I |
| Promote to main | R | A | I |
| Production deployment (Windows VM) | R | A | I |
| Secret rotation | R | A | I |
| Security vulnerability triage | R | A | C |
| Incident response (P1/P2) | R | A | I |
| Adding a new category | R | A | C |
| Rule addition / KB tuning | R | A | I |
| Breaking API change | C | A | C |
| Sunset of a feature | C | A | C |

## Escalation

For incidents that cannot be resolved by the primary on-call within the SLA windows defined in [`docs/runbook.md`](./runbook.md):

1. **Within 1 hour for P1**: notify the engineering lead
2. **Within 4 hours for P1**: escalate to the Aspose engineering management
3. **For external-impact incidents** (broken PRs already merged to public examples repo): notify Aspose.PDF product team immediately

## Contribution Sign-off

For the detailed roles × resources matrix (who can push, who can merge, who can rotate secrets, who can RDP into the VM), see [`docs/access-control.md`](./access-control.md). For data classification, retention, and deletion procedures, see [`docs/data-handling.md`](./data-handling.md).

All PRs require:

- At least one CODEOWNERS approval (enforced by branch protection on `main`)
- Passing CI (ruff, bandit, pip-audit, pytest with coverage gate)
- An updated [`CHANGELOG.md`](../CHANGELOG.md) entry for any user-facing change

See [`CONTRIBUTING.md`](../CONTRIBUTING.md) for the developer setup and contribution workflow.
