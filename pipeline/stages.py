"""
pipeline/stages.py — The 5-stage retry pipeline functions.

Stage 1: Baseline Generation
Stage 2: LLM Fix Attempts
Stage 3: Context Enrichment
Stage 4: Regeneration with enriched context
Stage 5: Final LLM Recovery
"""

import json
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Callable, List, Optional, Tuple

from config import AppConfig
from pipeline.models import StageOutcome, TaskInput
from pipeline.build import DotnetBuilder
from pipeline.mcp_client import MCPClient
from pipeline.llm_client import LLMClient
from pipeline.error_parser import extract_errors, parse_error_codes, detect_and_fix_known_patterns
from pipeline.prompt_builder import (
    build_enriched_prompt, build_retry_instruction,
    format_rules_for_prompt,
)
from knowledge.error_catalog import match_error_catalog
from knowledge.error_fixes import match_error_fixes, format_error_fixes_for_prompt
from knowledge.fix_history import get_boosted_rule_ids, record_successful_fix
from knowledge.auto_fixes import promote_auto_fix
from knowledge.rule_search import RuleSearchEngine
from knowledge.reranker import llm_rerank_rules

Notify = Callable[[str, str], None]


# ── var → explicit-type regex replacements ────────────────────────────────────
# These cover the most common patterns the LLM produces with `var`.
# Each tuple: (regex pattern, replacement using captured groups)
# Applied deterministically before building — no LLM involved.
_VAR_REPLACEMENTS: list = [
    # var x = new SomeType(         →  SomeType x = new SomeType(
    (re.compile(r'\bvar\s+(\w+)\s*=\s*new\s+([\w.]+)\s*\('), r'\2 \1 = new \2('),
    # var x = new SomeType {        →  SomeType x = new SomeType {
    (re.compile(r'\bvar\s+(\w+)\s*=\s*new\s+([\w.]+)\s*\{'), r'\2 \1 = new \2 {'),
    # var x = new SomeType[         →  SomeType[] x = new SomeType[
    (re.compile(r'\bvar\s+(\w+)\s*=\s*new\s+([\w.]+)\[\]'), r'\2[] \1 = new \2[]'),
    # foreach (var x in            →  foreach (var x in  — skip (type unknown without analysis)
]


def _sanitize_code(code: str) -> str:
    """Apply deterministic style fixes to generated C# code.

    Currently enforces:
    - No `var` for `new T(...)` / `new T {` / `new T[]` patterns
      where the type is recoverable from the right-hand side.
    - Does NOT touch: foreach(var ...), LINQ anonymous projections,
      or any pattern where the type cannot be inferred syntactically.
    """
    for pattern, replacement in _VAR_REPLACEMENTS:
        code = pattern.sub(replacement, code)
    return code


def run_baseline(
    task_input: TaskInput, mcp: MCPClient, builder: DotnetBuilder, notify: Notify,
    llm: LLMClient = None, config: AppConfig = None, generation_rules: str = "",
) -> StageOutcome:
    """Stage 1: Generate code and build/run.

    When use_own_llm is enabled, retrieves chunks via MCP and generates code
    with the user's own LLM key instead of letting MCP server generate.
    """
    use_own_llm = config and config.pipeline.use_own_llm and llm and llm.available

    metadata: dict = {}

    if use_own_llm:
        # Retrieve chunks + generate code with own LLM
        notify("baseline", "Retrieving API docs...")
        chunks = mcp.retrieve(task_input.task, category=task_input.category)
        chunks_text = MCPClient.format_chunks(chunks, config.pipeline.retrieve_max_chars)
        notify("baseline", "Generating code with own LLM...")
        result = llm.generate_code(
            task_input.task, chunks_text,
            rules_text=generation_rules,
            category=task_input.category,
        )
        if result:
            code = result.get("code", "")
            metadata = {k: v for k, v in result.items() if k != "code"}
        else:
            code = None
    else:
        # Original path: MCP server does retrieve + generate
        notify("baseline", "Generating code via MCP...")
        code = mcp.generate(task_input.task, category=task_input.category, product=task_input.product)

    if not code:
        return StageOutcome(success=False, stage="baseline", build_log="API call failed")

    # Apply deterministic style guard (e.g. var → explicit types)
    code = _sanitize_code(code)

    # ── Two-pass validation: check code against critical rules before building ──
    if use_own_llm and generation_rules and llm:
        notify("baseline", "Validating against rules...")
        validated = llm.validate_against_rules(code, generation_rules)
        if validated:
            code = _sanitize_code(validated)
            notify("baseline", "Rules violations fixed in pre-build pass")

    builder.write_csproj()
    builder.write_program_cs(code)
    notify("baseline", "Building and running...")
    success, output = builder.build_and_run()

    if success:
        return StageOutcome(success=True, code=code, stage="baseline", metadata=metadata)
    return StageOutcome(success=False, code=code, stage="baseline", build_log=output, metadata=metadata)


