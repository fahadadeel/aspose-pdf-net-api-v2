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
    """Match build errors against catalog; return fix guidance strings."""
    guidance: List[str] = []
    seen: set = set()
    for entry in catalog:
        pat = entry.get("pattern", "")
        if pat and re.search(pat, error_output) and pat not in seen:
            seen.add(pat)
            guidance.append(entry.get("fix_guidance", ""))
    return [g for g in guidance if g]
