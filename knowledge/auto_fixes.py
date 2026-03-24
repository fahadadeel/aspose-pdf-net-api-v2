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


def promote_auto_fix(path: str, rule_id: str) -> bool:
    """Bump confidence and hit count for an auto-generated fix that contributed to a success.

    Called when an auto rule helps resolve an error during the pipeline.
    Confidence increases by 0.1 per hit, capped at 1.0.
    """
    with _LOCK:
        p = Path(path)
        try:
            if not p.exists():
                return False
            data = json.loads(p.read_text(encoding="utf-8"))
            if not isinstance(data, dict) or rule_id not in data:
                return False

            rule = data[rule_id]
            rule["_hit_count"] = rule.get("_hit_count", 0) + 1
            rule["_confidence"] = min(rule.get("_confidence", 0.5) + 0.1, 1.0)

            p.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
            return True
        except Exception:
            return False


def approve_auto_fix(auto_path: str, curated_path: str, rule_id: str) -> bool:
    """Move an auto fix to the curated error_fixes.json file."""
    with _LOCK:
        p_auto = Path(auto_path)
        p_curated = Path(curated_path)
        try:
            if not p_auto.exists():
                return False
            auto_data = json.loads(p_auto.read_text(encoding="utf-8"))
            if rule_id not in auto_data:
                return False

            rule = auto_data.pop(rule_id)
            # Strip auto metadata
            for key in ("_auto", "_confidence", "_created_at", "_hit_count", "_stage", "_category"):
                rule.pop(key, None)

            # Add to curated
            curated_data = {}
            if p_curated.exists():
                curated_data = json.loads(p_curated.read_text(encoding="utf-8"))
            curated_data[rule_id] = rule
            p_curated.write_text(json.dumps(curated_data, indent=2, ensure_ascii=False), encoding="utf-8")

            # Save trimmed auto file
            p_auto.write_text(json.dumps(auto_data, indent=2, ensure_ascii=False), encoding="utf-8")
            return True
        except Exception as e:
            print(f"Failed to approve auto fix: {e}")
            return False


def approve_all_auto_fixes(auto_path: str, curated_path: str) -> int:
    """Move all auto fixes to the curated error_fixes.json. Returns count approved."""
    with _LOCK:
        p_auto = Path(auto_path)
        p_curated = Path(curated_path)
        try:
            if not p_auto.exists():
                return 0
            auto_data = json.loads(p_auto.read_text(encoding="utf-8"))
            if not auto_data:
                return 0

            curated_data = {}
            if p_curated.exists():
                curated_data = json.loads(p_curated.read_text(encoding="utf-8"))

            count = 0
            for rule_id, rule in auto_data.items():
                clean = {k: v for k, v in rule.items()
                         if k not in ("_auto", "_confidence", "_created_at", "_hit_count", "_stage", "_category")}
                curated_data[rule_id] = clean
                count += 1

            p_curated.write_text(json.dumps(curated_data, indent=2, ensure_ascii=False), encoding="utf-8")
            p_auto.write_text(json.dumps({}, indent=2, ensure_ascii=False), encoding="utf-8")
            return count
        except Exception as e:
            print(f"Failed to approve all auto fixes: {e}")
            return 0


def delete_auto_fix(path: str, rule_id: str) -> bool:
    """Remove an auto-generated fix."""
    with _LOCK:
        p = Path(path)
        try:
            if not p.exists():
                return False
            data = json.loads(p.read_text(encoding="utf-8"))
            if rule_id not in data:
                return False
            del data[rule_id]
            p.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
            return True
        except Exception:
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
