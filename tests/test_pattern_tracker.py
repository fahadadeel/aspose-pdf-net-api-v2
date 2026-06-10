"""Tests for knowledge/pattern_tracker.py — auto-pattern discovery + hit tracking."""

import json
import pytest
from knowledge.pattern_tracker import (
    record_transformation,
    load_auto_patterns,
    record_hit,
    get_effectiveness_stats,
)


@pytest.fixture
def tracker_paths(tmp_path):
    return {
        "candidates": str(tmp_path / "candidates.json"),
        "patterns": str(tmp_path / "auto_patterns.json"),
    }


def test_records_and_increments(tracker_paths):
    for _ in range(2):
        record_transformation(
            tracker_paths["candidates"], tracker_paths["patterns"],
            error_pattern="CS0104", old_text="Path.Combine", new_text="System.IO.Path.Combine",
        )

    candidates = json.loads(open(tracker_paths["candidates"]).read())
    assert len(candidates) == 1
    assert candidates[0]["count"] == 2


def test_promotes_at_threshold(tracker_paths):
    result = None
    for i in range(3):
        result = record_transformation(
            tracker_paths["candidates"], tracker_paths["patterns"],
            error_pattern="CS0104", old_text="Path.Combine", new_text="System.IO.Path.Combine",
            promotion_threshold=3,
        )

    # Should be promoted on the 3rd call
    assert result is not None
    assert result["old"] == "Path.Combine"
    assert result["new"] == "System.IO.Path.Combine"

    # Should be in auto_patterns.json
    patterns = load_auto_patterns(tracker_paths["patterns"])
    assert len(patterns) == 1

    # Should be removed from candidates
    candidates = json.loads(open(tracker_paths["candidates"]).read())
    assert len(candidates) == 0


def test_no_duplicate_promotion(tracker_paths):
    # Promote once
    for _ in range(3):
        record_transformation(
            tracker_paths["candidates"], tracker_paths["patterns"],
            error_pattern="CS0104", old_text="old", new_text="new",
            promotion_threshold=3,
        )

    # Try to promote again with fresh candidates
    for _ in range(3):
        record_transformation(
            tracker_paths["candidates"], tracker_paths["patterns"],
            error_pattern="CS0104", old_text="old", new_text="new",
            promotion_threshold=3,
        )

    # Should still only have 1 pattern
    patterns = load_auto_patterns(tracker_paths["patterns"])
    assert len(patterns) == 1


# ── record_hit / get_effectiveness_stats ────────────────────────────────────

def _promote_pattern(paths, old="old1", new="new1", threshold=3):
    """Helper: promote one pattern by calling record_transformation threshold times."""
    for _ in range(threshold):
        record_transformation(
            paths["candidates"], paths["patterns"],
            error_pattern="CS0104", old_text=old, new_text=new,
            promotion_threshold=threshold,
        )


def test_record_hit_increments_count_and_timestamp(tracker_paths):
    _promote_pattern(tracker_paths)
    assert record_hit(tracker_paths["patterns"], "old1", "new1") is True

    patterns = load_auto_patterns(tracker_paths["patterns"])
    assert patterns[0]["_hit_count"] == 1
    assert patterns[0]["_last_hit"] > 0


def test_record_hit_multiple_calls_accumulate(tracker_paths):
    _promote_pattern(tracker_paths)
    for _ in range(5):
        record_hit(tracker_paths["patterns"], "old1", "new1")

    patterns = load_auto_patterns(tracker_paths["patterns"])
    assert patterns[0]["_hit_count"] == 5


def test_record_hit_unknown_pattern_returns_false(tracker_paths):
    _promote_pattern(tracker_paths)
    assert record_hit(tracker_paths["patterns"], "nope", "neither") is False

    # Original pattern's hit count untouched
    patterns = load_auto_patterns(tracker_paths["patterns"])
    assert patterns[0].get("_hit_count", 0) == 0


def test_record_hit_empty_strings_returns_false(tracker_paths):
    _promote_pattern(tracker_paths)
    assert record_hit(tracker_paths["patterns"], "", "new1") is False
    assert record_hit(tracker_paths["patterns"], "old1", "") is False


def test_record_hit_missing_file_returns_false(tmp_path):
    # File doesn't exist yet
    assert record_hit(str(tmp_path / "ghost.json"), "x", "y") is False


def test_effectiveness_stats_empty_file(tmp_path):
    path = str(tmp_path / "auto_patterns.json")
    stats = get_effectiveness_stats(path)
    assert stats == {
        "total_patterns": 0,
        "active_patterns": 0,
        "dormant_patterns": 0,
        "total_hits": 0,
        "hit_rate": 0.0,
    }


def test_effectiveness_stats_all_dormant(tracker_paths):
    _promote_pattern(tracker_paths, old="old1", new="new1")
    _promote_pattern(tracker_paths, old="old2", new="new2")

    stats = get_effectiveness_stats(tracker_paths["patterns"])
    assert stats["total_patterns"] == 2
    assert stats["active_patterns"] == 0
    assert stats["dormant_patterns"] == 2
    assert stats["total_hits"] == 0
    assert stats["hit_rate"] == 0.0


def test_effectiveness_stats_mixed(tracker_paths):
    _promote_pattern(tracker_paths, old="old1", new="new1")
    _promote_pattern(tracker_paths, old="old2", new="new2")
    _promote_pattern(tracker_paths, old="old3", new="new3")

    # Fire pattern 1 three times, pattern 2 once, leave pattern 3 dormant
    for _ in range(3):
        record_hit(tracker_paths["patterns"], "old1", "new1")
    record_hit(tracker_paths["patterns"], "old2", "new2")

    stats = get_effectiveness_stats(tracker_paths["patterns"])
    assert stats["total_patterns"] == 3
    assert stats["active_patterns"] == 2
    assert stats["dormant_patterns"] == 1
    assert stats["total_hits"] == 4
    # 2 active / 3 total = 0.6667
    assert stats["hit_rate"] == pytest.approx(0.6667, rel=0.01)


def test_effectiveness_stats_all_active(tracker_paths):
    _promote_pattern(tracker_paths, old="old1", new="new1")
    record_hit(tracker_paths["patterns"], "old1", "new1")

    stats = get_effectiveness_stats(tracker_paths["patterns"])
    assert stats["hit_rate"] == 1.0