def run_llm_fix_loop(
    code: str, error_log: str, task: str,
    llm: LLMClient, builder: DotnetBuilder, notify: Notify,
    max_attempts: int = 3, user_rules: str = "",
    error_fixes_data: dict = None,
) -> StageOutcome:
    """Stage 2: Loop LLM fix attempts."""
    if not llm.available:
        return StageOutcome(success=False, stage="llm_fix", build_log="LLM not configured")

    last_err = error_log
    current_code = code

    for attempt in range(1, max_attempts + 1):
        notify("llm_fix", f"LLM fix attempt {attempt}/{max_attempts}...")
        error_lines = extract_errors(last_err, limit=10)
        error_summary = "\n".join(error_lines[:5]) if error_lines else "Build errors detected."

        # Match relevant error fixes for the current errors
        rules_for_llm = user_rules
        if error_fixes_data:
            parsed = parse_error_codes(error_lines)
            error_codes = list(dict.fromkeys(e.code for e in parsed))
            fixes = match_error_fixes(error_fixes_data, last_err, error_codes)
            fixes_text = format_error_fixes_for_prompt(fixes)
            if fixes_text:
                rules_for_llm = f"{user_rules}\n\n{fixes_text}" if user_rules else fixes_text

        fixed_code = llm.fix_code(task, current_code, error_summary, rules_for_llm)
        if not fixed_code:
            continue

        builder.write_program_cs(fixed_code)
        success, output = builder.build_and_run()

        if success:
            return StageOutcome(success=True, code=fixed_code, stage="llm_fix")

        last_err = output
        current_code = fixed_code

    return StageOutcome(success=False, code=current_code, stage="llm_fix", build_log=last_err)


def run_context_enrichment(
    task: str, error_log: str,
    mcp: MCPClient, llm: LLMClient, config: AppConfig,
    category: str = "",
) -> str:
    """Stage 3: Retrieve API chunks and optionally decompose task. Returns enriched task.

    Runs retrieval and decomposition in parallel when both are enabled.
    """
    parts = [task]

    do_retrieve = config.pipeline.use_retrieve_on_llm_fail
    do_decompose = config.pipeline.decompose_on_llm_fail and llm.available

    # Run both network calls in parallel when both are enabled
    if do_retrieve and do_decompose:
        chunks_text = ""
        decomposed = None

        def _retrieve():
            chunks = mcp.retrieve(
                task,
                category=category,
                limit=config.pipeline.retrieve_limit,
            )
            return MCPClient.format_chunks(chunks, config.pipeline.retrieve_max_chars)

        def _decompose():
            return llm.decompose_task(task, "")

        with ThreadPoolExecutor(max_workers=2) as pool:
            fut_retrieve = pool.submit(_retrieve)
            fut_decompose = pool.submit(_decompose)
            chunks_text = fut_retrieve.result()
            decomposed = fut_decompose.result()

        if decomposed:
            parts.append(decomposed)
        if chunks_text:
            parts.append(chunks_text)
    else:
        # Only one (or neither) is enabled — run sequentially
        if do_retrieve:
            chunks = mcp.retrieve(
                task,
                category=category,
                limit=config.pipeline.retrieve_limit,
            )
            chunks_text = MCPClient.format_chunks(chunks, config.pipeline.retrieve_max_chars)
            if chunks_text:
                parts.append(chunks_text)

        if do_decompose:
            context = "\n".join(parts[1:]) if len(parts) > 1 else ""
            decomposed = llm.decompose_task(task, context)
            if decomposed:
                parts.insert(1, decomposed)

    return "\n\n".join(parts)


