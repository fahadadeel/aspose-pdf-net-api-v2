# Branch Protection Policy

Active branch protection rules on `main` for both the GitHub mirror and the GitLab origin. The machine-readable form lives in [`policy/`](../policy/README.md).

## GitHub — `fahadadeel/aspose-pdf-net-api-v2` `main`

Policy file: [`policy/github-branch-protection-main.json`](../policy/github-branch-protection-main.json)

| Rule | Value | Why |
|------|-------|-----|
| Direct pushes to `main` | **Blocked** | All changes must come through PRs so CI runs first |
| Required status checks | `test` | The GitHub Actions job that runs ruff + bandit + pytest |
| Strict status checks | Enabled | PR branch must be up to date with main before merge |
| Force pushes | **Blocked** | Prevents accidental history rewrites; secret-scrub force-pushes require a temporary lift |
| Branch deletion | **Blocked** | `main` cannot be deleted via the API or UI |
| Conversation resolution | Required before merge | Surfaces unresolved review comments |
| Required PR reviews | **Not enforced** | Sole maintainer setup; would self-block on every solo PR |
| Linear history | Not required | Squash and merge commits are both allowed |
| Admin override (`enforce_admins`) | **Disabled** | Repo owner can recover from broken-CI deadlocks; logged in audit trail |

### Apply the policy

```bash
gh api --method PUT \
  repos/fahadadeel/aspose-pdf-net-api-v2/branches/main/protection \
  --input policy/github-branch-protection-main.json
```

### Verify the live policy

```bash
gh api repos/fahadadeel/aspose-pdf-net-api-v2/branches/main/protection \
  --jq '{required_status_checks, allow_force_pushes, allow_deletions, required_conversation_resolution}'
```

## GitLab — `sialkot/faisalabad-openize/aspose-pdf-net-api-v2` `main`

GitLab uses the **Protected Branches** UI under *Settings → Repository → Protected branches*. The active rules:

| Rule | Value |
|------|-------|
| Allowed to merge | Maintainers |
| Allowed to push and merge | Maintainers |
| Allowed to force push | **Off** (temporarily enabled only for documented secret-history rewrites) |
| Code owner approval required | On |

GitLab also requires pipeline success before merge:

| Rule | Value |
|------|-------|
| Pipelines must succeed | On |
| Skip pipelines must run | Off |

## Bypass procedure (force push)

The only sanctioned reason to force push to `main` is removing a leaked secret from git history. Procedure documented in [`docs/runbook.md`](./runbook.md#secret-rotation):

1. Disable force-push protection in the relevant UI (GitHub or GitLab)
2. Run `git filter-repo --replace-text` to scrub the secret
3. Force-push to both remotes
4. **Re-enable** force-push protection immediately
5. Rotate the leaked credential at the source system
6. Record the action in the CHANGELOG under `Security`

## Audit

Any change to either policy file must:

1. Open a PR against `main`
2. Pass CI (ruff + pytest)
3. Be reviewed by a CODEOWNERS reviewer (see [`.github/CODEOWNERS`](../.github/CODEOWNERS))
4. Be applied to the live repository as part of the merge sign-off using the commands above

Drift between the policy file and the live configuration should be caught manually during PR review — there is no automated drift detector at this time.
