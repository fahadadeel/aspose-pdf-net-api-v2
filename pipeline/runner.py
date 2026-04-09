"""
pipeline/runner.py — PipelineRunner: orchestrates the 5-stage retry pipeline.

Framework-agnostic: no FastAPI, no threading, no state.py dependencies.
Usable from CLI, API, or UI modes.
"""

import json
import re
import threading
from pathlib import Path
from typing import Callable, Optional

from config import AppConfig
from pipeline.models import TaskInput, PipelineResult
from pipeline.build import DotnetBuilder
from pipeline.mcp_client import MCPClient
from pipeline.llm_client import LLMClient
from pipeline.error_parser import detect_and_fix_known_patterns, extract_errors, parse_error_codes
from pipeline import stages
from pipeline.prompt_builder import build_namespace_restriction
from knowledge.rule_search import RuleSearchEngine
from knowledge.error_catalog import load_error_catalog
from knowledge.error_fixes import load_error_fixes, match_error_fixes, format_error_fixes_for_prompt
from knowledge.auto_learner import AutoLearner, load_auto_error_catalog


_ALWAYS_INCLUDE = {
    "limit-collections-to-four-elements-evaluation-mode",
    "no-blocking-calls-no-readline-no-watchers",
    "no-var-use-explicit-types",
    "no-external-frameworks-console-app-only",
    "no-unit-test-frameworks-write-console-app",
    "self-contained-examples-create-sample-pdf",
    "document-disposal-with-using",
    "page-indexing-one-based",
    "collection-indexing-one-based",
}

_STOP_WORDS = {
    "the", "and", "for", "not", "use", "does", "that", "with", "from",
    "this", "are", "has", "have", "can", "will", "new", "get", "set",
    "add", "all", "any", "class", "type", "name", "using", "method",
    "property", "instead", "never", "always", "must", "should", "correct",
    "wrong", "error", "could", "found", "missing", "directive", "assembly",
    "reference", "definition", "accessible", "extension", "accepting",
    "argument", "first", "does", "contain", "exist", "namespace",
    "aspose", "pdf", "document", "page", "pages", "file", "save", "load",
    "open", "create", "output", "input", "system", "string", "object",
    "instance", "abstract", "constructor", "parameter", "value",
    "example", "generate", "write", "read", "make", "show", "display",
}


def _extract_keywords(text: str) -> set:
    """Extract domain-specific keywords after CamelCase splitting + stop word removal."""
    expanded = re.sub(r"([a-z])([A-Z])", r"\1 \2", text)
    expanded = re.sub(r"[-_./]", " ", expanded)
    words = set(re.findall(r"[a-z][a-z0-9]{2,}", expanded.lower()))
    return words - _STOP_WORDS


def _shorten_note(note: str, max_len: int = 200) -> str:
    """Truncate a rule note to first 1-2 sentences, capped at max_len."""
    sentences = re.split(r"(?<=[.!]) ", note)
    short = sentences[0]
    if len(sentences) > 1 and len(short) + len(sentences[1]) + 1 < max_len:
        short = short + " " + sentences[1]
    return short[:max_len] if len(short) > max_len else short


