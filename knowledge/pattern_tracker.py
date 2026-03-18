"""
knowledge/pattern_tracker.py — Track recurring code transformations for auto-pattern discovery.

When the same text substitution (old → new) appears 3+ times across different tasks,
it's promoted to auto_patterns.json so future runs can apply it instantly via
detect_and_fix_known_patterns() without needing an LLM call.
"""

import json
import threading
from pathlib import Path
from typing import List, Optional

_LOCK = threading.Lock()
_MAX_CANDIDATES = 500
_PROMOTION_THRESHOLD = 3  # occurrences before auto-promotion
_MAX_PATTERNS = 100


def record_transformation(
    candidates_path: str,
    patterns_path: str,
    error_pattern: str,
    old_text: str,
    new_text: str,
    promotion_threshold: int = _PROMOTION_THRESHOLD,
) -> Optional[dict]:
    """Record a code transformation. Returns promoted pattern if threshold reached."""
    if not old_text or not new_text or old_text == new_text:
        return None

    with _LOCK:
        candidates = _load_json_list(candidates_path)

        # Find existing candidate with same old → new
        found = None
        for c in candidates:
            if c.get("old") == old_text and c.get("new") == new_text:
                found = c
                break

        if found:
            found["count"] = found.get("count", 1) + 1
            if not error_pattern in found.get("error_patterns", []):
                found.setdefault("error_patterns", []).append(error_pattern)
        else:
            candidates.append({
                "old": old_text,
                "new": new_text,
                "error_patterns": [error_pattern] if error_pattern else [],
                "count": 1,
            })

        # Prune oldest if over cap
        if len(candidates) > _MAX_CANDIDATES:
            candidates = candidates[-_MAX_CANDIDATES:]

        _save_json_list(candidates_path, candidates)

        # Check for promotion
        if found and found.get("count", 0) >= promotion_threshold:
            pattern = _promote_candidate(patterns_path, found)
            if pattern:
                # Remove from candidates
                candidates = [c for c in candidates if not (c.get("old") == old_text and c.get("new") == new_text)]
                _save_json_list(candidates_path, candidates)
                return pattern

    return None


def load_auto_patterns(path: str) -> List[dict]:
    """Load promoted auto patterns for use in detect_and_fix_known_patterns."""
    with _LOCK:
        return _load_json_list(path)


def _promote_candidate(patterns_path: str, candidate: dict) -> Optional[dict]:
    """Promote a candidate to auto_patterns.json."""
    patterns = _load_json_list(patterns_path)

    # Check if already exists
    for p in patterns:
        if p.get("old") == candidate["old"] and p.get("new") == candidate["new"]:
            return None  # already promoted

    # Build error pattern regex from collected patterns
    error_patterns = candidate.get("error_patterns", [])
    if error_patterns:
        # Escape and combine patterns
        import re
        escaped = [re.escape(ep) for ep in error_patterns[:3]]
        pattern_regex = "|".join(escaped)
    else:
        pattern_regex = re.escape(candidate["old"])

    new_pattern = {
        "pattern": pattern_regex,
        "old": candidate["old"],
        "new": candidate["new"],
        "regex": False,
        "rule": {
            "description": f"Auto-learned: replace '{candidate['old']}' with '{candidate['new']}'",
            "pattern": pattern_regex,
        },
        "_auto": True,
        "_occurrences": candidate.get("count", _PROMOTION_THRESHOLD),
    }

    patterns.append(new_pattern)

    # Cap
    if len(patterns) > _MAX_PATTERNS:
        patterns = patterns[-_MAX_PATTERNS:]

    _save_json_list(patterns_path, patterns)
    print(f"[PatternTracker] Promoted pattern: '{candidate['old']}' → '{candidate['new']}' ({candidate.get('count', 0)} occurrences)")
    return new_pattern


def _load_json_list(path: str) -> list:
    p = Path(path)
    if not p.exists():
        return []
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except (json.JSONDecodeError, Exception):
        return []


def _save_json_list(path: str, data: list):
    Path(path).write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
