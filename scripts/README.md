# Scripts

Utility scripts for the Aspose.PDF example generation pipeline.

## parallel_run.py — Parallel Orchestrator

Spawns multiple uvicorn instances on different ports and distributes categories across them for parallel example generation. Supports natural language commands via LLM.

### Quick Start

```bash
# Activate the venv first
source .venv/bin/activate

# Run all categories with 4 parallel workers
python scripts/parallel_run.py --all --workers 4

# Natural language (requires LITELLM_API_KEY in .env)
python scripts/parallel_run.py "run tables and forms with 2 workers"

# Retry all failed tasks across categories
python scripts/parallel_run.py --all-failed --workers 2

# Run only categories that haven't been run yet (mirrors the "Not Run" filter on the dashboard)
python scripts/parallel_run.py --not-run --workers 4

# Run the next 2 categories that haven't been run yet
python scripts/parallel_run.py --not-run --limit 2 --workers 4
# …or natural language
python scripts/parallel_run.py "run next 2 categories that are not run yet"

# Run only categories with incomplete results (some tasks still pending)
python scripts/parallel_run.py --needs-run --workers 3

# Specific categories
python scripts/parallel_run.py --categories "Tables in PDF,Forms,Annotations" -w 3

# Skip confirmation prompt
python scripts/parallel_run.py --all -w 4 -y
```

### How It Works

1. **Fetches categories** from the external API (`172.20.1.175:7001/api/categories`)
2. **Parses intent** — either from CLI flags or natural language via `gpt-oss` LLM
3. **Balances categories** across workers using greedy bin-packing (sorts by task count desc, assigns each to the lightest worker)
4. **Spawns N uvicorn instances** on ports 7110, 7111, 7112, ... (each is an independent app instance)
5. **Submits jobs** via `POST /api/start-tasks` to each instance
6. **Monitors progress** by polling `/api/status/{job_id}` with a live terminal dashboard
7. **Cleans up** — terminates all uvicorn instances on completion or Ctrl+C

### Architecture

```
parallel_run.py
  ├── Worker 1 (port 7110) → /api/start-tasks {categories: [A, B, C]}
  ├── Worker 2 (port 7111) → /api/start-tasks {categories: [D, E, F]}
  ├── Worker 3 (port 7112) → /api/start-tasks {categories: [G, H, I]}
  └── Worker 4 (port 7113) → /api/start-tasks {categories: [J, K, L]}
```

- **Zero code changes** to the main app — uses the HTTP API as the coordination layer
- Each instance is a full uvicorn server with `--workers 1` (required for in-memory state)
- Results are written to the shared `results/` directory on disk
- Git push is always disabled (`repo_push: False`) — git isn't safe for concurrent use
- Create PRs after all workers finish via the Results Dashboard

### CLI Options

| Flag | Default | Description |
|------|---------|-------------|
| `command` | — | Natural language command (parsed by LLM) |
| `--categories` | — | Comma-separated category names |
| `--all` | false | Run all available categories |
| `--all-failed` | false | Retry all categories with failures |
| `--not-run` | false | Run only categories that have never been run for this release (dashboard "Not Run") |
| `--needs-run` | false | Run only categories with incomplete results (dashboard "Needs Run") |
| `--completed` | false | Run only fully-completed categories (dashboard "Completed") |
| `--limit`, `-n` | — | Take only the first N categories after filtering (works with `--not-run`, `--needs-run`, etc.) |
| `--workers`, `-w` | 4 | Number of parallel workers |
| `--base-port` | 7110 | Starting port for worker instances |
| `--yes`, `-y` | false | Skip confirmation prompt |
| `--retry` | false | Retry failed tasks instead of new generation |
| `--merge-release` | false | Update + merge all green bot-authored PRs targeting the release branch |
| `--pr` | — | Specific PR number(s) to merge (repeatable); implies `--merge-release` |
| `--dry-run` | false | For `--merge-release`: print the merge plan and exit without merging |

### Natural Language Examples

The LLM parses these into structured intents:

- `"run all categories with 4 workers"` → runs everything
- `"retry failed in tables and forms"` → retries just those categories
- `"generate annotations and bookmarks examples using 2 workers"` → specific categories
- `"retry all failed categories with 3 workers"` → retry mode for all failures
- `"merge all passing release PRs"` → Flow A merge mode
- `"merge PR 192 and 207"` → Flow A merge mode, specific PRs only

### Merge Release Mode (Flow A)

The `--merge-release` flag (or any "merge release PRs" natural-language
command) runs a separate flow that does not spawn uvicorn workers.
Instead it:

1. Queries GitHub for open PRs targeting the effective release branch,
   filtered to `BOT_GITHUB_LOGIN`.
2. Fetches per-PR mergeable state + CI status and drops any that are
   conflicting or red.
3. Shows a plan table and asks for confirmation.
4. For each PR sequentially: calls Update Branch (bot token) → waits
   for CI → merges via `merge_pull_request` using
   `MERGE_ACCT_GITHUB_TOKEN` so the event is attributed to a human.
5. Prints a final merged/skipped/failed summary.

```bash
# Preview only — no merges
python scripts/parallel_run.py --merge-release --dry-run

# Merge everything green, with confirmation prompt
python scripts/parallel_run.py --merge-release

# Merge specific PRs only
python scripts/parallel_run.py --pr 192 --pr 207 -y

# Natural language
python scripts/parallel_run.py "merge all passing release PRs"
```

Requires `MERGE_ACCT_GITHUB_TOKEN` in `.env` for human-attributed
merges. Without it, merges still run but are attributed to the bot.

### Dependencies

No new dependencies — uses `requests` and `python-dotenv` which are already installed. Requires `LITELLM_API_KEY` in `.env` for natural language mode.

---

## verify_passed.py — Post-Build Verifier

Scans all PASSED `.cs` files in the results directory and verifies they still compile. Demotes false positives to `failed/`.

```bash
# Dry run (no changes)
python scripts/verify_passed.py --dry-run

# Verify a specific category
python scripts/verify_passed.py --category tables_in_pdf

# Full scan
python scripts/verify_passed.py
```

---

## populate_generation_rules.py — Rules Populator

Fetches API documentation from the MCP server and populates `resources/generation_rules.json`.

```bash
python scripts/populate_generation_rules.py
```
