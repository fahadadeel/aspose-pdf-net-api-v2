"""
knowledge/error_catalog.py — Load and match error patterns from error_catalog.json.
"""

import json
import re
from pathlib import Path
from typing import List


def load_error_catalog(path: str) -> List[dict]:
    """Load error catalog from JSON file."""
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except FileNotFoundError:
        print(f"Error catalog not found at {path}")
        return []
    except json.JSONDecodeError as e:
        print(f"Error catalog has invalid JSON: {e}")
        return []


def match_error_catalog(catalog: List[dict], error_output: str) -> List[str]:
    """Match build errors against catalog; return fix guidance strings.

    Patterns are data-driven (some are auto-learned), so a single bad
    regex is logged and skipped rather than crashing the caller.
    """
    guidance: List[str] = []
    seen: set = set()
    for entry in catalog:
        pat = entry.get("pattern", "")
        if not pat or pat in seen:
            continue
        try:
            if re.search(pat, error_output):
                seen.add(pat)
                guidance.append(entry.get("fix_guidance", ""))
        except re.error as rex:
            print(f"[error_catalog] Skipping invalid pattern {pat!r}: {rex}")
    return [g for g in guidance if g]
