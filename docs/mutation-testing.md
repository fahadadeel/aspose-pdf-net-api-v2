# Mutation Testing

> **Active schedule:** Weekly, Thursdays at 12:55 Asia/Karachi (`55 12 * * 4`). Configured via GitLab Pipeline Schedule `"Mutation testing (Thursday)"`.

Mutation testing measures **test quality** — how good your tests are at catching bugs — by introducing tiny intentional bugs into the source code and checking whether tests fail. A test suite that catches lots of mutations is a real safety net; one that misses them is exercising lines without verifying behaviour.

The Recruitize.AI agent treats mutation testing as a **P8 Proactive** signal alongside contract tests, dependabot, and feature flags.

## How it works in this repo

| Aspect | Detail |
|--------|--------|
| Tool | [`mutmut==3.6.0`](https://mutmut.readthedocs.io/) |
| Config | `[mutmut]` section in [`setup.cfg`](../setup.cfg) |
| Initial scope | `pipeline/error_parser.py`, `pipeline/prompt_builder.py`, `pipeline/models.py`, `middleware/security.py`, `knowledge/error_fixes.py`, `knowledge/pattern_tracker.py`, `routers/health.py` |
| CI job | `mutation-tests` stage in [`.gitlab-ci.yml`](../.gitlab-ci.yml) |
| Cadence | Scheduled weekly — currently `55 12 * * 4` (Thursdays at 12:55 Asia/Karachi) |
| Blocking? | No — output is informational, uploaded as a CI artifact |

The scope is intentionally narrow: stable, high-coverage, pure-logic modules where surviving mutations almost always indicate real test gaps. Expand the list in `setup.cfg` as test depth on other modules grows.

## Safety

- Mutations are applied in CI containers, not your dev tree
- Each mutated file is restored automatically after the test run
- `mutants/` and `mutmut-report.txt` are gitignored
- The CI job never touches `resources/*.json`, `.env`, git history, or the example-generation pipeline
- Worst-case interrupted runs leave mutated files in `mutants/` — never in the source tree

## Enabling the scheduled run

The CI job runs only when triggered by a Pipeline Schedule with `RUN_MUTATION_TESTS=true`. The schedule is already configured — these steps are kept for reference when changing cadence or recreating after a project move.

1. Go to **Project → Build → Pipeline Schedules**
   `https://gitlab.recruitize.ai/sialkot/faisalabad-openize/aspose-pdf-net-api-v2/-/pipeline_schedules`
2. Click **New schedule**
3. Fill in:

   | Field | Value |
   |-------|-------|
   | Description | `Mutation testing (Thursday)` |
   | Interval Pattern | Custom (Cron) — `55 12 * * 4` (Thursdays 12:55) |
   | Cron Timezone | Asia/Karachi |
   | Target Branch | `main` |
   | Variables | Add `RUN_MUTATION_TESTS` = `true` |
   | Activated | ✓ |

4. **Save pipeline schedule**

The schedule fires at the configured time. Look for the `mutation-tests` job under that pipeline. Download `mutmut-report.txt` from the job artifacts to review survived mutations.

**GitLab cron worker constraint:** the platform's schedule worker only wakes at minutes matching `3-59/10 * * * *` (i.e. 3, 13, 23, 33, 43, 53). GitLab rejects a cron with minute `0` as "syntax invalid". Other minutes are accepted, but the actual run fires at the *next* worker wake after the configured minute — e.g. minute `55` fires at minute `03` of the following hour. Pick a minute from `{3, 13, 23, 33, 43, 53}` for exact-minute timing.

## Reading the report

```text
Killed:    142  (88%)   ← tests caught the bug
Survived:   19  (12%)   ← tests didn't catch the bug
Timeout:     0
Suspicious: 0
Skipped:    0
```

Then for each survived mutation, mutmut shows the diff so you can decide:

- **Add a test** that would catch this mutation (improves real coverage)
- **Mark as equivalent** if the mutation is functionally identical to the original
- **Accept the gap** for cases where catching it would be over-testing

Survived mutations are a **TODO list for test quality**, not a CI failure.

## Running locally (optional)

```bash
make mutation        # full scope, slow
```

Or for one module:

```bash
.venv/bin/python -m mutmut run --paths-to-mutate pipeline/error_parser.py
.venv/bin/python -m mutmut results
```

Mutmut writes `mutants/`, `mutmut-report.txt`, and `.mutmut-cache` in the project root — all gitignored.

## Expanding scope

When you want to add a module to the mutation suite:

1. Verify the module's `pytest` coverage is comfortably above 80%
2. Add the path to `source_paths` in `setup.cfg`
3. Run `make mutation` locally once to see survived-mutation rate
4. If the rate is reasonable (under ~20%), the addition is sustainable

## Why P8

The Recruitize.AI calibration calls out mutation testing as a P8 criterion because it is one of the few verifiable proxies for **test depth in substance**, not just line coverage. A repo with 90% line coverage but 60% mutation score has tests that exercise the code without checking outcomes. A repo with 90%/90% has tests that actually catch regressions.
