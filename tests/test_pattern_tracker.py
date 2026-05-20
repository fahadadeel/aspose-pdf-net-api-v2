"""Tests for knowledge/pattern_tracker.py — auto-pattern discovery."""

import json
import pytest
from knowledge.pattern_tracker import record_transformation, load_auto_patterns


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
        result = record_transformation(
            tracker_paths["candidates"], tracker_paths["patterns"],
            error_pattern="CS0104", old_text="old", new_text="new",
            promotion_threshold=3,
        )

    # Should still only have 1 pattern
    patterns = load_auto_patterns(tracker_paths["patterns"])
    assert len(patterns) == 1
