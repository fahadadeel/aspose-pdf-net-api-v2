# Data Handling

This document describes what data the service touches, how it's classified, where it lives, how long it's kept, and what it's shared with. It is **engineering-grade compliance documentation** — honest, auditable, and grounded in the actual code paths — not a SOC 2 / ISO 27001 / GDPR audit artefact. If formal compliance certification is required for a downstream use, treat this document as the input to that certification, not the certification itself.

## Scope

| In scope | Out of scope |
|----------|--------------|
| Data the running service reads, writes, or transmits | Data inside Aspose.PDF itself (the .NET library) |
| Storage on the production Windows VM | Storage on contributor laptops |
| Data sent to MCP, LiteLLM, GitHub | Data inside those upstream services after it leaves us |
| The auto-learned rule files | Aspose product analytics |

## Data classification

| Class | Definition | Examples in this service |
|-------|------------|--------------------------|
| **Public** | Safe to commit and publish freely | Generated C# examples, `index.json`, root `agents.md`, root `README.md`, the auto-learned rules in `resources/auto_*.json` once committed |
| **Internal** | Useful to operators, not for public release | Job logs, in-memory `BUILD_STATE`, `usage_reports.jsonl`, `fix_history.json` |
| **Confidential** | Limited to a named owner / on-call | None at this time |
| **Secret** | Credentials and tokens | `LITELLM_API_KEY`, `REPO_TOKEN`, `MERGE_ACCT_GITHUB_TOKEN`, `ANTHROPIC_API_KEY`, `POLICY_DRIFT_TOKEN`, `API_KEY` |

There is **no personal data** (PII), no end-user data, no payment data, no health data anywhere in the service. The pipeline consumes task prompts (machine-generated category names + task descriptions from the Tasks/Categories API) and produces C# code.

## Data inventory

### Generated examples (public)

| Field | Value |
|-------|-------|
| What | C# source files (`*.cs`) produced by the pipeline |
| Where | `results/{nuget_version}/{category}.json` on disk, then committed to `aspose-pdf/agentic-net-examples` on GitHub |
| Retention | Indefinite. Examples accumulate per release. Old versions tagged but never deleted |
| Encryption | None at rest (filesystem) and TLS in transit when pushed to GitHub |
| Public exposure | Full — this is the entire point of the service |

### Auto-learned rules (public)

| Field | Value |
|-------|-------|
| What | Pattern-fix transformations, error → suggestion mappings, error catalog entries learned from successful mid-pipeline fixes |
| Where | `resources/auto_fixes.json`, `resources/auto_error_catalog.json`, `resources/auto_patterns.json` |
| Retention | Indefinite. Committed to git on the generator repo. Manual review + approve / delete via the Results Dashboard |
| Sensitivity | Effectively zero — these are code patterns, not data about people. Anything sensitive in a fix would only be sensitive about the SOURCE pattern (e.g. a typo in Aspose API usage) |

### Job logs (internal)

| Field | Value |
|-------|-------|
| What | Pipeline progress messages emitted via `add_log()` in `state.py` |
| Where | In-memory `BUILD_STATE[job_id]["logs"]` (capped at 500 entries via `_MAX_LOGS` in `state.py`), streamed to UI via SSE |
| Retention | In-memory only — lost on service restart. **Not persisted to disk.** The recently merged Prometheus metrics are persisted in the Prometheus container's TSDB (30-day retention by default — see `compose.production.yaml`) |
| Sensitivity | Logs may contain task descriptions (e.g. "Convert PDF to HTML"). These are categorically not PII |

### Usage reports (internal)

| Field | Value |
|-------|-------|
| What | JSONL records of per-job aggregate stats: token counts, pass/fail counts, stage timings — see `reporting.py` |
| Where | `usage_reports.jsonl` on disk; optionally POSTed to an external endpoint configured via `REPORTING_ENDPOINT_URL` + `REPORTING_ENDPOINT_TOKEN` (Bearer header, never URL query string — fixed in `reporting.py` previously) |
| Retention | Indefinite on local disk. Remote endpoint retention is governed by the operator of that endpoint |
| Sensitivity | Aggregate counters, no personal data |

### Fix history (internal)

| Field | Value |
|-------|-------|
| What | Record of successful fixes per task — used to boost matching in `knowledge/rule_search.py` |
| Where | `fix_history.json` at repo root |
| Retention | Indefinite. Truncated by hand if the file grows large; no automatic policy |

### Secrets (secret)

| Field | Value |
|-------|-------|
| What | API keys, GitHub PATs, GitLab PATs, LLM proxy keys |
| Where | `.env` (gitignored) on the host, OS environment of the running service. Never logged. Never committed |
| Retention | Until rotated. See `docs/runbook.md` Secret Rotation section |
| Defence in depth | (1) `.env*` patterns in `.gitignore` (2) `bandit` SAST scans on every commit (`-lll`, blocking) (3) `git filter-repo` history scrub is documented for accidental commits (4) `reporting.py` moved its token from URL query string to `Authorization: Bearer` header |

