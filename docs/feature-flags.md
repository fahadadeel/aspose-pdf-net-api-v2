# Feature Flags

The pipeline has a number of boolean toggles that change behaviour at runtime — whether to auto-learn from successes, whether to run the final LLM recovery stage, whether to push usage reports remotely, and so on. Before this mechanism existed each toggle was scattered across `config.py`, env vars, and conditionals in `jobs.py`/`pipeline/` with no single inventory.

The feature flag mechanism collects all of these into one declared registry, gives them owners, defaults, and descriptions, and exposes a single API (`features.is_enabled(name)`) for checking them.

## Source of truth

**[`resources/feature_flags.json`](../resources/feature_flags.json)** — every flag must be declared here before being used in code. Each entry has:

| Field | Purpose |
|-------|---------|
| `description` | One-line explanation of what the flag controls |
| `owner` | Person responsible for the gated behaviour |
| `default` | The value used when no env-var override is set |
| `env_var` | Name of the env var that overrides at runtime |
| `scope` | Logical area: `pipeline`, `git`, `persistence`, `reporting`, etc. |
| `added` | Date the flag was introduced (YYYY-MM-DD) |

## API

```python
from features import is_enabled

if is_enabled("auto_learn_on_success"):
    # learn from this successful fix
    ...
```

Resolution order (also documented in `_resolution_order` inside the JSON):

1. **Env var override** — if `env_var` is declared and set in the process environment, use it. Truthy values: `true`, `1`, `yes` (case-insensitive). Anything else is falsy.
2. **Registry default** — the `default` field on the flag entry.
3. **Caller-provided fallback** — only used if the flag is undeclared *and* the caller passed `default=`.

An undeclared flag with no caller default raises `KeyError` — declaration is mandatory.

Other helpers:

- `features.get_flag(name)` → the registry entry, or `None` if undeclared
- `features.list_flags()` → the full registry as a dict
- `features.snapshot()` → `{name: bool}` of all flags with currently-resolved values
- `features.refresh()` → clear the in-memory cache (used in tests / after live edits)

## Inspecting at runtime

`GET /api/feature-flags` returns the full registry with resolved values. Useful for ops dashboards, deployment verification, and debugging "why is X off in production":

```json
{
  "count": 11,
  "flags": [
    {
      "name": "auto_learn_on_success",
      "enabled": true,
      "default": true,
      "env_var": "AUTO_LEARN_ON_SUCCESS",
      "owner": "Fahad Adeel",
      "scope": "pipeline",
      "description": "Learn reusable fix rules from mid-pipeline successful fixes...",
      "added": "2026-06-10"
    },
    ...
  ]
}
```

## Adding a new flag

1. Open `resources/feature_flags.json` and add an entry under `flags`:

   ```json
   "my_new_toggle": {
     "description": "Short explanation of what this controls.",
     "owner": "Your Name",
     "default": false,
     "env_var": "MY_NEW_TOGGLE",
     "added": "2026-06-15",
     "scope": "pipeline"
   }
   ```

2. Reference it in code via `features.is_enabled("my_new_toggle")`.

3. If the flag changes pipeline behaviour, add a CHANGELOG entry under `Added` or `Changed`.

4. Add a test that covers both states (env override on / off).

## Why a registry instead of just env vars

- **Discoverability** — one file lists every behaviour toggle the service understands. Onboarding doesn't require grepping `os.getenv()` across the codebase.
- **Documentation** — each flag carries `description`, `owner`, and `scope` next to its default value, instead of those living in committed code comments that drift.
- **Audit-friendly** — the registry is policy-as-code for runtime behaviour. Changes to defaults are reviewable as a JSON diff.
- **Inspectable in production** — `/api/feature-flags` lets ops verify resolved values against expectations without shelling onto the host.
- **Compatible with existing env vars** — every flag still respects its declared env var, so existing `.env` files and CI variables keep working unchanged.

## Existing flags

See the [`resources/feature_flags.json`](../resources/feature_flags.json) file for the canonical list. As of 2026-06-10 it covers:

- **Pipeline behaviour:** `use_own_llm`, `use_retrieve_on_llm_fail`, `decompose_on_llm_fail`, `final_llm_after_regen_fail`, `auto_learn_on_success`, `auto_learn_catalog`, `learn_rules_from_failures`
- **Git:** `update_agents_md`
- **Persistence:** `resume_batch`
- **Reporting:** `reporting_enabled`, `reporting_log_to_file`
