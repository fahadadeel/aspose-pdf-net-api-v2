# Architecture

## Overview

Aspose PDF API v2 is a Python-based pipeline that automatically generates, compiles, and tests C# code examples for Aspose.PDF for .NET. Successful examples are committed to a separate GitHub repository with auto-generated pull requests.

```
┌─────────────────────────────────────────────────────────────┐
│                        FastAPI App                          │
│          Build Monitor UI  ·  Results Dashboard             │
└────────────────────────┬────────────────────────────────────┘
                         │
              ┌──────────▼──────────┐
              │    Job Workers      │  (background threads)
              │    jobs.py          │
              └──────────┬──────────┘
                         │
              ┌──────────▼──────────┐
              │   PipelineRunner    │
              │   pipeline/runner.py│
              └──────────┬──────────┘
                         │
         ┌───────────────┼───────────────┐
         │               │               │
    ┌────▼────┐    ┌──────▼─────┐  ┌────▼────────┐
    │   MCP   │    │   dotnet   │  │  LLM Client │
    │ /generate│   │ build + run│  │  (fix/regen)│
    └─────────┘    └────────────┘  └─────────────┘
         │
    ┌────▼──────────────┐
    │   git_ops/        │
    │  commit · push    │
    │  PR creation      │
    └───────────────────┘
```

## Pipeline Stages

Each job runs through up to 6 stages, stopping as soon as one succeeds:

| Stage | Description |
|-------|-------------|
| **1. Baseline** | MCP `/generate` → `dotnet build` + `dotnet run` |
| **2. Pattern Fix** | Regex-based fixes for known error patterns |
| **3. LLM Fix** | LLM code repair loop (`LLM_FIX_ATTEMPTS`, default 0) |
| **4. Context Enrichment** | MCP `/retrieve` + LLM task decomposition |
| **5. Regeneration** | MCP regen with KB rules + error catalog (3 attempts) |
| **6. Final LLM Recovery** | One last LLM fix attempt |

## Key Components

### `pipeline/`
- **`runner.py`** — orchestrates all stages in order
- **`build.py`** — writes `.csproj` + `Program.cs`, runs `dotnet build` and `dotnet run`
- **`mcp_client.py`** — calls MCP `/generate` and `/retrieve`
- **`llm_client.py`** — OpenAI-compatible chat for code repair and PR descriptions
- **`error_parser.py`** — extracts compiler errors, applies regex pattern fixes
- **`prompt_builder.py`** — builds enriched prompts for retry stages

### `knowledge/`
- **`rule_search.py`** — hybrid semantic + keyword search over `kb.json`
- **`error_catalog.py`** — maps error patterns to fix guidance
- **`auto_learner.py`** — learns new fixes from successful pipeline runs
- **`fix_history.py`** — tracks and boosts previously successful fixes

### `git_ops/`
- **`repo.py`** — clone/pull/branch management with serialized git lock
- **`committer.py`** — writes `.cs` files, commits, pushes, generates sidecar docs
- **`pr.py`** — creates pull requests with LLM-generated descriptions
- **`github_api.py`** — GitHub REST API v3 wrapper

### `resources/`
- **`kb.json`** — ~200+ knowledge base rules (semantic search)
- **`generation_rules.json`** — proactive rules injected into generation prompts
- **`error_fixes.json`** — curated code fixes matched against compiler errors
- **`auto_error_catalog.json`** / **`auto_fixes.json`** — auto-learned entries

## State Management

The app is **fully in-memory** — no database.

- `JOB_LOCK` — protects the `BUILD_STATE` dict across threads
- `_git_lock` — serializes all git subprocess calls
- `JOB_PAUSE_EVENTS` — `threading.Event` per job for pause/resume

**Critical**: always run with `--workers 1`. State is not shared between processes.

## Data Flow

```
Task input
    │
    ▼
MCP generate (C# code)
    │
    ▼
dotnet build + run ──► success ──► commit to examples repo ──► PR
    │
    ▼ (on failure)
Pattern fix ──► retry build
    │
    ▼ (on failure)
LLM fix ──► retry build
    │
    ▼ (on failure)
MCP retrieve + enrich ──► regen ──► retry build
    │
    ▼ (on failure)
Mark as failed
```
