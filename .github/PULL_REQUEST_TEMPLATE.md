## Summary

<!-- One or two sentences explaining what this PR does and why. -->

## Type of Change

- [ ] Bug fix
- [ ] New feature
- [ ] Refactor / code cleanup
- [ ] Documentation
- [ ] CI / build / dependency update
- [ ] Security fix

## Checklist

- [ ] `make check` passes locally (ruff + pytest with coverage gate)
- [ ] `bandit -c bandit.yaml -r . -lll` reports zero high-severity findings
- [ ] `CHANGELOG.md` updated under the current `[Unreleased] - YYYY-MM-DD` section
- [ ] New / modified code has test coverage
- [ ] No secrets, API keys, or credentials in code or commit messages

## Risk / Rollback

<!--
What's the blast radius if this goes wrong? How would we roll it back?
For releases, link the rollback snapshot ID from scripts/rollback.py.
-->

## Related Issues

<!-- e.g. Fixes #123, Closes #456 -->
