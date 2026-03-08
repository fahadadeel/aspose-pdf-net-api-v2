"""
knowledge/auto_fixes.py — Load and save auto-learned error fixes.

Thread-safe file I/O for resources/auto_fixes.json.
Uses the same format as error_fixes.json so match_error_fixes() works seamlessly.
"""

import json
import threading
from pathlib import Path
from typing import Dict

_LOCK = threading.Lock()
_MAX_RULES = 200


def load_auto_fixes(path: str) -> Dict[str, dict]:
    """Load auto-learned fixes from JSON file."""
    with _LOCK:
        p = Path(path)
        if not p.exists():
            return {}
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
        except (json.JSONDecodeError, Exception):
            return {}


def save_auto_fix(path: str, rule_id: str, rule: dict) -> bool:
    """Save a single auto-learned fix to the auto_fixes file.

    If rule_id already exists, it is overwritten.
    If the file exceeds MAX_RULES, the oldest entries are pruned.
    Returns True if save succeeded.
    """
    with _LOCK:
        p = Path(path)
        try:
            if p.exists():
                existing = json.loads(p.read_text(encoding="utf-8"))
                if not isinstance(existing, dict):
                    existing = {}
            else:
                existing = {}

            existing[rule_id] = rule

            # Prune if over max (keep newest by insertion order)
            if len(existing) > _MAX_RULES:
                keys = list(existing.keys())
                for old_key in keys[: len(keys) - _MAX_RULES]:
                    del existing[old_key]

            p.write_text(
                json.dumps(existing, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
            return True
        except Exception as e:
            print(f"Failed to save auto fix: {e}")
            return False


def is_duplicate_rule(path: str, rule_id: str, error_patterns: list) -> bool:
    """Check if a rule with same ID or very similar error patterns already exists."""
    existing = load_auto_fixes(path)

    if rule_id in existing:
        return True

    if error_patterns:
        new_set = set(e.lower().strip() for e in error_patterns)
        for fix in existing.values():
            old_errors = fix.get("errors", [])
            old_set = set(e.lower().strip() for e in old_errors)
            if old_set and new_set:
                overlap = len(old_set & new_set)
                if overlap / min(len(old_set), len(new_set)) > 0.5:
                    return True

    return False
