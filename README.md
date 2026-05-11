# Aspose.PDF for .NET — Examples Generator

Automated C# code generation and testing pipeline for **Aspose.PDF for .NET**. Generates working code examples via an MCP API, compiles and runs them with `dotnet`, and auto-fixes errors through a multi-stage retry pipeline. Results are persisted to disk with crash recovery and can be committed to GitHub with auto-generated pull requests.

---

## Table of Contents

- [Quick Start](#quick-start)
- [Architecture](#architecture)
- [Usage](#usage)
  - [Web UI](#web-ui)
  - [CLI](#cli)
  - [REST API](#rest-api)
- [Category Sweep Mode](#category-sweep-mode)
- [Parallel Generation](#parallel-generation)
- [Version Lifecycle](#version-lifecycle)
  - [Version Bump](#version-bump)
  - [Promote to Main](#promote-to-main)
  - [Full Release Workflow](#full-release-workflow)
- [PR Target Branch](#pr-target-branch)
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
- [Results Dashboard](#results-dashboard)
- [Rollback System](#rollback-system)
- [Project Structure](#project-structure)
- [Troubleshooting](#troubleshooting)

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
                    │  Build Monitor│  Jinja2 HTML + SSE
                    │   (port 7103) │  /
                    └──────┬───────┘
                           │
                    ┌──────┴───────┐
                    │   Results    │  Jinja2 HTML
                    │  Dashboard   │  /results-v2
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
              │  Persistence (disk)     │  results/{version}/
              │  Git Operations         │  clone, commit, PR
              └─────────────────────────┘
```

The system runs as a single-process FastAPI application. Jobs execute in daemon threads with thread-safe state management. Real-time updates stream to the UI via Server-Sent Events (SSE). Results are written to disk as they complete for crash recovery.

---

## Usage

### Web UI

Start the server and open `http://localhost:7103` in your browser. There are two pages:

- **Build Monitor** (`/`) — run the pipeline, monitor live progress
- **Results Dashboard** (`/results-v2`) — manage results, create PRs, regenerate metadata

#### Build Monitor

The UI has three modes:

| Mode | Description |
|------|-------------|
| **Single** | Enter a single task prompt, select category and product |
| **CSV** | Upload a CSV file with columns: `prompt`, `category`, `product` |
| **Task Generator** | Browse categories and select tasks from the external task API |

**Header Buttons:**
- **Results** — Navigate to Results Dashboard (`/results-v2`)
- **New Release** — Tag current version on main, create empty `release/{version}` staging branch, update `.env`

**Options:**
- **Create Pull Request** — Commit passed results to GitHub and create a PR
- **PR Target Branch** — Override which branch PRs merge into (e.g., `release/26.4.0`). Leave blank to use `REPO_BRANCH`
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

**Learned Rules Tab:**
- Review auto-learned rules with confidence score, hit count, and source stage
- **Approve** — Promote individual rule to curated `error_fixes.json`
- **Approve All** — Promote all auto-learned rules at once
- **Delete** — Remove a bad rule

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

# Version bump — tag old version, create staging branch, update .env
python cli.py --version-bump 26.4.0

# Promote staging branch to main
python cli.py --promote-to-main release/26.4.0 --version 26.4.0
```

**CLI Arguments:**

| Argument | Required | Default | Description |
|----------|----------|---------|-------------|
| `--task` | Yes* | — | Single task prompt text |
| `--csv` | Yes* | — | Path to CSV file (columns: `task`/`prompt`, `category`, `product`) |
| `--sweep` | Yes* | — | Sweep all tasks across categories |
| `--version-bump` | Yes* | — | Bump NuGet version (e.g., `26.4.0`) |
| `--promote-to-main` | Yes* | — | Promote staging branch to main (e.g., `release/26.4.0`) |
| `--version` | No | — | Version string for `--promote-to-main` |
| `--category` | No | `""` | Category for single task |
| `--categories` | No | `""` | Comma-separated category filter (sweep mode) |
| `--product` | No | `aspose.pdf` | Product name |
| `--repo-push` | No | `false` | Commit results and create PR |
| `--pr-target-branch` | No | `""` | Override PR base branch (e.g., `release/26.4.0`) |
| `--tfm` | No | `net10.0` | .NET target framework override |

*One of `--task`, `--csv`, `--sweep`, `--version-bump`, or `--promote-to-main` is required.

### REST API

All endpoints are served under the root path.

#### Job Management

| Endpoint | Method | Description |
|----------|--------|-------------|
| `POST /api/start` | Multipart form | Start single or CSV job |
| `POST /api/start-tasks` | JSON body | Start job from task list |
| `POST /api/start-sweep` | JSON body | Start category sweep job |
| `POST /api/version-bump` | JSON body | Tag old version, create staging branch, update `.env` |
| `POST /api/promote-to-main` | JSON body | Snapshot-promote staging branch to main, tag release, reset `.env` |
| `GET /api/status/{job_id}` | — | Poll job status |
| `GET /api/stream/{job_id}` | SSE | Real-time event stream |
| `POST /api/cancel/{job_id}` | — | Cancel a running job |
| `POST /api/pause/{job_id}` | — | Pause a running job |
| `POST /api/resume/{job_id}` | — | Resume a paused job |
| `POST /api/retry-pr/{job_id}` | — | Create or retry PR for completed job |
| `POST /api/retry-failed/{job_id}` | JSON body | Re-run failed tasks from a previous job |

#### Results Dashboard

| Endpoint | Method | Description |
|----------|--------|-------------|
| `GET /results-v2` | — | Results Dashboard UI (primary) |
| `GET /api/results` | — | List persisted disk results per category |
| `GET /api/results/all-categories` | — | Combined disk + repo view with status filters |
| `GET /api/results/sync-status` | — | Compare disk results with GitHub branch |
| `GET /api/results/{category}` | — | Detailed results for one category |
| `POST /api/create-pr-from-results` | JSON body | Create PR(s) from disk results (supports write mode) |
| `POST /api/regenerate-metadata` | JSON body | Regenerate missing metadata via LLM |
| `POST /api/update-repo-docs` | JSON body | Regenerate agents.md, index.json, README.md on repo |
| `POST /api/patch-pr-branch` | JSON body | Add agents.md + index.json to an existing PR branch that was missing them |

#### Learned Rules

| Endpoint | Method | Description |
|----------|--------|-------------|
| `GET /api/auto-fixes` | — | List auto-learned rules (confidence, hits, stage) |
| `POST /api/auto-fixes/{id}/approve` | — | Promote single auto rule to curated `error_fixes.json` |
| `POST /api/auto-fixes/approve-all` | — | Promote all auto-learned rules at once |
| `DELETE /api/auto-fixes/{id}` | — | Remove an auto-learned rule |

#### Data & Utilities

| Endpoint | Method | Description |
|----------|--------|-------------|
| `GET /api/health` | — | Health check |
| `GET /api/categories` | — | Fetch available categories from task API |
| `GET /api/tasks` | — | Fetch tasks by category |
| `POST /api/upload-files` | Multipart | Upload test input files |
| `GET /api/repo-categories` | — | List categories present on the repo branch |
| `POST /api/generate-category-docs` | JSON body | Generate agents.md + index.json for specific categories |
| `POST /api/generate-index-json` | JSON body | Regenerate index.json for a category from existing .cs files |

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
| `pr_target_branch` | form | No | Override PR base branch |
| `csv` | file | CSV mode | CSV file upload |

#### POST /api/create-pr-from-results — JSON Body

```json
{
  "categories": ["working-with-graphs"],
  "version": "26.4.0",
  "pr_style": "per-category",
  "pr_target_branch": "release/26.4.0",
  "write_mode": "replace"
}
```

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `categories` | array | all | Category slugs to include |
| `version` | string | config | NuGet version subfolder in `results/` |
| `pr_style` | string | `per-category` | `per-category` or `single` |
| `pr_target_branch` | string | config | Override PR base branch |
| `write_mode` | string | `replace` | `replace` (clean old files first) or `incremental` (add new only) |

#### POST /api/patch-pr-branch — JSON Body

```json
{
  "branch": "examples/abc123-accessibility-and-tagged-pdfs"
}
```

Reads `.cs` files already on the branch from GitHub, generates `agents.md` and `index.json`, then pushes them directly onto that branch. Useful when a PR was created before these sidecar files were included.

#### POST /api/start-tasks — JSON Body

```json
{
  "tasks": [
    {"task": "Save PDF", "category": "Basic Operations", "product": "aspose.pdf"},
    {"task": "Add bookmark", "category": "Bookmarks"}
  ],
  "repo_push": true,
  "force": false,
  "pr_target_branch": "release/26.4.0"
}
```

#### POST /api/start-sweep — JSON Body

```json
{
  "categories": ["Basic Operations", "Conversion"],
  "repo_push": true,
  "pr_target_branch": "release/26.4.0"
}
```

Processes ALL tasks for each selected category sequentially. Creates a usage report and PR (if `repo_push` is true) after each category.

#### POST /api/version-bump — JSON Body

```json
{
  "new_version": "26.4.0",
  "repo_push": true
}
```

Tags current `main` as `v{current_version}`, creates a GitHub Release, creates an empty orphan `release/{new_version}` branch (with `.github/workflows/` seeded from main so CI works immediately), and updates `.env` with new version and branch settings.

#### POST /api/promote-to-main — JSON Body

```json
{
  "staging_branch": "release/26.4.0",
  "new_version": "26.4.0"
}
```

Performs a **snapshot-promote** (not a PR merge). Takes the release branch's file tree, builds a new commit with that tree on top of `main`'s current HEAD, and fast-forwards `main` to it. This produces a clean, non-destructive one-commit diff — anyone who already cloned main can `git pull` cleanly. Then tags main as `v{new_version}`, creates a GitHub Release, and resets `.env` (`REPO_BRANCH=main`, `PR_TARGET_BRANCH` cleared).

#### POST /api/update-repo-docs — JSON Body

```json
{
  "update_readme": true
}
```

When `update_readme` is `true`, the README.md category listing is also updated. Only writes files when content meaningfully changes.

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
  "paused": false,
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
  "paused": false,
  "new_passed": [{"id": 12, "task": "...", "code": "..."}],
  "new_failed": [],
  "new_logs": ["[10:23:45] Task 12 passed (baseline)"],
  "pr_url": ""
}
```

A `done` event is sent when the job finishes.

---

## Category Sweep Mode

Sweep mode processes ALL tasks across selected (or all) categories in a single job. Unlike the normal Task Generator where you pick individual tasks, sweep auto-fetches everything from the tasks API.

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

## Parallel Generation

A full release touches hundreds of tasks across 30+ categories. Running them one-at-a-time through a single app instance takes hours. `scripts/parallel_run.py` is an orchestrator that spawns **N uvicorn workers on separate ports**, splits work across them using greedy bin-packing, and monitors everything from one terminal.

Each worker is a full app instance — so there are no code changes to the pipeline. The script uses the existing HTTP API (`/api/start-tasks`, `/api/status/{job_id}`) as the coordination layer. Results land in the shared `results/{version}/` directory.

```bash
# Run everything with 4 workers
python scripts/parallel_run.py --all --workers 4

# Only categories that have never been run for this release
python scripts/parallel_run.py --not-run --workers 4

# Next 2 categories that haven't been run yet
python scripts/parallel_run.py --not-run --limit 2 --workers 4

# Categories with incomplete results (some tasks still failing)
python scripts/parallel_run.py --needs-run --workers 3

# Retry all categories that have any failure
python scripts/parallel_run.py --all-failed --workers 2

# Natural language — LLM parses the intent
python scripts/parallel_run.py "run next 2 categories that are not run yet"
python scripts/parallel_run.py "retry failed in tables and forms"
```

**Status filters** mirror the Results Dashboard tabs (`Completed`, `Needs Run`, `Has Failed`, `Not Run`) — the script pulls live state from `/api/results/all-categories`. Combine any filter with `--limit N` to take only the first N categories.

**Worker isolation:** Each worker is spawned with `WORKSPACE_PATH=.parallel-workspaces/worker-N/` so concurrent workers don't share the `_build/` directory.

**Safety:**
- `repo_push` is always disabled for parallel runs — git isn't safe for concurrent use. Create PRs afterward via the Results Dashboard.
- Workers share the `results/` directory on disk; each task writes to its own file so there are no write conflicts.
- One category per worker — task-split mode was removed as it caused race conditions.
- Ctrl+C terminates all worker processes cleanly.

**Flow A — Merge release PRs as a human:**
```bash
# Update-branch + wait-for-CI + merge every green bot PR targeting release/<version>
python scripts/parallel_run.py --merge-release
```

See `scripts/README.md` for the full CLI reference and flag table.

---

## Version Lifecycle

### Version Bump

Prepares a new version release by preserving the old version and setting up a clean staging environment.

**What it does:**
1. **Tag** `main` as `v{current_version}` (e.g., `v26.3.0`) — read-only, does NOT modify main
2. **Create GitHub Release** from the tag
3. **Create** empty orphan branch `release/{new_version}` (no parent commits, completely clean)
4. **Seed** `.github/workflows/` from main onto the new release branch so CI is available immediately
5. **Update `.env`**: sets `NUGET_VERSION`, `PR_TARGET_BRANCH`, and `REPO_BRANCH` to the new values

**What it does NOT do:**
- Does not touch or modify the `main` branch in any way
- Does not delete or clean existing examples
- Does not run a sweep automatically — you trigger sweeps manually per category

**Access:**
- **UI:** Click **New Release** in the header → enter new version → confirm
- **CLI:** `python cli.py --version-bump 26.4.0`
- **API:** `POST /api/version-bump`

**After version bump:** Restart the app to load new `.env` settings. All subsequent PRs will automatically target `release/{new_version}`.

---

### Promote to Main

Promotes the completed staging branch to `main` once all category sweeps are done and reviewed. Uses a **snapshot-promote** strategy rather than a normal PR merge.

**Why snapshot-promote?** Release branches are orphans with no shared history with `main`. A normal PR merge would create a merge commit with two unrelated parents, which confuses `git log` and breaks `git pull` for anyone who already cloned main. Snapshot-promote instead creates a single new commit on top of main whose file tree exactly matches the release branch — one clean fast-forward.

**What it does:**
1. **Read** the release branch tree (all files as a single snapshot)
2. **Create** a new commit: `tree = release branch tree`, `parent = main HEAD`
3. **Fast-forward** `main` to the new commit via the GitHub API (non-destructive — no force push)
4. **Tag** the new main commit as `v{new_version}` + create GitHub Release
5. **Update `.env`**: resets `REPO_BRANCH=main`, clears `PR_TARGET_BRANCH`

The staging branch is **preserved** as a read-only archive — it is not deleted.

**Access:**
- **UI:** Click **Merge to Main** (Results Dashboard) — visible when `PR_TARGET_BRANCH` is set
- **CLI:** `python cli.py --promote-to-main release/26.4.0 --version 26.4.0`
- **API:** `POST /api/promote-to-main`

**After promotion:** Restart the app to load updated `.env`. Main now has the new version examples.

---

### Full Release Workflow

Complete end-to-end guide for releasing a new version (e.g., `26.4.0`):

```
Step 1 — Version Bump
  Click "New Release" → enter 26.4.0
  ├── Tags main as v26.3.0
  ├── Creates GitHub Release v26.3.0
  ├── Creates empty orphan branch: release/26.4.0
  ├── Seeds .github/workflows/ from main onto release/26.4.0
  └── Updates .env: NUGET_VERSION=26.4.0, PR_TARGET_BRANCH=release/26.4.0

  → Restart the app

Step 2 — Generate per category (repeat for all categories)
  Option A: Task Generator → select category → Sweep Selected
  Option B: python scripts/parallel_run.py --not-run --workers 4
  ├── Builds examples with Aspose.PDF 26.4.0
  ├── Results saved to results/26.4.0/{category}/
  ├── PRs target release/26.4.0
  └── Review and merge each category PR on GitHub

Step 3 — Promote to Main (when all categories are done)
  Click "Merge to Main" on Results Dashboard
  ├── Takes release/26.4.0 file tree
  ├── Creates one new commit on top of main (snapshot-promote)
  ├── Fast-forwards main — no force push, clean git pull for everyone
  ├── Tags main as v26.4.0
  ├── Creates GitHub Release v26.4.0
  └── Resets .env: REPO_BRANCH=main, PR_TARGET_BRANCH=(cleared)

  → Restart the app → main now has Aspose.PDF 26.4.0 examples
```

Old versions are permanently preserved via Git tags and GitHub Releases (`v26.3.0`, `v26.2.0`, etc.).

---

## PR Target Branch

Controls which branch all PRs merge into. This is the key setting for the release workflow.

| Setting | When to use |
|---------|-------------|
| Empty (default) | Normal operation — PRs target `REPO_BRANCH` (usually `main`) |
| `release/26.4.0` | Release workflow — PRs target the staging branch |

**How it flows:**
- Set via `PR_TARGET_BRANCH` in `.env`
- Override per-run in UI Options → **PR Target Branch** field
- Override per-run in API via `pr_target_branch` in request body
- Override per-run in CLI via `--pr-target-branch`

**Visual indicator:** The repo badge in the header shows the active target:
```
aspose-pdf/agentic-net-examples : main → release/26.4.0
```

Every PR creation path (single job, CSV, sweep, "Create PR from Results" button) uses `effective_pr_target`, which resolves to `PR_TARGET_BRANCH` if set, otherwise `REPO_BRANCH`.

---

## Usage Reporting

Every job run sends a usage report to a configurable endpoint (Google Apps Script) and/or logs it locally.

**Report payload includes:**
- Agent name, owner, job type, run ID
- Items discovered, succeeded, failed
- Run duration, LLM token usage, total API call count
- Product, platform, website metadata

Token usage is read from the `usage.total_tokens` field of each LiteLLM API response. MCP calls are tracked as call counts only (no token data available).

**Local logging:** Each report is appended as a JSON line to `usage_reports.jsonl` for local review before sending to remote. Failures are logged but never affect the pipeline.

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
| `MERGE_ACCT_GITHUB_TOKEN` | *(from .env)* | Personal PAT for human-attributed PR merges. Falls back to `REPO_TOKEN` if unset |

### Build Settings

Control how generated C# code is compiled and executed.

| Variable | Default | Description |
|----------|---------|-------------|
| `BUILD_TFM` | `net10.0` | .NET target framework moniker |
| `NUGET_PACKAGE` | `Aspose.PDF` | NuGet package name in `.csproj` |
| `NUGET_VERSION` | `26.4.0` | Aspose.PDF NuGet package version — updated automatically by Version Bump |
| `BUILD_TIMEOUT` | `30` | Max seconds for `dotnet build` |
| `RUN_TIMEOUT` | `30` | Max seconds for `dotnet run` |
| `BUILD_VERBOSITY` | `minimal` | dotnet build verbosity (`quiet`, `minimal`, `normal`, `detailed`) |
| `WORKSPACE_PATH` | `.` | Project root (build runs in `{WORKSPACE_PATH}/_build/` subdirectory) |

> **Note:** The build template uses `ImplicitUsings=enable` and `Nullable=enable` to match modern .NET project defaults. Generated code must use fully qualified type names where ambiguity exists (e.g., `Aspose.Pdf.Drawing.Path` vs `System.IO.Path`).

### Pipeline Settings

Fine-tune the retry behavior of the 5-stage pipeline.

| Variable | Default | Description |
|----------|---------|-------------|
| `USE_OWN_LLM` | `true` | Use own LLM key for Stage 1 code generation. When true, retrieves API docs via MCP then generates with LiteLLM. When false, MCP server handles generation |
| `LLM_FIX_ATTEMPTS` | `3` | Number of LLM code-fix attempts in Stage 2. Set to `0` to skip |
| `REGEN_ATTEMPTS` | `3` | Number of MCP regeneration attempts in Stage 4 |
| `RETRIEVE_LIMIT` | `20` | Max API documentation chunks to retrieve |
| `RETRIEVE_MAX_CHARS` | `12000` | Max characters in retrieved context |
| `USE_RETRIEVE_ON_LLM_FAIL` | `true` | Enable API retrieval in Stage 3 |
| `DECOMPOSE_ON_LLM_FAIL` | `false` | Enable LLM task decomposition in Stage 3 |
| `FINAL_LLM_AFTER_REGEN_FAIL` | `true` | Enable Stage 5 final LLM recovery |
| `RETRY_MODE` | `full` | `full` = use KB rules + error catalog; `simple` = minimal regen |
| `RESUME_BATCH` | `true` | Skip already-passed tasks on restart (crash recovery) |
| `AUTO_LEARN_ON_SUCCESS` | `true` | Auto-learn rules from mid-pipeline successful fixes |
| `AUTO_LEARN_CATALOG` | `true` | Also auto-expand the error catalog from successful fixes |
| `AUTO_LEARN_MIN_DIFF_LINES` | `3` | Minimum diff lines to trigger auto-learning |
| `LEARN_RULES_FROM_FAILURES` | `false` | Post-pipeline rule learning via the Anthropic API |

### MCP Settings

Configure the Model Context Protocol API for code generation and retrieval.

| Variable | Default | Description |
|----------|---------|-------------|
| `API_URL` | `http://172.20.1.175:7050/mcp/generate` | Code generation endpoint |
| `MCP_RETRIEVE_URL` | `http://172.20.1.175:7050/mcp/retrieve` | Documentation retrieval endpoint |
| `MCP_PRODUCT` | `pdf` | Product key sent to MCP |
| `MCP_PLATFORM` | `net` | Platform key sent to MCP |
| `MCP_RETRIEVAL_MODE` | `embedding` | Retrieval strategy |
| `MCP_RETRIEVAL_LIMIT` | `15` | Default retrieval limit |
| `MCP_TIMEOUT` | `60` | Request timeout (seconds) |

### LLM Settings

The LLM is used for code generation (when `USE_OWN_LLM=true`), code fixes, task decomposition, commit messages, and PR descriptions. Uses an OpenAI-compatible API via a LiteLLM proxy.

| Variable | Default | Description |
|----------|---------|-------------|
| `LITELLM_API_BASE` | `https://llm.professionalize.com/v1` | LLM API base URL |
| `LITELLM_API_KEY` | *(required)* | API key |
| `LITELLM_MODEL` | `gpt-oss` | Model name |
| `LLM_TIMEOUT` | `60` | Request timeout (seconds) |

**Optional — Anthropic (for post-pipeline rule learning):**

| Variable | Default | Description |
|----------|---------|-------------|
| `ANTHROPIC_API_KEY` | *(empty)* | Anthropic API key |
| `ANTHROPIC_MODEL` | `claude-sonnet-4-20250514` | Anthropic model for rule generalization |

### Git & PR Settings

Control how generated examples are committed and how PRs are created.

| Variable | Default | Description |
|----------|---------|-------------|
| `REPO_URL` | `https://github.com/aspose-pdf/agentic-net-examples.git` | Target GitHub repository |
| `REPO_PATH` | *(local path)* | Local clone path |
| `REPO_BRANCH` | `main` | Branch to check out and push commits to |
| `PR_TARGET_BRANCH` | *(empty)* | Branch PRs merge INTO — overrides `REPO_BRANCH`. Set to `release/26.4.0` during release workflow |
| `REPO_PUSH` | `false` | Auto-push commits (CLI override with `--repo-push`) |
| `REPO_TOKEN` | *(required for PR)* | GitHub PAT for bot account (pushes, PR creation) |
| `REPO_USER` | *(required for PR)* | Git author email |
| `MERGE_ACCT_GITHUB_TOKEN` | *(empty)* | Personal PAT for human-attributed PR approvals and merges |
| `BOT_GITHUB_LOGIN` | `agent-aspose-pdf-examples` | Bot's GitHub login — used to filter bot-authored PRs in merge scripts |
| `DEFAULT_CATEGORY` | `uncategorized` | Fallback category for tasks without one |
| `DEFAULT_PRODUCT` | `aspose.pdf` | Fallback product name |
| `PR_SPLIT_THRESHOLD` | `0` | Split PRs by category when file count exceeds this. `0` = disabled (single PR) |

#### PR Splitting

For large batch jobs (e.g., 2000+ tasks), a single PR becomes unwieldy. Set `PR_SPLIT_THRESHOLD` to split:

```bash
# Create one PR per category when batch produces > 200 files
export PR_SPLIT_THRESHOLD=200
```

When enabled, each category gets its own feature branch and PR. Branch naming: `examples/{category}-{uuid}`.

When `PR_SPLIT_THRESHOLD=0` (default), all files go into a single PR.

#### Repo Docs (agents.md)

The **Update Repo Docs** feature creates a separate PR with cumulative documentation:

- Scans all `.cs` files on the target branch
- Generates root `agents.md` with full example listing
- Generates per-category `agents.md` and `index.json` files
- Optionally updates the README.md category listing
- Only writes files when content meaningfully changes (avoids noise commits)

### Knowledge Base Settings

Control KB rule search and reranking behavior.

| Variable | Default | Description |
|----------|---------|-------------|
| `RULES_EXAMPLES_PATH` | `./resources/kb_new.json` | Knowledge base rules file |
| `ERROR_CATALOG_PATH` | `./resources/error_catalog.json` | Error pattern catalog |
| `ERROR_FIXES_PATH` | `./resources/error_fixes.json` | Curated error fixes |
| `FIX_HISTORY_PATH` | `./fix_history.json` | Auto-recorded successful fixes (capped at 500) |
| `AUTO_FIXES_PATH` | `./resources/auto_fixes.json` | Auto-learned error fix rules (pending review) |
| `AUTO_CATALOG_PATH` | `./resources/auto_error_catalog.json` | Auto-learned error catalog entries |
| `AUTO_PATTERNS_PATH` | `./resources/auto_patterns.json` | Auto-promoted pattern fixes |
| `RERANK_CANDIDATE_COUNT` | `100` | Initial candidates for LLM reranking |
| `RERANK_TOP_K` | `10` | Final top-K rules after reranking |
| `RERANK_ATTEMPT1_TOP_K` | `20` | Top-K for first regen attempt |
| `RERANK_TIMEOUT` | `20` | Reranking timeout (seconds) |

### External API Settings

| Variable | Default | Description |
|----------|---------|-------------|
| `CATEGORIES_API_URL` | `http://172.20.1.175:7061/api/categories` | Categories listing API |
| `TASKS_API_URL` | `http://172.20.1.175:7061/api/tasks` | Tasks listing API |
| `RESULTS_DIR` | `./results` | Base directory for persisted disk results |

---

## Pipeline Stages

Every task goes through a multi-stage pipeline that progressively applies more sophisticated fixes if the initial generation fails.

```
Task
 │
 ▼
┌─────────────────────────────┐
│  Stage 1: Baseline          │  Retrieve API docs (MCP) + generate (own LLM or MCP)
│  ✅ Success → Return        │  → dotnet build + dotnet run
│  ❌ Fail → Continue         │
└──────────────┬──────────────┘
               ▼
┌─────────────────────────────┐
│  Pattern Fix (loop ×5)      │  Regex-based deterministic fixes (error_parser.py)
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
│  Stage 3: Context Enrichment│  MCP /retrieve + optional task decomposition
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
│  ❌ Fail → Mark as FAILED   │  produced nothing usable
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

Auto-learned rules start at **0.5 confidence** (curated rules = 1.0). When an auto rule contributes to a successful fix, its confidence increases by 0.1 per hit (capped at 1.0). Confidence acts as a score multiplier during error fix matching.

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
| `POST /api/auto-fixes/approve-all` | — | Promote all auto rules at once |
| `DELETE /api/auto-fixes/{id}` | — | Remove a bad auto rule |

---

## PR Workflow

When `repo_push=true` is enabled, the pipeline commits results to GitHub:

1. **Clone/Pull** — `RepoManager` clones the repo (or pulls latest) with token auth
2. **Branch** — Creates a feature branch from `REPO_BRANCH` (e.g., `examples/batch-abc123`)
3. **Write Files** — Each passed example is saved as `{category}/{slug}.cs`
4. **Verify** — Each `.cs` file is compiled locally before commit (`_verify_cs_files_compile`)
5. **Sidecars** — `agents.md` and `index.json` generated per category and staged alongside `.cs` files
6. **Commit** — LLM generates a commit message summarizing the changes
7. **Push** — Branch pushed to origin
8. **Create PR** — LLM generates PR title + body, creates via GitHub API targeting `effective_pr_target`

**File naming:** Tasks are slugified (lowercase, special chars removed). If a file already exists, it auto-versions: `file__v2.cs`, `file__v3.cs`.

**PR target resolution:**
```
PR_TARGET_BRANCH (if set) → REPO_BRANCH → "main"
```

**Human-attributed merges:** The merge orchestrator uses `REPO_TOKEN` for Update Branch (bot action) and `MERGE_ACCT_GITHUB_TOKEN` for the actual merge — so the GitHub PR timeline shows a human reviewer, not the bot.

---

## Knowledge Base

The pipeline uses three knowledge sources to improve code generation in retry stages:

### KB Rules (`kb_new.json`)

Semantic search engine using SentenceTransformer (`all-MiniLM-L6-v2`) embeddings + IDF keyword matching. Each rule contains:
- `semantic_summary` — Natural language description
- `api_surface` — Relevant API types/members
- `rules` — Coding rules and constraints
- `warnings` — Common pitfalls

Search weighting: 55% semantic similarity + 45% keyword match.

### Error Catalog (`error_catalog.json`)

Regex-based pattern matching for common build errors. Each entry maps an error pattern to fix guidance text that's injected into the regeneration prompt.

### Error Fixes (`error_fixes.json`)

Curated database of real error→fix pairs. Scored by error code matches (3 pts) and key phrase matches (2 pts). Top 10 fixes are included as context for LLM and regeneration stages. Auto-learned fixes from `auto_fixes.json` are merged in at lower confidence.

### Auto-Generation Rules (`auto_generation_rules.json`)

Auto-generated from MCP `/retrieve` across all categories. Contains full API surface documentation — class signatures, method parameters, and usage patterns — organized by category. Generated by running:

```bash
python scripts/populate_generation_rules.py
python scripts/populate_generation_rules.py --categories "Basic Operations" "Conversion"
python scripts/populate_generation_rules.py --limit 30  # chunks per query
```

Re-run after each major NuGet version upgrade to pick up new APIs.

### Fix History (`fix_history.json`)

Auto-populated from successful fixes. Caps at 500 entries. Boosts future searches for similar error patterns, making the system learn from its own corrections over time.

---

## Results Dashboard

The Results Dashboard at `/results-v2` provides a post-run view of persisted disk results across all categories.

**Features:**
- **Per-category cards** with pass/fail/total counts and metadata quality badges
- **Status filters** — `All`, `Completed`, `Needs Run`, `Has Failed`, `Not Run`
- **Repo sync status** — compares disk results with GitHub branch (Synced / Partial / Pending badges)
- **Create PR from results** — push any category to the repo without re-running the pipeline
- **Write mode** — `Replace` (clean old files first) or `Incremental` (add new files only)
- **Regenerate metadata** — backfill missing titles, descriptions, tags, and API surface via LLM
- **Update Repo Docs** — regenerate root + per-category `agents.md`, `index.json`, and `README.md`
- **Merge to Main** — snapshot-promote staging branch to main, tag release, reset `.env`
- **Patch PR Branch** — add `agents.md` + `index.json` to an existing PR branch that was created without them

---

## Rollback System

`scripts/rollback.py` provides a CLI for undoing batch merge runs (Flow A) or promote-to-main operations (Flow B).

### Snapshots

Pre-flight snapshots are saved to `rollback_snapshots/` (gitignored) before running the merge orchestrator or promote-to-main. Each snapshot records the exact GitHub state (branch tips, tags, `.env` version) and is updated with the "after" state when the operation completes.

```bash
# List saved snapshots
python scripts/rollback.py list

# Inspect a snapshot
python scripts/rollback.py show latest
python scripts/rollback.py show latest-a   # most recent Flow A
python scripts/rollback.py show latest-b   # most recent Flow B

# Capture a manual snapshot before a merge run
python scripts/rollback.py snapshot --flow A

# Capture a manual snapshot before promote-to-main
python scripts/rollback.py snapshot --flow B
```

### Reverting

```bash
# Create revert PRs for every PR merged on the release branch since snapshot
python scripts/rollback.py revert-flow-a latest-a

# Revert the promote commit, delete the new tag/release
python scripts/rollback.py revert-flow-b latest-b

# Skip confirmation prompt
python scripts/rollback.py revert-flow-a latest-a --yes
```

All revert actions create PRs through normal merge flow — no force-push, no history rewrite — so repo rulesets are respected.

---

## Project Structure

```
aspose-pdf-api-v2/
├── main.py                    # FastAPI app entry point
├── cli.py                     # CLI (single, csv, sweep, version-bump, promote)
├── config.py                  # Typed configuration (dataclasses + env vars)
├── state.py                   # Thread-safe in-memory job state + SSE + pause/resume
├── jobs.py                    # Background job runners (run_pipeline, create_pr_from_results,
│                              #   regenerate_metadata, run_version_bump, run_promote_to_main)
├── persistence.py             # Versioned disk results (save, load, scan, update_task_metadata)
├── reporting.py               # Fire-and-forget usage reporting (remote POST + local JSONL)
│
├── pipeline/
│   ├── runner.py              # 5-stage pipeline orchestrator
│   ├── stages.py              # Individual stage implementations (use_own_llm path in Stage 1)
│   ├── models.py              # Data classes (TaskInput, PipelineResult, StageOutcome)
│   ├── build.py               # DotnetBuilder (compile + run, stale DLL protection)
│   ├── mcp_client.py          # MCP API client (generate + retrieve)
│   ├── llm_client.py          # LLM client (fix, decompose, generate_code, PR description)
│   ├── anthropic_client.py    # Anthropic API client (rule generalization)
│   ├── error_parser.py        # Build output parser + regex pattern fixes
│   ├── prompt_builder.py      # Prompt construction for retry stages + namespace restriction
│   └── usage_tracker.py       # Thread-safe token + API call counters per job
│
├── knowledge/
│   ├── rule_search.py         # Hybrid semantic + keyword KB search
│   ├── reranker.py            # LLM-based rule reranking
│   ├── error_catalog.py       # Error pattern → fix guidance matching
│   ├── error_fixes.py         # Scored error fix matching (confidence-weighted)
│   ├── fix_history.py         # Auto-recorded successful fix history (capped at 500)
│   ├── auto_fixes.py          # Auto-learned fix persistence + approve/approve-all/delete
│   ├── auto_learner.py        # Self-learning: extract rules from successful fixes via Anthropic API
│   └── pattern_tracker.py     # Track recurring code transformations → auto_patterns.json
│
├── git_ops/
│   ├── repo.py                # RepoManager (clone, pull, branch, _git_lock)
│   ├── committer.py           # CodeCommitter (write files, stage, commit + sidecar staging)
│   ├── pr.py                  # PRManager (create PR with LLM description)
│   ├── github_api.py          # GitHub REST API v3 wrapper (files, PRs, refs, tags, releases)
│   ├── agents_md.py           # Generate agents.md from batch results
│   ├── agents_content.py      # Category tips, API surface, anti-patterns content
│   └── repo_docs.py           # Cumulative repo scanning + docs generation
│
├── routers/
│   ├── ui.py                  # HTML UI endpoints (/, /results, /results-v2)
│   ├── jobs.py                # All job + results + auto-fixes endpoints
│   ├── results.py             # Results Dashboard page routes
│   ├── tasks.py               # /api/tasks proxy
│   ├── categories.py          # /api/categories proxy
│   ├── files.py               # /api/upload-files
│   └── health.py              # /api/health
│
├── templates/
│   ├── index.html             # Build Monitor UI (Jinja2 + SSE + vanilla JS)
│   ├── results.html           # Results Dashboard (legacy, /results)
│   └── results-v2.html        # Results Dashboard (current, /results-v2)
│
├── resources/
│   ├── kb.json                # Core knowledge base rules
│   ├── kb_new.json            # Extended knowledge base (active)
│   ├── kb_api.json            # API-surface KB entries
│   ├── generation_rules.json  # Curated generation rules (API usage constraints)
│   ├── auto_generation_rules.json  # Auto-generated rules from MCP /retrieve
│   ├── error_catalog.json     # Error pattern catalog (curated)
│   ├── error_fixes.json       # Curated error fixes
│   ├── auto_fixes.json        # Auto-learned error fixes (pending review)
│   ├── auto_error_catalog.json # Auto-learned catalog entries
│   └── auto_patterns.json     # Auto-promoted pattern fixes
│
├── scripts/
│   ├── parallel_run.py               # Parallel orchestrator — spawns N worker instances
│   ├── merge_release_prs.py          # Flow A — human-attributed batch merge of release PRs
│   ├── verify_passed.py              # Scan passed/ dirs, demote non-compiling .cs to failed/
│   ├── rollback.py                   # Rollback CLI (revert-flow-a, revert-flow-b)
│   ├── rollback_snapshot.py          # Snapshot capture/load helpers for rollback
│   └── populate_generation_rules.py  # One-time script to generate auto_generation_rules.json
│
├── requirements.txt           # Python dependencies
├── .env                       # Local environment (gitignored)
├── .env.production            # Production environment (gitignored)
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
| State lost on restart | Expected — state is in-memory only. Disk results in `results/` survive restart; use `RESUME_BATCH=true` to pick up where you left off |
| Multi-worker state issues | Must run with `--workers 1`. State is not shared across processes |
| MCP API timeouts | Auto-retried 3 times with 2s backoff. Increase `MCP_TIMEOUT` if persistent |
| PRs targeting wrong branch | Check `PR_TARGET_BRANCH` in `.env` and the **PR Target Branch** field in UI Options |
| Version bump — branch already exists | Safe to re-run — branch creation is skipped if already present |
| Promote to Main fails (non-fast-forward) | main has diverged from when the release branch was created. Check if main was force-pushed or reset, then resolve manually |
| CS0104 `Path` ambiguous reference | Code uses bare `Path` with `using Aspose.Pdf.Drawing;` — qualify as `Aspose.Pdf.Drawing.Path` or `System.IO.Path` |
| PR contains files from other categories | Fixed — per-category PRs use `git checkout . && git clean -fd` between iterations |
| Duplicate filenames overwriting in PRs | Fixed — `_write_examples_to_repo` deduplicates with `__v2`, `__v3` suffixes |
| Category names with underscores | Fixed — `normalize_category()` converts underscores to hyphens |
| Stale DLL false positives | Fixed — `--no-incremental` flag + unique AssemblyName per build + post-build DLL existence check |
| Passed .cs fails CI | Run `scripts/verify_passed.py` to demote any non-compiling files from `passed/` to `failed/` before creating a PR |
| PR branch missing agents.md / index.json | Use `POST /api/patch-pr-branch` with the branch name to generate and push the missing sidecar files |
| Parallel workers dying after a few tasks | Ensure `WORKSPACE_PATH=.parallel-workspaces/worker-N/` is set per worker (handled automatically by `parallel_run.py`) |
