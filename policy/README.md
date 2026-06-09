# Policy as Code

This directory holds machine-readable governance artifacts for the repository — branch protection, ruleset definitions, and related access control. Treating policy as code keeps the live configuration auditable, version-controlled, and reproducible across forks or new environments.

## Files

| File | Purpose | Applied to |
|------|---------|------------|
| [`github-branch-protection-main.json`](./github-branch-protection-main.json) | Branch protection rules for the `main` branch | `fahadadeel/aspose-pdf-net-api-v2` (GitHub) |
| [`gitlab-branch-protection-main.json`](./gitlab-branch-protection-main.json) | Branch protection + MR gates for `main` | `sialkot/faisalabad-openize/aspose-pdf-net-api-v2` (GitLab) |

See [`docs/branch-protection.md`](../docs/branch-protection.md) for the human-readable policy statement, plus the GitLab equivalent.

## Applying changes

### GitHub
Each GitHub file is the exact body of a `PUT /repos/{owner}/{repo}/branches/{branch}/protection` request.

```bash
gh api --method PUT \
  repos/fahadadeel/aspose-pdf-net-api-v2/branches/main/protection \
  --input policy/github-branch-protection-main.json
```

### GitLab
GitLab requires two API calls (branch protection and project-level MR settings live in separate endpoints) and a user token with **Owner** role on the project — project bot tokens are not sufficient.

```bash
# Branch protection: must DELETE then CREATE (the PATCH endpoint doesn't
# accept access-level lists)
glab api --method DELETE projects/560/protected_branches/main
glab api --method POST projects/560/protected_branches \
  -f name=main \
  -f allowed_to_push='[{"access_level":40}]' \
  -f allowed_to_merge='[{"access_level":40}]' \
  -f allow_force_push=false \
  -f code_owner_approval_required=true

# Project-level MR gates
glab api --method PUT projects/560 \
  -f only_allow_merge_if_pipeline_succeeds=true \
  -f only_allow_merge_if_all_discussions_are_resolved=true \
  -f merge_requests_require_code_owner_approval=true \
  -f allow_merge_on_skipped_pipeline=false
```

## Verification

```bash
# GitHub
gh api repos/fahadadeel/aspose-pdf-net-api-v2/branches/main/protection \
  --jq '{required_status_checks, allow_force_pushes, allow_deletions, required_conversation_resolution}'

# GitLab — branch protection
glab api projects/560/protected_branches/main
# GitLab — project-level MR gates
glab api projects/560 \
  | python3 -c "import json,sys; d=json.load(sys.stdin); [print(f'{k}:', d.get(k)) for k in ('only_allow_merge_if_pipeline_succeeds','only_allow_merge_if_all_discussions_are_resolved','merge_requests_require_code_owner_approval')]"
```

## Change control

Any change to a policy file must:
1. Open a PR against `main` (which the policy itself protects)
2. Pass CI (ruff + pytest)
3. Be reviewed by a CODEOWNERS reviewer (see [`.github/CODEOWNERS`](../.github/CODEOWNERS))
4. Be applied to the live repository via the `gh api` command above as part of the merge sign-off