def _format_rules_block(rules: dict, task: str = "", category: str = "",
                        max_chars: int = 32000) -> str:
    """Format rules as compact one-liners: baseline + task-relevant rules.

    Always includes ~9 universal baseline rules.  Then adds task-specific
    rules matched by keyword overlap.  Keeps prompt focused for the LLM
    (typically 10-40 rules instead of 160+).
    """

    query_kw = _extract_keywords(f"{task} {category}") if task else set()

    baseline = []
    matched = []
    skipped = 0

    for key, value in rules.items():
        if key.startswith("__") or not isinstance(value, dict):
            continue
        note = value.get("note", "")
        if not note:
            continue

        # Always-include baseline rules
        if key in _ALWAYS_INCLUDE:
            baseline.append((key, note))
            continue

        # If no task context, include everything (fallback)
        if not query_kw:
            matched.append((key, note))
            continue

        # Keyword match against rule id + note
        rule_kw = _extract_keywords(f"{key} {note}")
        if query_kw & rule_kw:
            matched.append((key, note))
        else:
            skipped += 1

    # Build output
    lines = []
    total_chars = 0

    if baseline:
        lines.append(f"MANDATORY RULES ({len(baseline)})")
        lines.append("=" * 50)
        for key, note in baseline:
            line = f"- {key}: {_shorten_note(note)}"
            lines.append(line)
            total_chars += len(line) + 1

    if matched:
        lines.append("")
        lines.append(f"TASK-SPECIFIC RULES ({len(matched)} matched, {skipped} skipped)")
        lines.append("=" * 50)
        for key, note in matched:
            line = f"- {key}: {_shorten_note(note)}"
            if total_chars + len(line) + 1 > max_chars:
                lines.append(f"... (truncated at {max_chars} chars)")
                break
            lines.append(line)
            total_chars += len(line) + 1

    return "\n".join(lines)


