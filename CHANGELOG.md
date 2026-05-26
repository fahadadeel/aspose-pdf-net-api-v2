# Changelog

All notable changes to this project are documented here.

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
