# Changelog

All notable changes to this project are documented here.

## [Unreleased] - 2026-06-10
### Added
- Contract tests with `schemathesis==4.21.3` — `tests/integration/test_contract.py` loads the live OpenAPI schema from the ASGI app and generates property-based requests for every documented endpoint. Currently runs against an allowlist of 6 well-defined READ-ONLY endpoints (`/api/health`, `/api/version`, `/api/metrics`, `/api/auto-fixes`, `/api/results`, `/api/repo-categories`); 32 endpoints are deliberately skipped pending schema tightening (listed in `_TODO_PATHS`). Foundation for full contract coverage as endpoint response models get explicit
- `scripts/export_openapi.py` — dumps the FastAPI OpenAPI schema to `docs/openapi.json` for repo-browsable API contract. Wired into GitLab CI as an artifact (30-day retention)
- `docs/openapi.json` — committed snapshot of the API contract (38 endpoints, 41 KB)

### Changed
- `requirements.txt` switched from ranged version pins (`>=current,<next_major`) to exact pins (`==`) for reproducible builds. `python-multipart` bumped to `0.0.27` and `requests` to `2.33.0` to clear the CVEs flagged by `pip-audit`. Dependabot will continue to propose minor/major bumps as PRs
- `requirements-ci.txt` — added `schemathesis==4.21.3`

## [Unreleased] - 2026-06-09
### Security
- Removed hardcoded `LITELLM_API_KEY` default from `config.py` — key now loads exclusively from the `LITELLM_API_KEY` env var
- Replaced CORS `allow_origins=["*"]` wildcard in `main.py` with explicit origins from a new `CORS_ORIGINS` env var (defaults to `localhost:7103`)
- Moved `reporting.py` endpoint token from URL query string to `Authorization: Bearer` header to prevent leakage via logs/proxies
- Scrubbed previously committed `LITELLM_API_KEY` from all of git history via `git filter-repo` and force-pushed to both remotes
- Added `bandit` SAST scanner and `pip-audit` dependency vulnerability scan as required CI steps on both GitHub Actions and GitLab CI; bandit config in `bandit.yaml`
- Marked SHA1 slug hash in `git_ops/committer.py` as `usedforsecurity=False` to reflect it's only used for filename truncation, not security
- New `middleware/security.py` with two middlewares wired into `main.py`:
  - `SecurityHeadersMiddleware` adds `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`, `Referrer-Policy: no-referrer`, `Permissions-Policy` (geo/mic/camera disabled), and `Strict-Transport-Security` to every response
  - `APIKeyMiddleware` optionally gates `/api/*` behind `X-API-Key` or `Authorization: Bearer` when the new `API_KEY` env var is set; no-op when unset to keep local dev frictionless. `/api/health`, `/`, `/results`, `/results-v2` remain public for monitoring/UI
- Type checking with `mypy==2.1.0` — added `mypy.ini` (lenient config, strict_optional disabled), wired as non-blocking CI step in GitHub Actions and GitLab CI, and `make typecheck` target
- `.pre-commit-config.yaml` — local hooks for ruff, bandit, trailing whitespace, end-of-file fixer, large-file guard, private-key detection
- `/api/metrics` endpoint — uptime, active/paused/completed/failed job counts, total examples processed, pass rate percentage. Lightweight observability without Prometheus dependency
- `/api/version` endpoint — service version, NuGet version, .NET TFM for deployment verification
- `make security` target — runs bandit + pip-audit locally with same flags as CI
- Branch protection enabled on `main` (GitHub): blocks direct pushes, requires `test` status check, disables force pushes and deletions, requires conversation resolution before merge
- `policy/` directory introduced as policy-as-code: `policy/github-branch-protection-main.json` is the exact API body applied to GitHub via `gh api --method PUT`; `policy/README.md` documents how to apply and verify
- `docs/branch-protection.md` — human-readable branch protection policy for both GitHub and GitLab, with the documented bypass procedure for secret-history rewrites
- `CONTRIBUTING.md` — new "Branch Protection & PR Workflow" section linking the protection policy and PR template
- `docs/runbook.md` — secret rotation step 5 now links to the bypass procedure in `docs/branch-protection.md`

