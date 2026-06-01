# Contributing

## Prerequisites

- Python 3.12+
- .NET 10.0 SDK
- Git

## Local Setup

```bash
# Clone and enter the project
git clone <repo-url>
cd aspose-pdf-api-v2

# Create venv, install dependencies, and set up .env in one step
make install
make env        # copies .env.example → .env; edit with your API keys
```

## Required Environment Variables

Minimum to run locally:

| Variable | Description |
|----------|-------------|
| `LITELLM_API_KEY` | LLM proxy API key |
| `ANTHROPIC_API_KEY` | Claude API key (rule learning) |
| `REPO_PATH` | Local path to the examples git repo |
| `REPO_TOKEN` | GitHub PAT for pushing + creating PRs |

## Running the App

```bash
make run          # single worker — required, state is in-memory
make run-reload   # auto-reload for development
```

Open `http://localhost:7103` for the Build Monitor UI.

## Running Tests

```bash
make test         # run all tests with coverage report
make test-fast    # run tests without coverage (faster)
make check        # lint + test — full quality gate before pushing
```

Tests are unit tests only — they do not require external services (MCP server, LiteLLM, GitHub).

## Testing C# Rule Changes

To verify a C# code fix compiles before adding it as a rule:

```bash
mkdir /tmp/test-rule && cd /tmp/test-rule
# create a minimal .csproj and Program.cs with your fix
dotnet build && dotnet run
```

## Key Constraints

- **Single worker only** — `--workers 1` is mandatory; in-memory state is not shared across processes
- **Rules are lazy-loaded** — editing `resources/generation_rules.json` or `resources/error_fixes.json` takes effect on the next job, no restart needed
- **Git operations are serialized** — all git subprocess calls go through `_git_lock`; do not add concurrent git calls

## Project Structure

```
aspose-pdf-api-v2/
├── main.py          # FastAPI entry point
├── jobs.py          # Background workers, all pipeline workflow paths
├── config.py        # Typed dataclass config + env overrides
├── state.py         # In-memory state + SSE + pause/resume
├── pipeline/        # Build, MCP client, LLM client, error parser, stages
├── knowledge/       # KB search, error catalog, auto-learning
├── git_ops/         # Git commit/push, PR creation, GitHub API
├── routers/         # FastAPI route handlers
├── resources/       # generation_rules.json, error_fixes.json, kb.json
├── scripts/         # parallel_run.py, verify_passed.py, rollback.py
├── templates/       # Jinja2 HTML (Build Monitor UI)
└── tests/           # Unit tests (pytest)
```
