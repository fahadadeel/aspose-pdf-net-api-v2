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
| `--workers`, `-w` | 4 | Number of parallel workers |
| `--base-port` | 7110 | Starting port for worker instances |
| `--yes`, `-y` | false | Skip confirmation prompt |
| `--retry` | false | Retry failed tasks instead of new generation |

### Natural Language Examples

The LLM parses these into structured intents:

- `"run all categories with 4 workers"` → runs everything
- `"retry failed in tables and forms"` → retries just those categories
- `"generate annotations and bookmarks examples using 2 workers"` → specific categories
- `"retry all failed categories with 3 workers"` → retry mode for all failures

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
