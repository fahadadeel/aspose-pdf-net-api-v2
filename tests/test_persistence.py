"""Tests for persistence.py — disk-backed task results."""

import json
import pytest
from persistence import (
    save_result, load_results, is_task_passed,
    load_cached_task, get_resume_stats, clear_results,
    update_task_metadata, versioned_results_dir,
)


@pytest.fixture
def results_dir(tmp_path):
    return str(tmp_path / "results" / "26.4.0")


def test_save_and_load_roundtrip(results_dir):
    save_result(results_dir, "Conversion", task_id="100",
                task_text="Convert PDF to HTML", status="PASSED",
                stage="baseline", badge="baseline",
                code="using System;\nclass Program { static void Main() {} }")

    results = load_results(results_dir, "Conversion")
    assert "100" in results
    assert results["100"]["status"] == "PASSED"
    assert results["100"]["stage"] == "baseline"
    assert results["100"]["task"] == "Convert PDF to HTML"


def test_is_task_passed(results_dir):
    save_result(results_dir, "Conversion", task_id="100",
                task_text="Convert PDF", status="PASSED", code="// ok")
    save_result(results_dir, "Conversion", task_id="101",
                task_text="Convert HTML", status="FAILED", code="// fail")

    assert is_task_passed(results_dir, "Conversion", "100", "Convert PDF") is True
    assert is_task_passed(results_dir, "Conversion", "101", "Convert HTML") is False
    assert is_task_passed(results_dir, "Conversion", "999", "Missing") is False


def test_load_cached_task_returns_code_for_passed(results_dir):
    code = "using Aspose.Pdf;\nclass Program { static void Main() {} }"
    save_result(results_dir, "Document", task_id="200",
                task_text="Save PDF", status="PASSED", code=code)

    cached = load_cached_task(results_dir, "Document", "200", "Save PDF")
    assert cached is not None
    assert cached["code"] == code
    assert cached["badge"] in ("CACHED", "")


def test_load_cached_task_returns_none_for_failed(results_dir):
    save_result(results_dir, "Document", task_id="201",
                task_text="Broken task", status="FAILED", code="// bad")

    cached = load_cached_task(results_dir, "Document", "201", "Broken task")
    assert cached is None


def test_get_resume_stats(results_dir):
    save_result(results_dir, "Forms", task_id="300",
                task_text="Fill form", status="PASSED", code="// ok")
    save_result(results_dir, "Forms", task_id="301",
                task_text="Read form", status="PASSED", code="// ok")
    save_result(results_dir, "Forms", task_id="302",
                task_text="Bad form", status="FAILED", code="// fail")

    stats = get_resume_stats(results_dir, "Forms")
    assert stats["passed"] == 2
    assert stats["failed"] == 1
    assert stats["total"] == 3


def test_passed_cleans_up_old_failed_file(results_dir):
    # First save as FAILED
    save_result(results_dir, "Text", task_id="400",
                task_text="Extract text", status="FAILED", code="// v1 bad")

    from persistence import _code_dir, _code_filename
    failed_file = _code_dir(results_dir, "Text", "FAILED") / _code_filename("400", "Extract text")
    assert failed_file.exists()

    # Now save as PASSED — should remove the failed file
    save_result(results_dir, "Text", task_id="400",
                task_text="Extract text", status="PASSED", code="// v2 good")

    assert not failed_file.exists()


def test_update_task_metadata(results_dir):
    save_result(results_dir, "Images", task_id="500",
                task_text="Add image", status="PASSED", code="// ok",
                metadata={"title": "Old Title"})

    updated = update_task_metadata(results_dir, "Images", "500",
                                   {"title": "New Title", "difficulty": "easy"})
    assert updated is True

    results = load_results(results_dir, "Images")
    assert results["500"]["metadata"]["title"] == "New Title"
    assert results["500"]["metadata"]["difficulty"] == "easy"


def test_versioned_results_dir():
    assert versioned_results_dir("results", "26.4.0") == "results/26.4.0"
    assert versioned_results_dir("results", "") == "results"
