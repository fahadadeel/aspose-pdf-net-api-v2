"""
knowledge/error_fixes.py — Load and match curated error fixes from error_fixes.json.
"""

import json
import re
from pathlib import Path
from typing import Dict, List


def load_error_fixes(path: str) -> Dict[str, dict]:
    """Load error fixes from JSON file (id -> fix object)."""
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except FileNotFoundError:
        print(f"Error fixes not found at {path}")
        return {}
    except json.JSONDecodeError as e:
        print(f"Error fixes has invalid JSON: {e}")
        return {}


def match_error_fixes(fixes: Dict[str, dict], error_output: str, error_codes: List[str]) -> List[dict]:
    """Match build errors against fixes; return top 10 scored by relevance."""
    if not fixes:
        return []

    scored = []
    error_lower = error_output.lower()

    for fix_id, fix in fixes.items():
        if not isinstance(fix, dict):
            continue
        score = 0.0
        for err_str in fix.get("errors", []):
            codes_in_fix = re.findall(r"CS\d{4}", err_str)
            for code in codes_in_fix:
                if code in error_codes:
                    score += 3.0

            key_phrases = re.findall(
                r"([\w.]+Exception|'[\w.]+'|does not contain a definition for '[\w.]+'|"
                r"does not contain a constructor that takes \d+ arguments)",
                err_str,
            )
            for phrase in key_phrases:
                clean = phrase.strip("'").lower()
                if clean and clean in error_lower:
                    score += 2.0

        if score > 0:
            scored.append((score, fix_id, fix))

    scored.sort(key=lambda x: x[0], reverse=True)
    return [{"id": fid, **fd} for _, fid, fd in scored[:10]]


def format_error_fixes_for_prompt(fixes: List[dict]) -> str:
    """Format matched fixes into prompt text."""
    if not fixes:
        return ""
    parts = ["=== VERIFIED ERROR FIXES (apply these) ==="]
    for fix in fixes:
        parts.append(f"\n[Fix: {fix.get('id', 'unknown')}]")
        if fix.get("note"):
            parts.append(f"Note: {fix['note']}")
        if fix.get("code"):
            parts.append(f"Code:\n{fix['code']}")
    return "\n".join(parts)
