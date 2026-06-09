# Security Policy

## Reporting a Vulnerability

If you discover a security vulnerability in this project, please report it privately.

**Do not** open a public GitHub issue or pull request describing the vulnerability.

### How to report

Email **fahadadeel@gmail.com** with:

- A description of the issue and its potential impact
- Steps to reproduce (proof-of-concept code if available)
- The commit SHA or version where you observed it
- Any suggested remediation

We will respond within **48 hours** to acknowledge receipt. A full triage and remediation timeline will follow within **5 business days**.

## Supported Versions

This project ships continuous releases tagged `vX.Y.Z` aligned with the underlying Aspose.PDF NuGet version. Security fixes are applied to the latest tagged release only — older versions are not patched.

| Version | Supported |
|---------|-----------|
| Latest `vX.Y.Z` (current `main`) | ✅ |
| Older tags | ❌ |

## Security Practices

This repository enforces the following security controls in CI on every push:

- **Static analysis** — [`bandit`](https://github.com/PyCQA/bandit) blocks merges on high-severity findings; configuration in [`bandit.yaml`](./bandit.yaml)
- **Dependency vulnerability scan** — [`pip-audit`](https://github.com/pypa/pip-audit) runs against `requirements-ci.txt` on every CI build
- **Lint enforcement** — [`ruff`](https://github.com/astral-sh/ruff) zero violations required
- **Coverage floor** — `pytest --cov-fail-under=50` prevents test regressions

See [`docs/runbook.md`](./docs/runbook.md) for the secret rotation procedure and incident response steps.

## Disclosure

Once a fix has been released, we may publish a brief advisory in the project [CHANGELOG](./CHANGELOG.md) under a `Security` heading. Reporters who request public credit will be acknowledged in the advisory.
