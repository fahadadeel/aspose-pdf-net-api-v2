"""
knowledge/reranker.py — LLM-based reranking of candidate KB rules.
"""

import json
from typing import List, Optional

from pipeline.llm_client import LLMClient


def llm_rerank_rules(
    candidate_rules: List[dict],
    build_errors: str,
    original_prompt: str,
    top_k: int,
    llm: LLMClient,
) -> Optional[List[dict]]:
    """Use LLM to rerank candidate KB rules based on actual build errors.

    Returns reranked rules or None on failure (caller falls back to ST top-k).
    """
    if not llm.available or not candidate_rules:
        return None

    candidates_compact = [
        {
            "id": r.get("id", ""),
            "category": r.get("category", ""),
            "summary": r.get("semantic_summary", ""),
            "api": r.get("api_surface", []),
        }
        for r in candidate_rules
    ]

    system = (
        "You are an expert at matching Aspose.PDF for .NET API knowledge base rules "
        "to C# build errors. Given candidate rules and build errors, "
        f"return ONLY a JSON array of the {top_k} most relevant rule IDs.\n\n"
        "Selection criteria:\n"
        "- Rules whose api fields match types/methods in errors\n"
        "- Rules whose summary describes patterns that would fix errors\n"
        "- Prefer high-specificity over generic rules\n\n"
        'Return ONLY: ["rule-id-1", "rule-id-2", ...]'
    )
    user = (
        f"## Task\n{original_prompt[:500]}\n\n"
        f"## Build Errors\n{build_errors[:2000]}\n\n"
        f"## Candidate Rules ({len(candidates_compact)} total)\n"
        f"{json.dumps(candidates_compact)}\n\n"
        f"Return top {top_k} rule IDs as JSON array."
    )

    content = llm.chat(system, user, temperature=0.1, max_tokens=500, timeout=20)
    if not content:
        return None

    # Strip markdown fences
    if content.startswith("```"):
        content = content.split("\n", 1)[-1]
        if content.endswith("```"):
            content = content[:-3]
        content = content.strip()

    try:
        selected_ids = json.loads(content)
        if not isinstance(selected_ids, list) or not all(isinstance(x, str) for x in selected_ids):
            return None
        lookup = {r.get("id", ""): r for r in candidate_rules}
        reranked = [lookup[rid] for rid in selected_ids if rid in lookup]
        return reranked[:top_k] if reranked else None
    except json.JSONDecodeError:
        return None