def run_regen_loop(
    enriched_task: str, task_input: TaskInput,
    original_error_log: str,
    mcp: MCPClient, builder: DotnetBuilder, llm: LLMClient,
    notify: Notify, config: AppConfig,
    rule_engine: Optional[RuleSearchEngine] = None,
    error_catalog: list = None,
    error_fixes_data: dict = None,
    generation_rules: str = "",
) -> StageOutcome:
    """Stage 4: Regeneration with enriched context and KB rules."""
    max_attempts = config.pipeline.regen_attempts
    retry_mode = config.pipeline.retry_mode

    error_lines = extract_errors(original_error_log, limit=10)
    parsed = parse_error_codes(error_lines)
    error_codes = list(dict.fromkeys(e.code for e in parsed))
    error_summary = "\n".join(error_lines[:5]) if error_lines else "Build errors detected."

    history_boosts = get_boosted_rule_ids(config.fix_history_path, error_codes)
    prev_codes: List[str] = []
    prev_count = 0
    last_code = ""
    last_err = original_error_log

    for attempt in range(1, max_attempts + 1):
        if retry_mode == "simple":
            prompt = (
                f"{enriched_task}\n\n"
                f"The previous code failed with:\n{error_summary}\n\n"
                f"Please generate corrected code."
            )
            top_rules = []
            catalog_patterns = []
        else:
            # Full mode: catalog + error fixes + KB rules
            cat_guidance = match_error_catalog(error_catalog or [], last_err) if error_catalog else []
            matched_catalog = [e.get("pattern", "") for e in (error_catalog or []) if re.search(e.get("pattern", "x^"), last_err)]
            fixes = match_error_fixes(error_fixes_data or {}, last_err, error_codes)
            fixes_text = format_error_fixes_for_prompt(fixes)

            query = f"{task_input.task}\n{error_summary}"
            if attempt == 1 and rule_engine:
                top_rules = rule_engine.find_top_rules(query, config.reranker.attempt1_top_k, error_codes, history_boosts)
            elif rule_engine:
                candidates = rule_engine.find_top_rules(query, config.reranker.candidate_count, error_codes, history_boosts)
                reranked = llm_rerank_rules(candidates, error_summary, task_input.task, config.reranker.top_k, llm)
                if reranked:
                    top_rules = reranked
                else:
                    top_k = RuleSearchEngine.compute_adaptive_top_k(attempt, error_codes, prev_codes, len(error_lines), prev_count)
                    top_rules = candidates[:top_k]
            else:
                top_rules = []

            rules_text = format_rules_for_prompt(top_rules)
            retry_inst = build_retry_instruction(attempt, error_codes)
            catalog_patterns = matched_catalog

            prompt = build_enriched_prompt(
                enriched_task, error_summary,
                catalog_guidance=cat_guidance,
                error_fixes_text=fixes_text,
                retry_instruction=retry_inst,
                rules_text=rules_text,
            )

        notify("regen", f"MCP regen attempt {attempt}/{max_attempts}...")
        use_own_llm = config.pipeline.use_own_llm and llm and llm.available
        if use_own_llm:
            chunks = mcp.retrieve(task_input.task, category=task_input.category)
            chunks_text = MCPClient.format_chunks(chunks, config.pipeline.retrieve_max_chars)
            regen_result = llm.generate_code(
                prompt, chunks_text,
                rules_text=generation_rules,
                category=task_input.category,
            )
            code = regen_result.get("code", "") if regen_result else None
        else:
            code = mcp.generate(prompt, category=task_input.category, product=task_input.product, limit=config.pipeline.retrieve_limit)
        if not code:
            continue

        builder.write_program_cs(code)
        success, output = builder.build_and_run()
        last_code = code

        if success:
            # Record fix for future learning
            rule_ids = [r.get("id", "") for r in top_rules if r.get("id")]
            try:
                record_successful_fix(
                    config.fix_history_path, error_codes, rule_ids,
                    catalog_patterns, attempt, task_input.task[:120],
                )
            except Exception:
                pass
            # Promote auto-generated fixes that contributed to this success
            if fixes:
                for f in fixes:
                    if f.get("_auto"):
                        try:
                            promote_auto_fix(config.auto_fixes_path, f.get("id", ""))
                        except Exception:
                            pass
            rule_desc = json.dumps({
                "description": f"MCP regen attempt {attempt} ({len(top_rules)} rules)",
                "pattern": "Regeneration with context enrichment",
            }, indent=2)
            return StageOutcome(success=True, code=code, stage="regen", rule=rule_desc)

        # Update error state for next attempt
        prev_codes = error_codes[:]
        prev_count = len(error_lines)
        last_err = output
        error_lines = extract_errors(output, limit=10)
        parsed = parse_error_codes(error_lines)
        error_codes = list(dict.fromkeys(e.code for e in parsed))
        error_summary = "\n".join(error_lines[:5]) if error_lines else "Build errors detected."
        history_boosts = get_boosted_rule_ids(config.fix_history_path, error_codes)

    return StageOutcome(success=False, code=last_code, stage="regen", build_log=last_err)


def run_final_llm_recovery(
    code: str, error_log: str, task: str,
    llm: LLMClient, builder: DotnetBuilder, notify: Notify,
    config: AppConfig,
    error_fixes_data: dict = None,
) -> StageOutcome:
    """Stage 5: One last LLM fix attempt using last regen code."""
    if not llm.available or not code:
        return StageOutcome(success=False, stage="final_llm")

    notify("final_llm", "Final LLM recovery attempt...")
    error_lines = extract_errors(error_log, limit=10)
    error_summary = "\n".join(error_lines[:5]) if error_lines else "Build errors detected."

    # Match relevant error fixes for this final attempt
    fixes_text = ""
    if error_fixes_data:
        parsed = parse_error_codes(error_lines)
        error_codes = list(dict.fromkeys(e.code for e in parsed))
        fixes = match_error_fixes(error_fixes_data, error_log, error_codes)
        fixes_text = format_error_fixes_for_prompt(fixes)

    fixed = llm.fix_code(task, code, error_summary, fixes_text)
    if not fixed:
        return StageOutcome(success=False, stage="final_llm")

    builder.write_program_cs(fixed)
    success, output = builder.build_and_run()

    if success:
        return StageOutcome(success=True, code=fixed, stage="final_llm")
    return StageOutcome(success=False, code=fixed, stage="final_llm", build_log=output)
