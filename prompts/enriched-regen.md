# Enriched Regeneration Prompt

Used in Stage 5 (Regeneration) when baseline and LLM fix stages have failed.
Combines the original task with full context: error history, KB rules, error catalog
guidance, fix examples, and an optional decomposed implementation plan.

## Structure

```
{task}

{decomposed_plan}          ← LLM-generated step-by-step plan (Stage 4 output)

Previous attempt had these errors:
{error_summary}            ← Compiler errors from last failed build

=== KNOWN API FIXES (apply these first) ===
{catalog_guidance}         ← Matched entries from error_catalog.json

{error_fixes_text}         ← Scored fix suggestions from error_fixes.json

{retry_instruction}        ← Attempt-specific constraint (see retry-instructions.md)

=== Relevant API Patterns (from knowledge base) ===
{rules_text}               ← Top-K KB rules from semantic + keyword search

{chunks_text}              ← MCP /retrieve context chunks

Please generate corrected code that fixes the above errors.
```

## Sections

| Section | Source | Always present |
|---------|--------|---------------|
| `task` | Original task prompt | Yes |
| `decomposed_plan` | `pipeline/llm_client.py` decompose call | No |
| `error_summary` | `pipeline/error_parser.py` | Yes |
| `catalog_guidance` | `knowledge/error_catalog.py` | No |
| `error_fixes_text` | `knowledge/error_fixes.py` | No |
| `retry_instruction` | `pipeline/prompt_builder.py` | No |
| `rules_text` | `knowledge/rule_search.py` + `knowledge/reranker.py` | No |
| `chunks_text` | `pipeline/mcp_client.py` `/retrieve` | No |

## KB Rules Format

Each matched rule is formatted as:

```
[Pattern N] {rule_id}  ({category})  * high confidence
Summary: {semantic_summary}
Key APIs: {api_surface}
IMPORTANT NOTES:
  - {warnings}
Implementation:
  - {rules}
```

## Source

`pipeline/prompt_builder.py` → `build_enriched_prompt()`, `format_rules_for_prompt()`
