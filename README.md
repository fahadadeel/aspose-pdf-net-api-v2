# Aspose.PDF for .NET — Examples Generator

Automated C# code generation and testing pipeline for **Aspose.PDF for .NET**. Generates working code examples via an MCP API, compiles and runs them with `dotnet`, and auto-fixes errors through a multi-stage retry pipeline. Results can be committed to GitHub with auto-generated pull requests.

---

## Table of Contents

- [Quick Start](#quick-start)
- [Architecture](#architecture)
- [Usage](#usage)
  - [Web UI](#web-ui)
  - [CLI](#cli)
  - [REST API](#rest-api)
- [Category Sweep Mode](#category-sweep-mode)
- [Version Bump](#version-bump)
- [Usage Reporting](#usage-reporting)
- [Configuration](#configuration)
  - [Environment Variables](#environment-variables)
  - [Build Settings](#build-settings)
  - [Pipeline Settings](#pipeline-settings)
  - [MCP Settings](#mcp-settings)
  - [LLM Settings](#llm-settings)
  - [Git & PR Settings](#git--pr-settings)
  - [Knowledge Base Settings](#knowledge-base-settings)
- [Pipeline Stages](#pipeline-stages)
- [Self-Learning](#self-learning)
- [PR Workflow](#pr-workflow)
- [Knowledge Base](#knowledge-base)
- [Project Structure](#project-structure)

---

## Quick Start

### Prerequisites

- Python 3.12+
- .NET SDK 10.0 (`dotnet` must be on `PATH`)
- A GitHub Personal Access Token (for PR creation)
- Access to the MCP code generation API

### Installation

```bash
# Clone the repo
git clone https://github.com/fahadadeel/aspose-pdf-net-api-v2.git
cd aspose-pdf-net-api-v2

# Create virtual environment
python -m venv .venv
source .venv/bin/activate  # Linux/macOS
# .venv\Scripts\activate   # Windows

# Install dependencies
pip install -r requirements.txt
```

### Environment Setup

Copy the example environment file and fill in your values:

```bash
cp .env.example .env
```

Edit `.env` with your keys:

```env
LITELLM_API_KEY=sk-your-key-here
REPO_TOKEN=ghp_your-github-pat
REPO_USER=your-email@example.com
```

### Run

```bash
# Web UI (development)
uvicorn main:app --host 0.0.0.0 --port 7103 --reload

# Web UI (production) — must use single worker
uvicorn main:app --host 0.0.0.0 --port 7103 --workers 1

# CLI — single task
python cli.py --task "Save a PDF document to disk"

# CLI — batch from CSV
python cli.py --csv tasks.csv --repo-push
```

> **Important:** Always use `--workers 1`. State is stored in-memory and is not shared across workers.

---

## Architecture

```
                    ┌──────────────┐
                    │   Web UI     │  Jinja2 HTML + SSE
                    │   (port 7103)│
                    └──────┬───────┘
                           │
              ┌────────────┼────────────┐
              │       FastAPI App       │  main.py
              │    (routers + SSE)      │
              └────────────┬────────────┘
                           │
              ┌────────────┼────────────┐
              │     Job Runner (jobs.py)│  Daemon threads
              │   ┌────────────────┐    │
              │   │  5-Stage       │    │
              │   │  Pipeline      │    │
              │   │  (runner.py)   │    │
              │   └───┬───┬───┬────┘    │
              │       │   │   │         │
              │  ┌────┘   │   └────┐    │
              │  MCP    LLM    KB  │    │
              │  API    API  Search│    │
              └────────────────────┘    │
                           │
              ┌────────────┼────────────┐
              │   Git Operations        │
              │  (clone, commit, PR)    │
              └─────────────────────────┘
```

The system runs as a single-process FastAPI application. Jobs execute in daemon threads with thread-safe state management. Real-time updates stream to the UI via Server-Sent Events (SSE).

---

## Usage

### Web UI

Start the server and open `http://localhost:7103` in your browser.

The UI has three modes:

| Mode | Description |
|------|-------------|
| **Single** | Enter a single task prompt, select category and product |
| **CSV** | Upload a CSV file with columns: `prompt`, `category`, `product` |
| **Task Generator** | Browse categories and select tasks from the external task API |

**Header Buttons:**
- **Update Repo Docs** — Scan repo and generate cumulative `agents.md` files (creates a separate docs PR)
- **Version Bump** — Tag current version, clean all examples, and regenerate with a new NuGet version

**Options:**
- **Create Pull Request** — Commit passed results to GitHub and create a PR
- **API URL Override** — Use a custom MCP API URL (admin mode, append `?admin` to URL)

**Monitor Panel:**
- Real-time stats: total, passed, failed, pass rate, elapsed time
- Live console log with timestamped entries
- View generated code inline with copy-to-clipboard
- **Create PR** button — Create/retry PR after job completes
- **Download CSV** button — Export results as CSV

**Task Generator Tips:**
- Click a category to load its tasks (single selection)
- **Shift+click** to select multiple categories at once
- Use the search boxes to filter categories and tasks
- Select All / Deselect All for bulk selection
- **Sweep Selected** button — Process ALL tasks across selected categories (per-category usage reports and PRs)

### CLI

```bash
# Single task
python cli.py --task "Convert HTML to PDF" --category "Conversion" --product "aspose.pdf"

# Single task with repo push
python cli.py --task "Add watermark to PDF" --category "Annotations" --repo-push

# Batch from CSV
python cli.py --csv tasks.csv

# Batch with PR creation
python cli.py --csv tasks.csv --repo-push

# Override target framework
python cli.py --task "Merge two PDFs" --tfm "net9.0"

# Category sweep — all categories
python cli.py --sweep

# Category sweep — specific categories
python cli.py --sweep --categories "Basic Operations,Conversion"

# Category sweep with PR creation
python cli.py --sweep --repo-push

# Version bump — tag old, clean, regenerate with new version
python cli.py --version-bump 26.3.0 --repo-push
```

**CLI Arguments:**

| Argument | Required | Default | Description |
|----------|----------|---------|-------------|
| `--task` | Yes* | — | Single task prompt text |
| `--csv` | Yes* | — | Path to CSV file (columns: `task`/`prompt`, `category`, `product`) |
| `--sweep` | Yes* | — | Sweep all tasks across categories |
| `--version-bump` | Yes* | — | Bump NuGet version (e.g., `26.3.0`) |
| `--category` | No | `""` | Category for single task |
| `--categories` | No | `""` | Comma-separated category filter (sweep mode) |
| `--product` | No | `aspose.pdf` | Product name |
| `--repo-push` | No | `false` | Commit results and create PR |
| `--tfm` | No | `net10.0` | .NET target framework override |

*One of `--task`, `--csv`, `--sweep`, or `--version-bump` is required.

### REST API

All endpoints are served under the root path.

#### Job Management

| Endpoint | Method | Description |
|----------|--------|-------------|
| `POST /api/start` | Multipart form | Start single or CSV job |
| `POST /api/start-tasks` | JSON body | Start job from task list |
| `POST /api/start-sweep` | JSON body | Start category sweep job |
| `POST /api/version-bump` | JSON body | Bump NuGet version (tag + clean + sweep) |
| `GET /api/status/{job_id}` | — | Poll job status |
| `GET /api/stream/{job_id}` | SSE | Real-time event stream |
| `POST /api/cancel/{job_id}` | — | Cancel a running job |
| `POST /api/retry-pr/{job_id}` | — | Create or retry PR for completed job |
| `POST /api/update-repo-docs` | JSON body | Generate cumulative repo docs PR |
| `GET /api/auto-fixes` | — | List auto-learned rules (confidence, hits) |
| `POST /api/auto-fixes/{id}/approve` | — | Promote auto rule to curated |
| `DELETE /api/auto-fixes/{id}` | — | Remove auto-learned rule |

#### Data & Utilities

| Endpoint | Method | Description |
|----------|--------|-------------|
| `GET /api/health` | — | Health check |
| `GET /api/categories` | — | Fetch available categories |
| `GET /api/tasks` | — | Fetch tasks by category |
| `POST /api/upload-files` | Multipart | Upload test input files |

#### POST /api/start — Parameters

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `mode` | form | Yes | `single` or `csv` |
| `prompt` | form | Single mode | Task prompt text |
| `category` | form | No | Category name |
| `product` | form | No | Product (default: `aspose.pdf`) |
| `repo_push` | form | No | `"true"` to create PR |
| `force` | form | No | `"true"` to force regeneration |
| `api_url` | form | No | Custom MCP API URL |
| `csv` | file | CSV mode | CSV file upload |

#### POST /api/start-tasks — JSON Body

```json
{
  "tasks": [
    {"task": "Save PDF", "category": "BasicOperations", "product": "aspose.pdf"},
    {"task": "Add bookmark", "category": "Bookmarks"}
  ],
  "repo_push": true,
  "force": false,
  "api_url": null
}
```

#### POST /api/start-sweep — JSON Body

```json
{
  "categories": ["Basic Operations", "Conversion"],
  "repo_push": true,
  "api_url": null
}
```

Processes ALL tasks for each selected category sequentially. Creates a usage report and PR (if `repo_push` is true) after each category.

#### POST /api/version-bump — JSON Body

```json
{
  "new_version": "26.3.0",
  "repo_push": true
}
```

Tags the current version, creates a GitHub Release, deletes all existing examples, and runs a full sweep with the new NuGet version.

#### POST /api/update-repo-docs — JSON Body

```json
{
  "update_readme": true
}
```

When `update_readme` is `true`, the README.md category listing is also updated.

#### GET /api/status Response

```json
{
  "status": "running",
  "total": 50,
  "processed": 12,
  "passed_count": 10,
  "failed_count": 2,
  "pass_rate": 83,
  "elapsed": 145,
  "current_task": "Building: Add bookmark to PDF...",
  "passed": [{"id": 1, "task": "...", "badge": "baseline", "code": "...", "category": "..."}],
  "failed": [{"id": 2, "task": "...", "badge": "stage5", "code": "...", "category": "..."}],
  "logs": ["[10:23:45] Processing task 12/50..."],
  "pr_url": "https://github.com/...",
  "pr_branch": "examples/batch-abc123"
}
```

#### SSE Stream Events

The `GET /api/stream/{job_id}` endpoint pushes JSON messages with delta updates:

```json
{
  "status": "running",
  "total": 50,
  "processed": 12,
  "passed_count": 10,
  "failed_count": 2,
  "pass_rate": 83,
  "elapsed": 145,
  "current_task": "Building...",
  "new_passed": [{"id": 12, "task": "...", "code": "..."}],
  "new_failed": [],
  "new_logs": ["[10:23:45] Task 12 passed (baseline)"],
  "pr_url": ""
}
```

A `done` event is sent when the job finishes.

---

## Category Sweep Mode

Sweep mode processes ALL tasks across selected (or all) categories in a single job. Unlike the normal Task Generator where you pick individual tasks, sweep auto-fetches everything.

**How it works:**
1. Fetches all tasks per category from the external tasks API (paginated)
2. Processes tasks sequentially, one category at a time
3. After each category: sends a **usage report** and creates a **PR** (if enabled)
4. Monitor view shows unified progress across all categories

**Access:**
- **UI:** Task Generator → select categories → click **Sweep Selected**
- **CLI:** `python cli.py --sweep --categories "Basic Operations,Conversion" --repo-push`
- **API:** `POST /api/start-sweep`

**Per-category outputs:**
- Usage report with `run_id` suffix (e.g., `{job_id}-basic-operations`)
- Separate git branch and PR per category (e.g., `examples/{job_id}-basic-operations`)

---

## Version Bump

Automates the process of upgrading to a new Aspose.PDF NuGet version while preserving old examples via Git tags and GitHub Releases.

**Flow:**
1. **Tag** current main branch as `v{old_version}` (e.g., `v26.2.0`)
2. **Create GitHub Release** from the tag (with version metadata)
3. **Clean** all existing `.cs` example files from the repo
4. **Commit** the cleanup to main
5. **Sweep** all categories with the new NuGet version (full regeneration)

**Access:**
- **UI:** Click **Version Bump** in the header → enter new version → confirm
- **CLI:** `python cli.py --version-bump 26.3.0 --repo-push`
- **API:** `POST /api/version-bump`

**After bumping:** Update `NUGET_VERSION` in your `.env` file to persist the new version across restarts.

---

## Usage Reporting

Every job run sends a usage report to a configurable endpoint (Google Apps Script) and/or logs it locally.

**Report payload includes:**
- Agent name, owner, job type
- Items discovered, succeeded, failed
- Run duration, token usage, API call count
- Product, platform, website metadata

**Local logging:** Each report is appended as a JSON line to `usage_reports.jsonl` for local review.

**Config switches:**
| Variable | Default | Description |
|----------|---------|-------------|
| `REPORTING_ENABLED` | `true` | Master switch for all reporting |
| `REPORTING_LOG_TO_FILE` | `true` | Write reports to `usage_reports.jsonl` |
| `REPORTING_ENDPOINT_URL` | *(from .env)* | Remote endpoint URL (empty = skip remote POST) |
| `REPORTING_ENDPOINT_TOKEN` | *(from .env)* | Auth token appended as `?token=` query param |
| `REPORTING_WEBSITE` | `aspose.com` | Website field in reports |
| `REPORTING_WEBSITE_SECTION` | `examples` | Website section field in reports |

---

## Configuration

Configuration is managed through typed Python dataclasses in `config.py`. Every setting can be overridden with environment variables. Place them in a `.env` file (loaded automatically) or export them in your shell.

**Environment-specific config:** Set `APP_ENV` to load a different env file:
- `APP_ENV=production` loads `.env.production`
- `APP_ENV=staging` loads `.env.staging`
- Unset loads `.env`

### Environment Variables

#### Required

| Variable | Description |
|----------|-------------|
| `LITELLM_API_KEY` | API key for the LLM proxy (used for code fixes, PR descriptions) |
| `REPO_TOKEN` | GitHub Personal Access Token (for cloning, pushing, PR creation) |
| `REPO_USER` | Git user email for commits |

#### Recommended

| Variable | Default | Description |
|----------|---------|-------------|
| `API_URL` | `http://172.20.1.175:7050/mcp/generate` | MCP code generation endpoint |
| `MCP_RETRIEVE_URL` | `http://172.20.1.175:7050/mcp/retrieve` | MCP documentation retrieval endpoint |
| `REPO_PATH` | *(local path)* | Local path for the git repository |
| `REPO_URL` | `https://github.com/aspose-pdf/agentic-net-examples.git` | Target GitHub repository |

### Build Settings

Control how generated C# code is compiled and executed.

| Variable | Default | Description |
|----------|---------|-------------|
| `BUILD_TFM` | `net10.0` | .NET target framework moniker |
| `NUGET_PACKAGE` | `Aspose.PDF` | NuGet package name in `.csproj` |
| `NUGET_VERSION` | `26.2.0` | Aspose.PDF NuGet package version |
| `BUILD_TIMEOUT` | `30` | Max seconds for `dotnet build` |
| `RUN_TIMEOUT` | `30` | Max seconds for `dotnet run` |
| `BUILD_VERBOSITY` | `minimal` | dotnet build verbosity (`quiet`, `minimal`, `normal`, `detailed`) |
| `WORKSPACE_PATH` | `.` | Project root (build runs in `_build/` subdirectory) |

### Pipeline Settings

Fine-tune the retry behavior of the 5-stage pipeline.

| Variable | Default | Description |
|----------|---------|-------------|
| `LLM_FIX_ATTEMPTS` | `3` | Number of LLM code-fix attempts in Stage 2. Set to `0` to skip Stage 2 |
| `REGEN_ATTEMPTS` | `3` | Number of MCP regeneration attempts in Stage 4 |
| `RETRIEVE_LIMIT` | `20` | Max API documentation chunks to retrieve |
| `RETRIEVE_MAX_CHARS` | `12000` | Max characters in retrieved context |
| `USE_RETRIEVE_ON_LLM_FAIL` | `true` | Enable API retrieval in Stage 3 |
| `DECOMPOSE_ON_LLM_FAIL` | `false` | Enable LLM task decomposition in Stage 3 |
| `FINAL_LLM_AFTER_REGEN_FAIL` | `true` | Enable Stage 5 final LLM recovery |
| `RETRY_MODE` | `full` | `full` = use KB rules + error catalog; `simple` = minimal regen |
| `USE_OWN_LLM` | `true` | Use own LLM key for code generation instead of MCP's built-in LLM |
| `LEARN_RULES_FROM_FAILURES` | `false` | Post-pipeline rule learning via Anthropic Claude |
| `AUTO_LEARN_ON_SUCCESS` | `true` | Auto-learn rules from mid-pipeline successful fixes |
| `AUTO_LEARN_CATALOG` | `true` | Also auto-expand the error catalog from successful fixes |
| `AUTO_LEARN_MIN_DIFF_LINES` | `3` | Minimum diff lines to trigger auto-learning |

### MCP Settings

Configure the Model Context Protocol API for code generation.

| Variable | Default | Description |
|----------|---------|-------------|
| `API_URL` | `http://172.20.1.175:7050/mcp/generate` | Code generation endpoint |
| `MCP_RETRIEVE_URL` | `http://172.20.1.175:7050/mcp/retrieve` | Documentation retrieval endpoint |
| `MCP_PRODUCT` | `pdf` | Product key sent to MCP |
| `MCP_PLATFORM` | `net` | Platform key sent to MCP |
| `MCP_RETRIEVAL_MODE` | `embedding` | Retrieval strategy |
| `MCP_RETRIEVAL_LIMIT` | `15` | Default retrieval limit |
| `MCP_TIMEOUT` | `30` | Request timeout (seconds) |

### LLM Settings

The LLM is used for code fixes, task decomposition, commit messages, and PR descriptions. It uses an OpenAI-compatible API via a LiteLLM proxy.

| Variable | Default | Description |
|----------|---------|-------------|
| `LITELLM_API_BASE` | `https://llm.professionalize.com/v1` | LLM API base URL |
| `LITELLM_API_KEY` | *(required)* | API key |
| `LITELLM_MODEL` | `gpt-oss` | Model name |

**Optional — Anthropic (for post-pipeline rule learning):**

| Variable | Default | Description |
|----------|---------|-------------|
| `ANTHROPIC_API_KEY` | *(empty)* | Anthropic API key |
| `ANTHROPIC_MODEL` | `claude-sonnet-4-20250514` | Anthropic model |

### Git & PR Settings

Control how generated examples are committed and how PRs are created.

| Variable | Default | Description |
|----------|---------|-------------|
| `REPO_URL` | `https://github.com/aspose-pdf/agentic-net-examples.git` | Target GitHub repository |
| `REPO_PATH` | *(local path)* | Local clone path |
| `REPO_BRANCH` | `main` | Base branch for feature branches |
| `REPO_PUSH` | `false` | Auto-push commits (CLI override with `--repo-push`) |
| `REPO_TOKEN` | *(required for PR)* | GitHub PAT with repo scope |
| `REPO_USER` | *(required for PR)* | Git author email |
| `DEFAULT_CATEGORY` | `uncategorized` | Fallback category for tasks without one |
| `DEFAULT_PRODUCT` | `aspose.pdf` | Fallback product name |
| `PR_SPLIT_THRESHOLD` | `0` | Split PRs by category when file count exceeds this. `0` = disabled (single PR) |

#### PR Splitting

For large batch jobs (e.g., 2000+ tasks), a single PR becomes unwieldy. Set `PR_SPLIT_THRESHOLD` to split:

```bash
# Create one PR per category when batch produces > 200 files
export PR_SPLIT_THRESHOLD=200
```

When enabled:
- Each category gets its own feature branch and PR
- `agents.md` is **not** included in split PRs (use "Update Repo Docs" separately)
- Branch naming: `examples/{category}-{uuid}`

When `PR_SPLIT_THRESHOLD=0` (default):
- All files go into a single PR
- `agents.md` is included in the PR

#### Repo Docs (agents.md)

The **Update Repo Docs** feature creates a separate PR with cumulative documentation:

- Scans all `.cs` files on the main branch
- Generates root `agents.md` with full example listing
- Generates per-category `agents.md` files
- Optionally updates the README.md category listing

This is decoupled from batch PRs so documentation always reflects the actual state of the repository, regardless of which PRs have been merged.

### Knowledge Base Settings

Control KB rule search and reranking behavior.

| Variable | Default | Description |
|----------|---------|-------------|
| `RULES_EXAMPLES_PATH` | `./resources/kb.json` | Knowledge base rules file |
| `ERROR_CATALOG_PATH` | `./resources/error_catalog.json` | Error pattern catalog |
| `ERROR_FIXES_PATH` | `./resources/error_fixes.json` | Curated error fixes |
| `FIX_HISTORY_PATH` | `./fix_history.json` | Auto-recorded successful fixes (capped at 500) |
| `AUTO_FIXES_PATH` | `./resources/auto_fixes.json` | Auto-learned error fix rules |
| `AUTO_CATALOG_PATH` | `./resources/auto_error_catalog.json` | Auto-learned error catalog entries |
| `AUTO_PATTERNS_PATH` | `./resources/auto_patterns.json` | Auto-promoted pattern fixes |
| `RERANK_CANDIDATE_COUNT` | `100` | Initial candidates for LLM reranking |
| `RERANK_TOP_K` | `10` | Final top-K rules after reranking |
| `RERANK_ATTEMPT1_TOP_K` | `20` | Top-K for first regen attempt |
| `RERANK_TIMEOUT` | `20` | Reranking timeout (seconds) |

### External API Settings

| Variable | Default | Description |
|----------|---------|-------------|
| `CATEGORIES_API_URL` | `http://172.20.1.175:7001/api/categories` | Categories listing API |
| `TASKS_API_URL` | `http://172.20.1.175:7001/api/tasks` | Tasks listing API |
| `UI_PORT` | `7103` | Web UI port |

---

## Pipeline Stages

Every task goes through a multi-stage pipeline that progressively applies more sophisticated fixes if the initial generation fails.

```
Task
 │
 ▼
┌─────────────────────────────┐
│  Stage 1: Baseline          │  MCP /generate → dotnet build + run
│  ✅ Success → Return        │
│  ❌ Fail → Continue         │
└──────────────┬──────────────┘
               ▼
┌─────────────────────────────┐
│  Pattern Fix (loop ×5)      │  Regex-based known error fixes
│  ✅ Success → Return        │
│  ❌ Fail → Continue         │
└──────────────┬──────────────┘
               ▼
┌─────────────────────────────┐
│  Stage 2: LLM Fix           │  Send code + errors to LLM for repair
│  (LLM_FIX_ATTEMPTS rounds)  │  Includes matched error fixes as context
│  ✅ Success → Return        │
│  ❌ Fail → Continue         │
└──────────────┬──────────────┘
               ▼
┌─────────────────────────────┐
│  Stage 3: Context Enrichment│  Parallel: MCP /retrieve + task decomposition
│  (Fetch API docs & rules)   │
└──────────────┬──────────────┘
               ▼
┌─────────────────────────────┐
│  Stage 4: Regeneration      │  MCP regen with KB rules, error catalog,
│  (REGEN_ATTEMPTS rounds)    │  error fixes, fix history boosting
│  ✅ Success → Return        │
│  ❌ Fail → Continue         │
└──────────────┬──────────────┘
               ▼
┌─────────────────────────────┐
│  Stage 5: Final LLM Recovery│  One last LLM fix attempt
│  ✅ Success → Return        │  Falls back to pre-regen code if Stage 4
│  ❌ Fail → Mark as FAILED   │  produced nothing
└─────────────────────────────┘
```

**Result badges** indicate which stage produced the final code: `baseline`, `pattern_fix`, `llm_fix`, `regen`, `final_llm`.

**Transient failures:** If the MCP API returns errors (timeouts, 5xx), the task is requeued up to 3 times with backoff instead of being marked as failed.

---

## Self-Learning

The pipeline automatically learns from its own successes. When a task fails at Stage 1 but is fixed at a later stage, the system extracts reusable patterns that help future runs avoid the same errors.

### How It Works

1. **Detect Fix** — When a non-baseline stage succeeds, the pipeline computes a diff between the failing and fixed code
2. **Generalize** — The LLM extracts the API-level fix pattern (not task-specific details) into a structured rule
3. **Deduplicate** — New rules are checked against existing curated and auto-generated rules (50% error overlap threshold)
4. **Save** — Rules are stored in `resources/auto_fixes.json` with confidence metadata
5. **Apply** — Auto-learned rules are merged into the error fix pool on next pipeline run (curated rules always rank higher)

All learning happens in fire-and-forget daemon threads, so it never blocks the pipeline.

### Confidence Scoring

Auto-learned rules start at **0.5 confidence** (curated rules = 1.0). When an auto rule contributes to a successful fix, its confidence increases by 0.1 per hit (capped at 1.0). Confidence acts as a score multiplier during error fix matching, so curated rules naturally rank higher.

### Three Learning Targets

| Target | File | Description |
|--------|------|-------------|
| **Error Fixes** | `resources/auto_fixes.json` | Code snippets + error patterns (same format as `error_fixes.json`) |
| **Error Catalog** | `resources/auto_error_catalog.json` | Error pattern → fix guidance entries |
| **Pattern Fixes** | `resources/auto_patterns.json` | Simple text substitutions promoted after 3+ occurrences |

### Review & Management

Auto-learned rules can be reviewed in the **Learned Rules** tab in the Web UI, or via the API:

| Endpoint | Method | Description |
|----------|--------|-------------|
| `GET /api/auto-fixes` | — | List all auto rules with confidence, hit count, source stage |
| `POST /api/auto-fixes/{id}/approve` | — | Promote to curated `error_fixes.json` |
| `DELETE /api/auto-fixes/{id}` | — | Remove a bad auto rule |

### Configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `AUTO_LEARN_ON_SUCCESS` | `true` | Enable learning from mid-pipeline fixes |
| `AUTO_LEARN_CATALOG` | `true` | Also expand error catalog automatically |
| `AUTO_LEARN_MIN_DIFF_LINES` | `3` | Minimum diff lines to trigger learning |
| `AUTO_FIXES_PATH` | `./resources/auto_fixes.json` | Auto-learned error fixes file |
| `AUTO_CATALOG_PATH` | `./resources/auto_error_catalog.json` | Auto-learned catalog entries |
| `AUTO_PATTERNS_PATH` | `./resources/auto_patterns.json` | Auto-promoted pattern fixes |

---

## PR Workflow

When `repo_push=true` is enabled, the pipeline commits results to GitHub:

1. **Clone/Pull** — `RepoManager` clones the repo (or pulls latest) with token auth
2. **Branch** — Creates a feature branch from the base branch (e.g., `examples/batch-abc123`)
3. **Write Files** — Each passed example is saved as `{category}/{slug}.cs`
4. **Commit** — LLM generates a commit message summarizing the changes
5. **Push** — Push branch to origin
6. **Create PR** — LLM generates PR title and body, creates via GitHub API

**File naming:** Tasks are slugified (lowercase, special chars removed). If a file already exists, it auto-versions: `file__v2.cs`, `file__v3.cs`.

**PR Splitting:** For large batches, set `PR_SPLIT_THRESHOLD` to create one PR per category instead of a single massive PR.

---

## Knowledge Base

The pipeline uses three knowledge sources to improve code generation in retry stages:

### KB Rules (`kb.json`)

Semantic search engine using SentenceTransformer (`all-MiniLM-L6-v2`) embeddings + IDF keyword matching. Each rule contains:
- `semantic_summary` — Natural language description
- `api_surface` — Relevant API types/members
- `rules` — Coding rules and constraints
- `warnings` — Common pitfalls

Search weighting: 55% semantic similarity + 45% keyword match.

### Error Catalog (`error_catalog.json`)

Regex-based pattern matching for common build errors. Each entry maps an error pattern to fix guidance text that's injected into the regeneration prompt.

### Error Fixes (`error_fixes.json`)

Curated database of real error→fix pairs. Scored by error code matches (3 pts) and key phrase matches (2 pts). Top 10 fixes are included as context for LLM and regeneration stages.

### Fix History (`fix_history.json`)

Auto-populated from successful fixes. Caps at 500 entries. Boosts future searches for similar error patterns, making the system learn from its own corrections over time.

---

## Project Structure

```
aspose-pdf-api-v2/
├── main.py                    # FastAPI app entry point
├── cli.py                     # CLI interface (single, csv, sweep, version-bump)
├── config.py                  # Typed configuration (dataclasses + env vars)
├── state.py                   # Thread-safe in-memory job state
├── jobs.py                    # Background job runner (run_job, run_sweep, run_version_bump)
├── reporting.py               # Fire-and-forget usage reporting (remote + local JSONL)
│
├── pipeline/
│   ├── runner.py              # 5-stage pipeline orchestrator
│   ├── stages.py              # Individual stage implementations
│   ├── build.py               # DotnetBuilder (compile + run with timeout kill)
│   ├── mcp_client.py          # MCP API client (generate + retrieve)
│   ├── llm_client.py          # LLM client (fix, decompose, commit msg, PR)
│   ├── error_parser.py        # Build output parser + regex pattern fixes
│   └── prompt_builder.py      # Prompt construction for retry stages
│
├── knowledge/
│   ├── rule_search.py         # Hybrid semantic + keyword KB search
│   ├── reranker.py            # LLM-based rule reranking
│   ├── error_catalog.py       # Error pattern → fix guidance matching
│   ├── error_fixes.py         # Scored error fix matching (confidence-weighted)
│   ├── fix_history.py         # Auto-recorded successful fix history
│   ├── auto_fixes.py          # Auto-learned fix persistence + promotion
│   ├── auto_learner.py        # Self-learning: extract rules from successful fixes
│   └── pattern_tracker.py     # Track recurring code transformations
│
├── git_ops/
│   ├── repo.py                # RepoManager (clone, pull, branch)
│   ├── committer.py           # CodeCommitter (write files, stage, commit)
│   ├── pr.py                  # PRManager (create PR, agents.md)
│   ├── github_api.py          # GitHub REST API v3 wrapper (files, PRs, tags, releases)
│   ├── agents_md.py           # Generate agents.md from batch results
│   ├── agents_content.py      # Domain knowledge + agents.md content generation
│   └── repo_docs.py           # Cumulative repo scanning + docs generation
│
├── routers/
│   ├── ui.py                  # HTML UI endpoint (serves index.html)
│   ├── jobs.py                # Job endpoints (start, sweep, version-bump, status, stream)
│   ├── files.py               # File upload endpoint
│   └── proxy.py               # Categories/tasks API proxy
│
├── templates/
│   └── index.html             # Web UI (Jinja2 + SSE + vanilla JS)
│
├── resources/
│   ├── kb.json                # Knowledge base rules
│   ├── error_catalog.json     # Error pattern catalog
│   ├── error_fixes.json       # Curated error fixes
│   ├── auto_fixes.json        # Auto-learned error fixes (generated)
│   ├── auto_error_catalog.json # Auto-learned catalog entries (generated)
│   └── auto_patterns.json     # Auto-promoted pattern fixes (generated)
│
├── requirements.txt           # Python dependencies
├── .env.example               # Environment variable template
├── fix_history.json           # Auto-generated fix history (capped at 500)
└── usage_reports.jsonl        # Local usage report log (one JSON line per run)
```

---

## Troubleshooting

| Issue | Solution |
|-------|----------|
| MSBuild glob errors (`MSB3552`) | Ensure no junk directories in project root. Build runs in isolated `_build/` subdirectory |
| Zombie `dotnet` processes | Fixed — the builder kills the entire process group on timeout |
| `'str' object has no attribute 'get'` in Stage 2 | Ensure `error_fixes.json` contains only dict entries (no string comment keys) |
| State lost on restart | Expected — state is in-memory only. Use CSV export to save results |
| Multi-worker state issues | Must run with `--workers 1`. State is not shared across processes |
| MCP API timeouts | Auto-retried 3 times with 2s backoff. Increase `MCP_TIMEOUT` if persistent |
