# Changelog

All notable changes to this project are documented here.

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
