# Aspose PDF Net API V2 — Agent Definition

## Identity

| Field | Value |
|-------|-------|
| **Name** | Aspose.PDF Example Generator |
| **Type** | AI Agent |
| **Author** | Fahad Adeel |
| **Version** | 2.0 |
| **Language** | Python 3.12 |
| **Framework** | FastAPI + Uvicorn |
| **Runtime** | Single-process, multi-threaded |
| **License** | Proprietary |

## Purpose

Automated C# code generation and testing pipeline for Aspose.PDF for .NET. Generates working code examples via an MCP API, compiles and runs them with `dotnet`, auto-fixes errors through a multi-stage retry pipeline, and publishes results as GitHub pull requests.

## Output Repository

Generated examples are committed and pushed to a separate GitHub repository:

| Field | Value |
|-------|-------|
| **Repository** | [aspose-pdf/agentic-net-examples](https://github.com/aspose-pdf/agentic-net-examples) |
| **Default Config** | `REPO_URL` in [`config.py`](config.py), overridable via `.env` |
| **Local Clone Path** | `REPO_PATH` in `.env` (e.g. `C:\fahad\agentic-net-examples-v3` on server) |
| **Branch Strategy** | Feature branches per category (e.g. `examples/{job_id}-conversion`), PRs target `main` or `release/{version}` |
| **File Structure** | `{Category}/{slug}.cs` with `agents.md` and `index.json` sidecar files per category |

This repository (aspose-pdf-net-api-v2) is the **agent/pipeline** — it generates, tests, and publishes code. The output repository contains only the final passing C# examples.

## Capabilities

### Code Generation & Testing
- Generate C# examples from natural language task prompts via MCP API ([`pipeline/mcp_client.py`](pipeline/mcp_client.py)) or own LLM ([`pipeline/llm_client.py`](pipeline/llm_client.py))
- Compile and run generated code with .NET SDK ([`pipeline/build.py`](pipeline/build.py))
- 5-stage auto-fix pipeline: baseline → pattern fix → LLM fix → context enrichment + regen → final LLM recovery ([`pipeline/runner.py`](pipeline/runner.py), [`pipeline/stages.py`](pipeline/stages.py))
- Regex-based deterministic error pattern fixes ([`pipeline/error_parser.py`](pipeline/error_parser.py))

### Self-Learning
- Auto-learn reusable fix rules from mid-pipeline successes ([`knowledge/auto_learner.py`](knowledge/auto_learner.py))
- Auto-expand error catalog from successful fixes ([`knowledge/error_catalog.py`](knowledge/error_catalog.py))
- Track recurring code transformations and auto-promote at threshold ([`knowledge/pattern_tracker.py`](knowledge/pattern_tracker.py))
- Confidence-weighted error fix matching with curated and auto-learned rules ([`knowledge/error_fixes.py`](knowledge/error_fixes.py))
- Semantic + keyword hybrid KB search with LLM reranking ([`knowledge/rule_search.py`](knowledge/rule_search.py), [`knowledge/reranker.py`](knowledge/reranker.py))

### Git & PR Management
- Clone, branch, commit, and push to GitHub repositories ([`git_ops/repo.py`](git_ops/repo.py), [`git_ops/committer.py`](git_ops/committer.py))
- Create pull requests with LLM-generated descriptions ([`git_ops/pr.py`](git_ops/pr.py))
- GitHub REST API wrapper for files, PRs, refs, tags, and releases ([`git_ops/github_api.py`](git_ops/github_api.py))
- Per-category PR splitting for large batches
- Pre-commit compile verification of .cs files ([`jobs.py`](jobs.py))
- Generate per-category `agents.md` and `index.json` sidecar files ([`git_ops/agents_md.py`](git_ops/agents_md.py), [`git_ops/agents_content.py`](git_ops/agents_content.py))
- Cumulative repo docs scanning and generation ([`git_ops/repo_docs.py`](git_ops/repo_docs.py))

### Version Lifecycle
- Version bump: tag main, create GitHub Release, create orphan staging branch, seed CI workflows, update .env ([`jobs.py#run_version_bump`](jobs.py))
- Promote to main: snapshot-promote staging branch as a single fast-forward commit ([`jobs.py#run_promote_to_main`](jobs.py))
- Rollback: revert merged PRs or promote commits via CLI ([`scripts/rollback.py`](scripts/rollback.py), [`scripts/rollback_snapshot.py`](scripts/rollback_snapshot.py))

### Persistence & Crash Recovery
- Versioned disk-backed results with atomic writes ([`persistence.py`](persistence.py))
- Resume interrupted batch jobs by skipping already-passed tasks
- Per-category JSON index + individual .cs code files in `results/{version}/`

### Parallel Execution
- Multi-worker orchestrator spawns N uvicorn instances with isolated workspaces ([`scripts/parallel_run.py`](scripts/parallel_run.py))
- Greedy bin-packing distributes categories across workers
- Human-attributed batch merge of release PRs ([`scripts/merge_release_prs.py`](scripts/merge_release_prs.py))

### Monitoring & Reporting
- Real-time Server-Sent Events (SSE) for live progress ([`routers/jobs.py#api_stream`](routers/jobs.py))
- Thread-safe in-memory job state with pause/resume/cancel ([`state.py`](state.py))
- Usage reporting to external endpoint with local JSONL logging ([`reporting.py`](reporting.py))
- Token usage tracking per job ([`pipeline/usage_tracker.py`](pipeline/usage_tracker.py))

### Results Management
- Results Dashboard with per-category cards, status filters, repo sync status ([`templates/results-v2.html`](templates/results-v2.html), [`routers/results.py`](routers/results.py))
- Create PRs from persisted disk results without re-running the pipeline ([`jobs.py#create_pr_from_results`](jobs.py))
- Regenerate missing metadata (title, description, tags, APIs) via LLM ([`jobs.py#regenerate_metadata`](jobs.py))
- Download results as CSV ([`templates/index.html`](templates/index.html))
- Patch existing PR branches with missing sidecar files

## API Surface

### Job Management

| Method | Endpoint | Handler | Description |
|--------|----------|---------|-------------|
| POST | `/api/start` | [`routers/jobs.py#api_start`](routers/jobs.py) | Start single or CSV job |
| POST | `/api/start-tasks` | [`routers/jobs.py#api_start_tasks`](routers/jobs.py) | Start job from task list |
| POST | `/api/start-sweep` | [`routers/jobs.py#api_start_sweep`](routers/jobs.py) | Start category sweep |
| POST | `/api/cancel/{job_id}` | [`routers/jobs.py#api_cancel`](routers/jobs.py) | Cancel a running job |
| POST | `/api/pause/{job_id}` | [`routers/jobs.py#api_pause`](routers/jobs.py) | Pause a running job |
| POST | `/api/resume/{job_id}` | [`routers/jobs.py#api_resume`](routers/jobs.py) | Resume a paused job |
| GET | `/api/status/{job_id}` | [`routers/jobs.py#api_status`](routers/jobs.py) | Poll job status |
| GET | `/api/stream/{job_id}` | [`routers/jobs.py#api_stream`](routers/jobs.py) | Real-time SSE stream |
| POST | `/api/retry-pr/{job_id}` | [`routers/jobs.py#api_retry_pr`](routers/jobs.py) | Create/retry PR |
| POST | `/api/retry-failed/{job_id}` | [`routers/jobs.py#api_retry_failed`](routers/jobs.py) | Re-run failed tasks |

### Version Lifecycle

| Method | Endpoint | Handler | Description |
|--------|----------|---------|-------------|
| POST | `/api/version-bump` | [`jobs.py#run_version_bump`](jobs.py) | Tag, create staging branch, update .env |
| POST | `/api/promote-to-main` | [`jobs.py#run_promote_to_main`](jobs.py) | Snapshot-promote staging to main |

### Results & PRs

| Method | Endpoint | Handler | Description |
|--------|----------|---------|-------------|
| GET | `/api/results` | [`routers/jobs.py#api_results`](routers/jobs.py) | List disk results per category |
| GET | `/api/results/all-categories` | [`routers/jobs.py#api_results_all`](routers/jobs.py) | Combined disk + repo view |
| GET | `/api/results/sync-status` | [`routers/jobs.py#api_sync_status`](routers/jobs.py) | Compare disk vs GitHub |
| GET | `/api/results/{category}` | [`routers/jobs.py#api_results_category`](routers/jobs.py) | Category detail |
| POST | `/api/create-pr-from-results` | [`jobs.py#create_pr_from_results`](jobs.py) | Create PR from disk results |
| POST | `/api/regenerate-metadata` | [`jobs.py#regenerate_metadata`](jobs.py) | Backfill metadata via LLM |
| POST | `/api/update-repo-docs` | [`git_ops/repo_docs.py`](git_ops/repo_docs.py) | Regenerate agents.md + index.json |
| POST | `/api/patch-pr-branch` | [`routers/jobs.py#api_patch_pr_branch`](routers/jobs.py) | Add sidecar files to PR branch |

### Auto-Learned Rules

| Method | Endpoint | Handler | Description |
|--------|----------|---------|-------------|
| GET | `/api/auto-fixes` | [`routers/jobs.py#api_auto_fixes`](routers/jobs.py) | List auto-learned rules |
| POST | `/api/auto-fixes/{id}/approve` | [`routers/jobs.py#api_approve_auto_fix`](routers/jobs.py) | Promote to curated fixes |
| POST | `/api/auto-fixes/approve-all` | [`routers/jobs.py#api_approve_all`](routers/jobs.py) | Promote all rules |
| DELETE | `/api/auto-fixes/{id}` | [`routers/jobs.py#api_delete_auto_fix`](routers/jobs.py) | Remove a rule |

### Data & Utilities

| Method | Endpoint | Handler | Description |
|--------|----------|---------|-------------|
| GET | `/api/health` | [`routers/health.py`](routers/health.py) | Health check |
| GET | `/api/categories` | [`routers/categories.py`](routers/categories.py) | Fetch categories |
| GET | `/api/tasks` | [`routers/tasks.py`](routers/tasks.py) | Fetch tasks by category |
| POST | `/api/upload-files` | [`routers/files.py`](routers/files.py) | Upload test input files |
| GET | `/api/repo-categories` | [`routers/jobs.py#api_repo_categories`](routers/jobs.py) | List repo branch categories |

## Architecture

### Core Modules

| Module | Purpose |
|--------|---------|
| [`main.py`](main.py) | FastAPI app entry point, router registration |
| [`jobs.py`](jobs.py) | Background job runners (pipeline, PR creation, version bump, promote) |
| [`state.py`](state.py) | Thread-safe in-memory job state, SSE notifications, pause/resume/cancel |
| [`config.py`](config.py) | Typed dataclass configuration with .env overrides |
| [`persistence.py`](persistence.py) | Versioned disk-backed results with atomic writes |
| [`reporting.py`](reporting.py) | Usage reporting (remote POST + local JSONL) |
| [`cli.py`](cli.py) | CLI interface (single, CSV, sweep, version-bump, promote) |

### Pipeline

| Module | Purpose |
|--------|---------|
| [`pipeline/runner.py`](pipeline/runner.py) | 5-stage pipeline orchestrator |
| [`pipeline/stages.py`](pipeline/stages.py) | Individual stage implementations |
| [`pipeline/build.py`](pipeline/build.py) | .NET build + run with timeout and process group cleanup |
| [`pipeline/mcp_client.py`](pipeline/mcp_client.py) | MCP API client (generate + retrieve) |
| [`pipeline/llm_client.py`](pipeline/llm_client.py) | LLM client (fix, generate, metadata extraction, PR description) |
| [`pipeline/anthropic_client.py`](pipeline/anthropic_client.py) | Anthropic API for rule generalization |
| [`pipeline/error_parser.py`](pipeline/error_parser.py) | Build output parser + regex pattern fixes |
| [`pipeline/prompt_builder.py`](pipeline/prompt_builder.py) | Prompt construction with namespace restriction |
| [`pipeline/usage_tracker.py`](pipeline/usage_tracker.py) | Thread-safe token + API call counters |
| [`pipeline/models.py`](pipeline/models.py) | Data classes (TaskInput, PipelineResult, StageOutcome) |

### Knowledge Base

| Module | Purpose |
|--------|---------|
| [`knowledge/rule_search.py`](knowledge/rule_search.py) | Hybrid semantic + keyword KB search |
| [`knowledge/reranker.py`](knowledge/reranker.py) | LLM-based rule reranking |
| [`knowledge/error_catalog.py`](knowledge/error_catalog.py) | Error pattern → fix guidance matching |
| [`knowledge/error_fixes.py`](knowledge/error_fixes.py) | Scored error fix matching (confidence-weighted) |
| [`knowledge/fix_history.py`](knowledge/fix_history.py) | Auto-recorded successful fix history |
| [`knowledge/auto_fixes.py`](knowledge/auto_fixes.py) | Auto-learned fix persistence + CRUD |
| [`knowledge/auto_learner.py`](knowledge/auto_learner.py) | Extract rules from successful fixes |
| [`knowledge/pattern_tracker.py`](knowledge/pattern_tracker.py) | Track recurring transformations → auto-promote |

### Git Operations

| Module | Purpose |
|--------|---------|
| [`git_ops/repo.py`](git_ops/repo.py) | RepoManager (clone, pull, branch, git lock) |
| [`git_ops/committer.py`](git_ops/committer.py) | CodeCommitter (write files, stage, commit) |
| [`git_ops/pr.py`](git_ops/pr.py) | PRManager (create PR with LLM description) |
| [`git_ops/github_api.py`](git_ops/github_api.py) | GitHub REST API v3 wrapper |
| [`git_ops/agents_md.py`](git_ops/agents_md.py) | Generate agents.md from batch results |
| [`git_ops/agents_content.py`](git_ops/agents_content.py) | Category tips, API surface content |
| [`git_ops/repo_docs.py`](git_ops/repo_docs.py) | Cumulative repo scanning + docs generation |

### Routers

| Module | Purpose |
|--------|---------|
| [`routers/ui.py`](routers/ui.py) | HTML UI endpoints (/, /results, /results-v2) |
| [`routers/jobs.py`](routers/jobs.py) | All job, results, and auto-fixes API endpoints |
| [`routers/results.py`](routers/results.py) | Results Dashboard page routes |
| [`routers/tasks.py`](routers/tasks.py) | Task API proxy |
| [`routers/categories.py`](routers/categories.py) | Categories API proxy |
| [`routers/files.py`](routers/files.py) | File upload endpoint |
| [`routers/health.py`](routers/health.py) | Health check |

### Scripts

| Module | Purpose |
|--------|---------|
| [`scripts/parallel_run.py`](scripts/parallel_run.py) | Parallel orchestrator (N workers) |
| [`scripts/merge_release_prs.py`](scripts/merge_release_prs.py) | Human-attributed batch merge |
| [`scripts/verify_passed.py`](scripts/verify_passed.py) | Demote non-compiling .cs files |
| [`scripts/rollback.py`](scripts/rollback.py) | Rollback CLI (revert-flow-a, revert-flow-b) |
| [`scripts/rollback_snapshot.py`](scripts/rollback_snapshot.py) | Snapshot capture/load helpers |
| [`scripts/populate_generation_rules.py`](scripts/populate_generation_rules.py) | Generate auto_generation_rules.json |

## Data Flow

```
Task Prompt
    │
    ▼
┌─────────────────────────┐
│  Stage 1: Baseline      │  MCP retrieve → LLM generate → dotnet build+run
│  Pass? → commit to git  │
│  Fail? ↓                │
├─────────────────────────┤
│  Pattern Fix (×5)       │  Regex-based deterministic fixes
│  Pass? → commit to git  │
│  Fail? ↓                │
├─────────────────────────┤
│  Stage 2: LLM Fix (×3)  │  Send code + errors to LLM
│  Pass? → commit to git  │
│  Fail? ↓                │
├─────────────────────────┤
│  Stage 3: Enrich        │  Fetch more API docs + KB rules
│  Stage 4: Regen (×3)    │  MCP regen with full context
│  Pass? → commit to git  │
│  Fail? ↓                │
├─────────────────────────┤
│  Stage 5: Final LLM     │  Last recovery attempt
│  Pass? → commit to git  │
│  Fail? → mark FAILED    │
└─────────────────────────┘
    │
    ▼
┌─────────────────────────┐
│  Persistence            │  results/{version}/{category}/passed/*.cs
│  Git Commit + PR        │  GitHub branch + pull request
│  Usage Report           │  Remote endpoint + local JSONL
└─────────────────────────┘
```

## Testing

Unit tests cover core modules: persistence, error fixes, pattern tracker, config, and state management.

```bash
python -m pytest tests/ -v
```

Tests run automatically on every push via [`.gitlab-ci.yml`](.gitlab-ci.yml).

| Test File | Module | Tests |
|-----------|--------|-------|
| [`tests/test_persistence.py`](tests/test_persistence.py) | [`persistence.py`](persistence.py) | 8 |
| [`tests/test_error_fixes.py`](tests/test_error_fixes.py) | [`knowledge/error_fixes.py`](knowledge/error_fixes.py) | 5 |
| [`tests/test_pattern_tracker.py`](tests/test_pattern_tracker.py) | [`knowledge/pattern_tracker.py`](knowledge/pattern_tracker.py) | 3 |
| [`tests/test_config.py`](tests/test_config.py) | [`config.py`](config.py) | 2 |
| [`tests/test_state.py`](tests/test_state.py) | [`state.py`](state.py) | 2 |
