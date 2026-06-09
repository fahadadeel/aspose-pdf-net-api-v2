# Changelog

All notable changes to this project are documented here.

## [Unreleased] - 2026-06-09
### Security
- Removed hardcoded `LITELLM_API_KEY` default from `config.py` — key now loads exclusively from the `LITELLM_API_KEY` env var
- Replaced CORS `allow_origins=["*"]` wildcard in `main.py` with explicit origins from a new `CORS_ORIGINS` env var (defaults to `localhost:7103`)
- Moved `reporting.py` endpoint token from URL query string to `Authorization: Bearer` header to prevent leakage via logs/proxies
- Scrubbed previously committed `LITELLM_API_KEY` from all of git history via `git filter-repo` and force-pushed to both remotes
- Added `bandit` SAST scanner and `pip-audit` dependency vulnerability scan as required CI steps on both GitHub Actions and GitLab CI; bandit config in `bandit.yaml`
- Marked SHA1 slug hash in `git_ops/committer.py` as `usedforsecurity=False` to reflect it's only used for filename truncation, not security

### Added
- Auto-generated GitHub Release notes (`git_ops/release_notes.py`) — diffs `index.json` between release branch and main to produce a rich release body with summary table, new/updated categories, and full category breakdown. Wired into `run_version_bump()` and `run_promote_to_main()` in `jobs.py`
- **Update README** button on Results Dashboard + new `POST /api/update-readme` endpoint — scans live repo file counts, regenerates `README.md` with the improved Agentic format, and pushes directly to the examples repo (no PR)
- `docs/runbook.md` — operations runbook with SLA targets, severity definitions, on-call contacts, 6 common failure scenarios with mitigation steps, rollback procedure, and secret rotation steps
- `CORS_ORIGINS` env var documented in `.env.example` and `.claude/rules/env-vars.md`
- New `tests/integration/` suite covering full-app FastAPI boot, CORS configuration, MCP mount, and the `/api/update-readme` endpoint via `TestClient`

### Changed
- `generate_readme()` in `git_ops/repo_docs.py` refactored — now produces the improved Agentic format with "For AI Coding Agents" section, category table with `agents.md` links, and the **Agentic .NET Ecosystem** table linking all 7 sibling repos (Words, Cells, HTML, Imaging, Slides, Email, BarCode); ecosystem list extracted to `_ECOSYSTEM_REPOS` constant
- `pytest.ini` — added `--cov-fail-under=50` to prevent coverage regression (current 51%)
- Updated `aspose-pdf/agentic-net-examples` repo description to start with "Agentic, build-validated..." and expanded GitHub topics to 20 (added `agentic`, `agentic-ai`, `llm`, `mcp`, `generative-ai`, `pdf-conversion`, `pdf-editing`, `pdf-forms`, `pdf-annotations`, `digital-signatures`) for better discoverability

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