class PipelineRunner:
    """Orchestrates the 5-stage code generation and testing pipeline."""

    def __init__(
        self,
        config: AppConfig,
        progress_callback: Callable = None,
        shared_sentence_model=None,
        usage_tracker=None,
    ):
        self.config = config
        self._notify_fn = progress_callback
        self.mcp = MCPClient(config, usage_tracker=usage_tracker)
        self.llm = LLMClient(config, usage_tracker=usage_tracker)
        self.builder = DotnetBuilder(config)

        # Knowledge base (lazy-loaded on first regen)
        self._rule_engine = RuleSearchEngine()
        self._shared_model = shared_sentence_model
        self._kb_loaded = False
        self._error_catalog = None
        self._error_fixes = None

        # Self-learning (fire-and-forget after successful fixes)
        self._auto_learner = AutoLearner(config, self.llm) if config.pipeline.auto_learn_on_success else None

        # Generation rules (lazy-loaded when use_own_llm is enabled)
        self._generation_rules_raw = {}   # raw dict from JSON (for per-task filtering)
        self._generation_rules = ""       # formatted text (fallback / backward compat)
        self._generation_rules_loaded = False

    def _notify(self, stage: str, message: str):
        if self._notify_fn:
            try:
                self._notify_fn(stage, message)
            except Exception:
                pass

    def _ensure_error_fixes(self):
        """Load error fixes (lightweight, needed from Stage 2 onward)."""
        if self._error_fixes is not None:
            return
        self._error_fixes = load_error_fixes(self.config.error_fixes_path)
        auto_fixes = load_error_fixes(self.config.auto_fixes_path)
        if auto_fixes:
            self._error_fixes = {**auto_fixes, **self._error_fixes}

    def _ensure_kb(self):
        """Lazy-load full knowledge base resources (rules, catalog, fixes)."""
        if self._kb_loaded:
            return
        self._rule_engine.load(self.config.rules_examples_path, self._shared_model)
        self._error_catalog = load_error_catalog(self.config.error_catalog_path)
        # Merge auto-learned catalog entries
        auto_catalog = load_auto_error_catalog(self.config.auto_catalog_path)
        if auto_catalog:
            self._error_catalog = self._error_catalog + auto_catalog
        self._ensure_error_fixes()
        self._kb_loaded = True

    def _ensure_generation_rules(self):
        """Lazy-load generation rules from resources/generation_rules.json."""
        if self._generation_rules_loaded:
            return
        self._generation_rules_loaded = True
        rules_path = Path(self.config.workspace_path) / "resources" / "generation_rules.json"
        if rules_path.exists():
            try:
                data = json.loads(rules_path.read_text(encoding="utf-8"))
                self._generation_rules_raw = data.get("rules", {})
            except Exception as e:
                print(f"Warning: could not load generation rules: {e}")

    def _get_rules_for_task(self, task: str, category: str = "") -> str:
        """Return baseline + task-relevant rules as compact one-liners."""
        self._ensure_generation_rules()
        if not self._generation_rules_raw:
            return ""
        return _format_rules_block(self._generation_rules_raw, task=task, category=category)

    def _enrich_metadata(self, result: PipelineResult):
        """Extract metadata from final compiled code via LLM (post-success).

        Enriches result.metadata with title, filename, description, tags,
        apis_used, difficulty.  Runs once per passed example.
        Skips silently if LLM is unavailable or extraction fails.
        """
        final_code = result.fixed_code or result.generated_code
        if not final_code or not self.llm.available:
            return
        # Skip if metadata is already complete (e.g. own-LLM baseline success)
        _META_KEYS = ("title", "filename", "description", "tags", "apis_used", "difficulty")
        if all(result.metadata.get(k) for k in _META_KEYS):
            self._notify("metadata", "Metadata already complete — skipping extraction")
            return
        try:
            self._notify("metadata", "Extracting metadata from compiled code...")
            meta = self.llm.extract_metadata(result.task, final_code, result.category)
            if meta:
                # Merge — LLM-extracted metadata wins, but don't overwrite existing non-empty values
                for key, value in meta.items():
                    if value and not result.metadata.get(key):
                        result.metadata[key] = value
                self._notify("metadata", f"Metadata extracted: {meta.get('title', '')[:60]}")
        except Exception as e:
            self._notify("metadata", f"Metadata extraction skipped: {str(e)[:80]}")

    def _fire_learning(self, task_input: TaskInput, original_code: str, fixed_code: str, error_log: str, stage: str):
        """Fire-and-forget: extract a reusable rule from a successful fix."""
        if not self._auto_learner or stage == "baseline":
            return
        error_codes = re.findall(r"CS\d{4}", error_log)
        threading.Thread(
            target=self._auto_learner.learn_from_success,
            args=(task_input.task, task_input.category, original_code, fixed_code, error_log, error_codes, stage),
            daemon=True,
        ).start()

    def _get_fixes_for_error(self, error_log: str) -> str:
        """Match error fixes against a build error and return formatted text."""
        self._ensure_error_fixes()
        error_codes = re.findall(r"CS\d{4}", error_log)
        fixes = match_error_fixes(self._error_fixes or {}, error_log, error_codes)
        return format_error_fixes_for_prompt(fixes) if fixes else ""

    def execute(self, task_input: TaskInput) -> PipelineResult:
        """Run the 5-stage pipeline. Returns PipelineResult."""
        result = PipelineResult(
            task=task_input.task,
            category=task_input.category,
            product=task_input.product,
        )

        # ── Namespace restriction (computed once, reused across stages) ──
        ns_restriction = build_namespace_restriction(
            task_input.category, self.config.mcp.exclude_namespaces,
        )

        # ── Stage 1: Baseline Generation ──
        task_rules = ""
        if self.config.pipeline.use_own_llm:
            task_rules = self._get_rules_for_task(task_input.task, task_input.category)
        self._notify("baseline", f"Stage 1: Generating code for: {task_input.task[:80]}...")
        outcome = stages.run_baseline(
            task_input, self.mcp, self.builder, self._notify,
            llm=self.llm, config=self.config,
            generation_rules=task_rules,
            namespace_restriction=ns_restriction,
        )

        if outcome.success:
            result.generated_code = outcome.code
            result.metadata = outcome.metadata
            result.status = "SUCCESS"
            result.stage = "baseline"
            self._enrich_metadata(result)
            return result

        if not outcome.code:
            result.status = "API_FAILED"
            result.stage = "baseline"
            result.build_log = outcome.build_log
            return result

        result.generated_code = outcome.code
        result.metadata = outcome.metadata  # keep baseline metadata even if code gets fixed later
        current_code = outcome.code
        current_error = outcome.build_log

        # ── Pattern fix (between stages 1 and 2) ──
        # Loop: a single call only applies the first matching fix, so
        # keep applying until no more known patterns match (max 5).
        for _pf_round in range(5):
            fixed, rule = detect_and_fix_known_patterns(current_code, current_error, self.config.auto_patterns_path)
            if not fixed:
                break
            self._notify("pattern_fix", f"Applying known pattern fix (round {_pf_round + 1})...")
            self.builder.write_program_cs(fixed)
            success, output = self.builder.build_and_run()
            if success:
                result.fixed_code = fixed
                result.rule = rule or ""
                result.status = "SUCCESS"
                result.stage = "pattern_fix"
                self._enrich_metadata(result)
                self._fire_learning(task_input, outcome.code, fixed, current_error, "pattern_fix")
                return result
            current_code = fixed
            current_error = output

        # ── Stage 2: LLM Fix Attempts ──
        self._ensure_error_fixes()
        if self.config.pipeline.llm_fix_attempts > 0:
            self._notify("llm_fix", "Stage 2: LLM fix attempts...")
            outcome = stages.run_llm_fix_loop(
                current_code, current_error, task_input.task,
                self.llm, self.builder, self._notify,
                max_attempts=self.config.pipeline.llm_fix_attempts,
                user_rules=task_rules,
                error_fixes_data=self._error_fixes,
                namespace_restriction=ns_restriction,
            )
            if outcome.success:
                result.fixed_code = outcome.code
                result.status = "SUCCESS"
                result.stage = "llm_fix"
                self._enrich_metadata(result)
                self._fire_learning(task_input, result.generated_code, outcome.code, current_error, "llm_fix")
                return result

            current_code = outcome.code
            current_error = outcome.build_log

        # ── Stage 3: Context Enrichment ──
        self._notify("enrich", "Stage 3: Enriching context...")
        enriched_task = stages.run_context_enrichment(
            task_input.task, current_error,
            self.mcp, self.llm, self.config,
            category=task_input.category,
        )

        # ── Stage 4: Regeneration with enriched context ──
        self._ensure_kb()
        self._notify("regen", "Stage 4: Regeneration attempts...")
        outcome = stages.run_regen_loop(
            enriched_task, task_input, current_error,
            self.mcp, self.builder, self.llm, self._notify, self.config,
            rule_engine=self._rule_engine,
            error_catalog=self._error_catalog,
            error_fixes_data=self._error_fixes,
            generation_rules=task_rules,
            namespace_restriction=ns_restriction,
        )
        if outcome.success:
            result.fixed_code = outcome.code
            result.rule = outcome.rule
            result.status = "SUCCESS"
            result.stage = "regen"
            self._enrich_metadata(result)
            self._fire_learning(task_input, result.generated_code, outcome.code, current_error, "regen")
            return result

        # ── Stage 5: Final LLM Recovery ──
        if self.config.pipeline.final_llm_after_regen_fail:
            # Fall back to pre-regen code if Stage 4 produced nothing
            # (e.g. all MCP regen attempts returned None).
            stage5_code = outcome.code or current_code
            stage5_error = outcome.build_log or current_error
            self._notify("final_llm", "Stage 5: Final LLM recovery...")
            outcome = stages.run_final_llm_recovery(
                stage5_code, stage5_error, task_input.task,
                self.llm, self.builder, self._notify, self.config,
                error_fixes_data=self._error_fixes,
                generation_rules=task_rules,
                namespace_restriction=ns_restriction,
            )
            if outcome.success:
                result.fixed_code = outcome.code
                result.status = "SUCCESS"
                result.stage = "final_llm"
                self._enrich_metadata(result)
                self._fire_learning(task_input, result.generated_code, outcome.code, stage5_error, "final_llm")
                return result

        # ── All stages failed ──
        result.status = "FAILED"
        result.stage = "exhausted"
        result.build_log = outcome.build_log
        return result
