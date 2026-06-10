"""
knowledge/pattern_tracker.py -- Track recurring code transformations for auto-pattern discovery.

When the same text substitution (old -> new) appears 3+ times across different tasks,
it's promoted to auto_patterns.json so future runs can apply it instantly via
detect_and_fix_known_patterns() without needing an LLM call.

After promotion, each pattern carries hit counters so we can answer
"how often does this promoted pattern actually fire on subsequent runs?"
That's the convergence metric the self-learning loop needs to know if its
predictions hold up.
"""

import json
import threading
import time
from pathlib import Path
from typing import List, Optional
from logging_config import get_logger
logger = get_logger(__name__)

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

        # Find existing candidate with same old -> new
        found = None
        for c in candidates:
            if c.get("old") == old_text and c.get("new") == new_text:
                found = c
                break

        if found:
            found["count"] = found.get("count", 1) + 1
            if error_pattern not in found.get("error_patterns", []):
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


def record_hit(patterns_path: str, old_text: str, new_text: str) -> bool:
    """Record that a promoted pattern fired in a subsequent run.

    Called fire-and-forget (e.g. from a background thread) when the pattern
    fix loop in pipeline/error_parser.py applies an auto-learned pattern.
    Returns True if the pattern was found and incremented, False otherwise.

    Idempotent on concurrent calls — the lock serialises read-modify-write.
    """
    if not old_text or not new_text:
        return False

    try:
        with _LOCK:
            patterns = _load_json_list(patterns_path)
            for p in patterns:
                if p.get("old") == old_text and p.get("new") == new_text:
                    p["_hit_count"] = int(p.get("_hit_count", 0)) + 1
                    p["_last_hit"] = time.time()
                    _save_json_list(patterns_path, patterns)
                    return True
        return False
    except Exception as e:
        # Never let metric writes crash the pipeline
        logger.warning("record_hit_failed", extra={"error": str(e)})
        return False


def get_effectiveness_stats(patterns_path: str) -> dict:
    """Return summary stats on promoted-pattern effectiveness.

    Shape:
        {
            "total_patterns":   N,     # promoted patterns on disk
            "active_patterns":  M,     # promoted patterns with hit_count > 0
            "dormant_patterns": N - M, # promoted but never fired
            "total_hits":       sum(hit_count),
            "hit_rate":         active/total (0.0..1.0; 0.0 if no patterns),
        }

    "active" means "has fired at least once since promotion". The hit_rate
    is the convergence signal — a self-learning loop that promotes rules
    nothing ever uses isn't actually learning.
    """
    try:
        with _LOCK:
            patterns = _load_json_list(patterns_path)
    except Exception:
        patterns = []

    total = len(patterns)
    active = sum(1 for p in patterns if int(p.get("_hit_count", 0)) > 0)
    total_hits = sum(int(p.get("_hit_count", 0)) for p in patterns)
    hit_rate = round(active / total, 4) if total else 0.0

    return {
        "total_patterns": total,
        "active_patterns": active,
        "dormant_patterns": total - active,
        "total_hits": total_hits,
        "hit_rate": hit_rate,
    }


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
    logger.info(f"[PatternTracker] Promoted pattern: '{candidate['old']}' -> '{candidate['new']}' ({candidate.get('count', 0)} occurrences)")
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
