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

## Testing

The repo has a layered test strategy. Different layers catch different classes of bugs and run at different speeds.

### Test Layers

| Layer | Location | What it covers | Speed |
|-------|----------|----------------|-------|
| **Unit** | `tests/test_*.py` | Pure functions, single modules, no I/O. Examples: config parsing, error pattern matching, build template generation. | <1s for all |
| **Integration** | `tests/integration/test_*.py` | FastAPI routers via `TestClient`, security middleware, disk-backed persistence, multi-module flows. | <2s for all |
| **Contract** *(planned)* | TBD | OpenAPI schema validation via `schemathesis` against `/openapi.json`. Catches drift between declared API and actual behaviour. | Slower |
| **Mutation** *(planned, informational)* | TBD | `mutmut` runs tests against deliberately broken code to verify the tests actually catch bugs. | Slow — runs weekly |

### Running Tests

```bash
make test         # all tests with coverage report (current ~66%, gate at 60%)
make test-fast    # all tests without coverage (faster, ~2s)
make check        # lint + test — full quality gate before pushing
make typecheck    # mypy informational check
make security     # bandit + pip-audit
```

Tests do not require external services (MCP server, LiteLLM, GitHub). Network calls are mocked via `monkeypatch` or the worker-function pattern (e.g. `monkeypatch.setattr("routers.jobs.run_pipeline", lambda *a, **k: None)`).

### Coverage Policy

- Gate enforced in [`pytest.ini`](./pytest.ini): `--cov-fail-under=60`
- Tracked modules listed explicitly in [`.coveragerc`](./.coveragerc) — adding a new module to coverage scope is a deliberate act
- Per-file gaps are listed in the `make test` output; aim to keep `routers/jobs.py` above 60%

### Adding a Test

| For this kind of change | Use this layer |
|-------------------------|----------------|
| New utility / pure function | Unit test |
| New API endpoint | Integration test + endpoint validation cases |
| New middleware | Integration test against a minimal `FastAPI()` |
| New router with disk reads | Integration test with `tmp_path` fixture and a schema-correct seeded results file |
| Schema-breaking change | Contract test (once `schemathesis` is wired up) |

## Quality Gates

Every PR runs the same gates locally (`make check`) and in CI:

1. **`ruff check .`** — zero violations required
2. **`bandit -c bandit.yaml -r . -lll`** — zero high-severity findings required
3. **`pip-audit -r requirements-ci.txt`** — informational; CVEs are reviewed in the PR
4. **`mypy --config-file mypy.ini .`** — informational; tightens over time
5. **`pytest tests/ --cov --cov-fail-under=60`** — all tests pass, coverage gate enforced

See [`.github/workflows/ci.yml`](./.github/workflows/ci.yml) and [`.gitlab-ci.yml`](./.gitlab-ci.yml) for the exact CI configuration.

### Optional: pre-commit hooks

Mirror the CI gates locally on every commit:

```bash
pip install pre-commit
pre-commit install
```

Configuration in [`.pre-commit-config.yaml`](./.pre-commit-config.yaml).

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

## Branch Protection & PR Workflow

`main` is protected on both GitHub and GitLab — direct pushes are blocked, CI must pass, and force pushes are disabled. See [`docs/branch-protection.md`](./docs/branch-protection.md) for the full policy and the machine-readable form in [`policy/`](./policy/). All changes must:

1. Land on a feature branch
2. Open a PR using the [PR template](./.github/PULL_REQUEST_TEMPLATE.md)
3. Pass the CI status check (`test` job — ruff + bandit + pytest)
4. Update [`CHANGELOG.md`](./CHANGELOG.md) under the current `[Unreleased]` section
5. Resolve all review conversations before merge

## Related Documentation

| Doc | Purpose |
|-----|---------|
| [`docs/architecture.md`](./docs/architecture.md) | System architecture and component boundaries |
| [`docs/deployment.md`](./docs/deployment.md) | Production deployment on the Windows VM |
| [`docs/runbook.md`](./docs/runbook.md) | On-call procedures, SLAs, common failure scenarios |
| [`docs/observability.md`](./docs/observability.md) | Prometheus scraping setup, Grafana dashboard import, alert rules |
| [`docs/ownership.md`](./docs/ownership.md) | RACI matrix, component owners, escalation path |
| [`docs/branch-protection.md`](./docs/branch-protection.md) | Branch protection policy (GitHub + GitLab) |
| [`SECURITY.md`](./SECURITY.md) | Vulnerability reporting policy |
| [`CHANGELOG.md`](./CHANGELOG.md) | All notable changes — update with every PR |

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