### Added
- Auto-generated GitHub Release notes (`git_ops/release_notes.py`) — diffs `index.json` between release branch and main to produce a rich release body with summary table, new/updated categories, and full category breakdown. Wired into `run_version_bump()` and `run_promote_to_main()` in `jobs.py`
- **Update README** button on Results Dashboard + new `POST /api/update-readme` endpoint — scans live repo file counts, regenerates `README.md` with the improved Agentic format, and pushes directly to the examples repo (no PR)
- `docs/runbook.md` — operations runbook with SLA targets, severity definitions, on-call contacts, 6 common failure scenarios with mitigation steps, rollback procedure, and secret rotation steps
- `CORS_ORIGINS` env var documented in `.env.example` and `.claude/rules/env-vars.md`
- New `tests/integration/` suite — `test_app_integration.py` (full-app FastAPI boot, CORS, MCP mount, `/api/update-readme`); `test_router_endpoints.py` (42 router endpoint scenarios); `test_middleware.py` (9 security header / API key scenarios); `test_metrics_endpoints.py` (7 scenarios for `/api/health`, `/api/version`, `/api/metrics`). Pushed `routers/jobs.py` coverage from 22% to 62%, `routers/health.py` to 95%, and total coverage from 51% to 66.6%
- README CI/quality badges (CI, coverage, tests, ruff, bandit, Python version, .NET framework version)
- `SECURITY.md` — vulnerability reporting policy with 48-hour ack SLA, supported versions, and links to security controls
- `.github/dependabot.yml` — weekly grouped dependency updates for `pip` and `github-actions` ecosystems with separate runtime/dev groups
- `.github/PULL_REQUEST_TEMPLATE.md` and `.github/ISSUE_TEMPLATE/{bug_report,feature_request}.md` — standardized PR/issue formats
- `docs/ownership.md` — operational accountability doc with team contacts, component owners, RACI matrix, and escalation path
- Expanded `CONTRIBUTING.md` with a **Testing** section (test layers table — unit, integration, planned contract + mutation), **Quality Gates** section enumerating the 5 CI checks every PR runs, optional pre-commit setup, and a **Related Documentation** index linking architecture, deployment, runbook, ownership, and security policy

### Changed
- `generate_readme()` in `git_ops/repo_docs.py` refactored — now produces the improved Agentic format with "For AI Coding Agents" section, category table with `agents.md` links, and the **Agentic .NET Ecosystem** table linking all 7 sibling repos (Words, Cells, HTML, Imaging, Slides, Email, BarCode); ecosystem list extracted to `_ECOSYSTEM_REPOS` constant
- `pytest.ini` — coverage gate raised to `--cov-fail-under=60` (current 64%)
- `API_KEY` env var added to `.env.example` and `.claude/rules/env-vars.md`
- Updated `aspose-pdf/agentic-net-examples` repo description to start with "Agentic, build-validated..." and expanded GitHub topics to 20 (added `agentic`, `agentic-ai`, `llm`, `mcp`, `generative-ai`, `pdf-conversion`, `pdf-editing`, `pdf-forms`, `pdf-annotations`, `digital-signatures`) for better discoverability
- Expanded `.github/CODEOWNERS` with per-component path mappings (pipeline, knowledge, git_ops, routers, CI, security, docs) so PR reviews are routed to the right owner

## [Unreleased] - 2026-06-02
### Fixed
- Pinned `scipy<1.16.0` to fix pipeline crash during KB load — scipy 1.16+ introduced an internal assertion (`"Warnings too long"`) triggered on `sentence_transformers` import, killing Stage 3+ jobs
- Wrapped `PipelineRunner.execute()` in try/except so unhandled exceptions return a `FAILED` result instead of crashing the job thread

### Added
- MCP server at `/mcp` via `fastapi-mcp` — standard Model Context Protocol, works with any MCP client (Claude Desktop, Cursor, Continue.dev, etc.)
- `mcp_config.example.json` — ready-to-use client configuration
- `Makefile` with targets: `run`, `run-reload`, `install`, `install-ci`, `lint`, `lint-fix`, `test`, `test-fast`, `check`, `build-image`, `env`
- `ruff.toml` — ruff linter config (E/F rules, line-length 120, py312 target)

### Changed
- Version-pinned all `requirements.txt` entries with `>=current,<next_major`
- `requirements-ci.txt` uses exact `==` pins for reproducibility; added `ruff`
- CI (GitLab + GitHub Actions) now enforces zero ruff violations before tests
- Updated `agents.md`: added MCP interface capability, corrected test counts (117 tests across 11 files)

## [26.4.0] - 2026-04-01
### Changed
- Bumped Aspose.PDF NuGet target to `26.4.0`
- Promoted release/26.4.0 branch to main (snapshot-promote)
- Added Results Dashboard (`/results-v2`) with post-generation actions
- Added disk-backed persistence and crash recovery (`persistence.py`)
- Added rollback system with Flow A/B snapshots (`scripts/rollback.py`)

## [26.3.0] - 2026-03-01
### Changed
- Bumped Aspose.PDF NuGet target to `26.3.0`
- Added parallel orchestrator (`scripts/parallel_run.py`) — N workers on ports 7110+
- Added auto-learning pipeline (`knowledge/auto_learner.py`)
- Added usage reporting to JSONL (`reporting.py`)
- Added pre-commit `.cs` compilation verification before git commit

## [26.2.0] - 2026-02-01
### Added
- Initial pipeline: MCP generate → dotnet build/run → multi-stage retry
- Pattern-based error fixes (`pipeline/error_parser.py`)
- LLM fix loop with configurable attempts (`LLM_FIX_ATTEMPTS`)
- Knowledge base semantic search (`knowledge/rule_search.py`)
- Git commit/push + PR creation (`git_ops/`)
- FastAPI UI with SSE streaming build monitor
- CLI interface (`cli.py`)
- Unit tests (`tests/`)
