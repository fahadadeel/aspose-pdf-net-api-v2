# Policy as Code

This directory holds machine-readable governance artifacts for the repository — branch protection, ruleset definitions, and related access control. Treating policy as code keeps the live configuration auditable, version-controlled, and reproducible across forks or new environments.

## Files

| File | Purpose | Applied to |
|------|---------|------------|
| [`github-branch-protection-main.json`](./github-branch-protection-main.json) | Branch protection rules for the `main` branch | `fahadadeel/aspose-pdf-net-api-v2` (GitHub) |

See [`docs/branch-protection.md`](../docs/branch-protection.md) for the human-readable policy statement, plus the GitLab equivalent.

## Applying changes

Branch protection updates are applied via the GitHub API. Each file in this directory is the exact body of a `PUT /repos/{owner}/{repo}/branches/{branch}/protection` request.

```bash
gh api --method PUT \
  repos/fahadadeel/aspose-pdf-net-api-v2/branches/main/protection \
  --input policy/github-branch-protection-main.json
```

## Verification

```bash
# Confirm the live policy matches the file
gh api repos/fahadadeel/aspose-pdf-net-api-v2/branches/main/protection \
  --jq '{required_status_checks, allow_force_pushes, allow_deletions, required_conversation_resolution}'
```

## Change control

Any change to a policy file must:
1. Open a PR against `main` (which the policy itself protects)
2. Pass CI (ruff + pytest)
3. Be reviewed by a CODEOWNERS reviewer (see [`.github/CODEOWNERS`](../.github/CODEOWNERS))
4. Be applied to the live repository via the `gh api` command above as part of the merge sign-off
