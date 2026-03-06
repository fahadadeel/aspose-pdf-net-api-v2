"""
knowledge/fix_history.py — Thread-safe fix history: record successful fixes, compute boosts.
"""

import json
import math
import time
import threading
from pathlib import Path
from typing import Dict, List

_LOCK = threading.Lock()
_MAX_ENTRIES = 500


def load_fix_history(path: str) -> List[dict]:
    """Load fix history from disk (thread-safe)."""
    with _LOCK:
        p = Path(path)
        if p.exists():
            try:
                data = json.loads(p.read_text(encoding="utf-8"))
                return data if isinstance(data, list) else []
            except Exception:
                return []
        return []


def save_fix_history(path: str, history: List[dict]) -> None:
    """Persist fix history to disk (thread-safe), capped at max entries."""
    with _LOCK:
        try:
            if len(history) > _MAX_ENTRIES:
                history = history[-_MAX_ENTRIES:]
            Path(path).write_text(json.dumps(history, indent=2, default=str), encoding="utf-8")
        except Exception:
            pass


def record_successful_fix(
    path: str,
    error_codes: List[str],
    rule_ids: List[str],
    catalog_patterns: List[str],
    attempt: int,
    prompt_hint: str = "",
) -> None:
    """Record a successful fix for future learning."""
    history = load_fix_history(path)
    history.append({
        "ts": time.time(),
        "error_codes": error_codes[:10],
        "rule_ids": rule_ids[:15],
        "catalog_patterns": catalog_patterns[:10],
        "attempt": attempt,
        "prompt_hint": prompt_hint[:120],
    })
    save_fix_history(path, history)


def get_boosted_rule_ids(path: str, error_codes: List[str]) -> Dict[str, float]:
    """Return rule IDs that previously fixed similar errors, with boost weights [0.05, 0.25]."""
    if not error_codes:
        return {}

    history = load_fix_history(path)
    if not history:
        return {}

    error_set = set(error_codes)
    now = time.time()
    boosts: Dict[str, float] = {}

    for entry in history:
        past_codes = set(entry.get("error_codes", []))
        overlap = error_set & past_codes
        if not overlap:
            continue
        overlap_ratio = len(overlap) / max(len(error_set), len(past_codes))
        age_days = (now - entry.get("ts", now)) / 86400.0
        recency = math.exp(-0.693 * age_days / 7.0)
        base_boost = 0.25 * overlap_ratio * recency
        for rid in entry.get("rule_ids", []):
            boosts[rid] = max(boosts.get(rid, 0.0), base_boost)

    return {k: max(0.05, min(0.25, v)) for k, v in boosts.items() if v >= 0.05}
