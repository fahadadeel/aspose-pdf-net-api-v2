---
name: Bug report
about: A pipeline run failed, produced wrong output, or the service is broken
title: "[Bug] "
labels: ["bug"]
assignees: []
---

## Description

<!-- What happened? What did you expect? -->

## Reproduction

1. ...
2. ...
3. ...

## Environment

| Field | Value |
|-------|-------|
| Service version / commit SHA | |
| `NUGET_VERSION` (from `.env`) | |
| OS (host running the service) | |
| Job ID (if applicable) | |
| Category / task name | |

## Logs

```
<!-- Paste relevant lines from logs/service.log or the Job log in the UI -->
```

## Severity

- [ ] P1 — Service down or shipping broken PRs to public examples repo
- [ ] P2 — All jobs failing or a whole category 100% failing
- [ ] P3 — Specific tasks failing intermittently
- [ ] P4 — Cosmetic / non-blocking