## Data flows

External systems the service exchanges data with:

| System | Direction | What flows | Sensitivity |
|--------|-----------|------------|-------------|
| MCP server (`172.20.1.175:7050`) | both | Task prompts (out), generated code (in), retrieval queries (out), KB documents (in) | Public |
| LiteLLM proxy (`llm.professionalize.com`) | both | Code-fix prompts (out), LLM responses (in) | Public + Secret in headers |
| Anthropic API (Claude) | both | Post-pipeline rule-learning prompts (out), rule extractions (in) | Public + Secret in headers |
| GitHub (`aspose-pdf/agentic-net-examples`) | both | Generated `.cs` files + sidecar docs (out), PR/branch metadata (in) | Public + Secret in headers |
| GitLab (`gitlab.recruitize.ai`) | both | Source-repo MRs (out), CI logs (in) | Internal + Secret in headers |
| Tasks/Categories API (`172.20.1.175:7061`) | inbound | Category and task lists (in) | Public |
| Reporting endpoint (optional) | outbound | Usage aggregates (out) | Internal + Bearer header |

No system in this list is queried with end-user identifiers because there are no end-user identifiers in the service.

## Encryption posture

| Layer | Posture |
|-------|---------|
| In transit | All third-party APIs (LiteLLM, GitHub, GitLab, Anthropic) are TLS-only. MCP and Tasks/Categories API are internal HTTP at the moment — they live on a private network |
| At rest (Windows VM) | None. Filesystem-level encryption depends on the VM's BitLocker policy |
| At rest (container deployment) | None at the application layer. Docker volume encryption is the operator's choice |
| Secrets | Stored in `.env` plaintext; access controlled by filesystem permissions on the host |

## Retention summary

| Data | Lifecycle |
|------|-----------|
| Generated examples | Indefinite (versioned in git tags) |
| Auto-learned rules | Indefinite (versioned in git, manual review) |
| Job logs (in-memory) | Until restart, capped at 500 entries |
| Usage reports (disk JSONL) | Indefinite locally; remote endpoint controls its own retention |
| Prometheus metrics | 30 days (container deployment); not retained in the NSSM deployment |
| Fix history | Indefinite |
| Secrets | Until rotated |

## Deletion procedures

| Need | How |
|------|-----|
| Forget a specific category | Delete the category folder + entry in `index.json`; commit; `Update Repo Docs` regenerates the agents.md |
| Forget an auto-learned rule | Reject + delete via the Results Dashboard auto-fixes review, OR edit `resources/auto_*.json` and commit |
| Clear job state | Restart the service (`nssm restart AsposePdfApi` or `docker compose restart app`) |
| Clear Prometheus history | `docker volume rm aspose-pdf-api-v2_prometheus-data` |
| Rotate a secret | Procedure in [`docs/runbook.md#secret-rotation`](./runbook.md#secret-rotation) |
| Scrub a leaked secret from git history | Procedure documented in `docs/runbook.md`, uses `git filter-repo --replace-text` with the branch protection bypass documented in [`docs/branch-protection.md`](./branch-protection.md) |

## Compliance posture — what this satisfies and doesn't

| Standard | Status |
|----------|--------|
| Engineering-grade data inventory | ✅ This document |
| Engineering-grade retention policy | ✅ This document |
| Engineering-grade deletion procedures | ✅ This document |
| Documented secret-rotation runbook | ✅ See [`docs/runbook.md`](./runbook.md) |
| SAST + dependency scanning in CI | ✅ `bandit` blocking on high-severity, `pip-audit` informational |
| Branch protection + policy-as-code | ✅ See [`docs/branch-protection.md`](./branch-protection.md), [`policy/`](../policy/) |
| Documented access control matrix | ✅ See [`docs/access-control.md`](./access-control.md) |
| SOC 2 Type II attestation | ❌ Would require formal audit + ongoing evidence collection. Not undertaken |
| ISO 27001 certification | ❌ Same |
| GDPR data-processor agreement | ❌ No PII in scope — agreement not applicable |
| HIPAA BAA | ❌ No PHI in scope — agreement not applicable |
| PCI DSS | ❌ No cardholder data in scope — controls not applicable |

The `❌` rows are not gaps in this service — they're attestation frameworks designed for different problem domains and would be inapplicable here even if pursued.

## Operator responsibilities

- Keep `.env` permissions restrictive (`chmod 600` on Linux; equivalent NTFS ACL on the Windows VM)
- Rotate secrets on a calendar (recommend every 90 days) or immediately on suspected leak
- Review and approve auto-learned rules via the Results Dashboard before they accumulate
- Apply OS-level patches on the Windows VM / container host
- Keep `requirements.txt` versions current — Dependabot proposes upgrades; you decide

## Changes to this document

This file is reviewed alongside any change that:
- Adds a new data store (in-memory, on disk, or third-party)
- Adds a new external system the service talks to
- Changes the retention of an existing data class
- Adds a new secret

CHANGELOG entries that touch any of those should include a note that this document was reviewed and either left unchanged or updated.
