"""Tests for PipelineRunner.execute() — all pipeline stage paths."""

import pytest
from unittest.mock import patch, MagicMock

from config import AppConfig
from pipeline.models import TaskInput, StageOutcome, PipelineResult
from pipeline.runner import PipelineRunner


@pytest.fixture
def config(tmp_path):
    cfg = AppConfig()
    cfg.workspace_path = str(tmp_path)
    cfg.pipeline.llm_fix_attempts = 0       # disable LLM fix stage
    cfg.pipeline.auto_learn_on_success = False
    cfg.pipeline.final_llm_after_regen_fail = False
    return cfg


@pytest.fixture
def task():
    return TaskInput(task="Convert PDF to DOCX", category="conversion")


def _make_runner(config):
    """Create PipelineRunner with all external deps mocked."""
    with patch("pipeline.runner.MCPClient"), \
         patch("pipeline.runner.LLMClient"), \
         patch("pipeline.runner.DotnetBuilder"), \
         patch("pipeline.runner.RuleSearchEngine"):
        return PipelineRunner(config)


# ── Baseline success ───────────────────────────────────────────────────────────

def test_baseline_success_returns_success_stage(config, task):
    runner = _make_runner(config)

    success_outcome = StageOutcome(success=True, code="var doc = new Document();", metadata={})
    runner.llm.available = False

    with patch("pipeline.runner.stages") as mock_stages:
        mock_stages.run_baseline.return_value = success_outcome
        result = runner.execute(task)

    assert result.status == "SUCCESS"
    assert result.stage == "baseline"
    assert result.generated_code == "var doc = new Document();"


def test_baseline_success_no_further_stages_called(config, task):
    runner = _make_runner(config)
    runner.llm.available = False

    with patch("pipeline.runner.stages") as mock_stages:
        mock_stages.run_baseline.return_value = StageOutcome(success=True, code="// ok")
        runner.execute(task)
        mock_stages.run_llm_fix_loop.assert_not_called()
        mock_stages.run_regen_loop.assert_not_called()


# ── API_FAILED (no code returned) ─────────────────────────────────────────────

def test_baseline_no_code_returns_api_failed(config, task):
    runner = _make_runner(config)

    with patch("pipeline.runner.stages") as mock_stages:
        mock_stages.run_baseline.return_value = StageOutcome(
            success=False, code="", build_log="MCP timeout"
        )
        result = runner.execute(task)

    assert result.status == "API_FAILED"
    assert result.stage == "baseline"


# ── Pattern fix success ────────────────────────────────────────────────────────

def test_pattern_fix_success(config, task):
    runner = _make_runner(config)
    runner.llm.available = False
    runner.builder.write_program_cs = MagicMock()
    runner.builder.build_and_run = MagicMock(return_value=(True, "Build succeeded"))

    failed_baseline = StageOutcome(
        success=False, code="var r = new Rectangle();",
        build_log="error CS0104: 'Rectangle' is an ambiguous reference"
    )

    with patch("pipeline.runner.stages") as mock_stages, \
         patch("pipeline.runner.detect_and_fix_known_patterns") as mock_fix:
        mock_stages.run_baseline.return_value = failed_baseline
        mock_fix.return_value = ("var r = new Aspose.Pdf.Rectangle();", '{"description": "fix"}')

        result = runner.execute(task)

    assert result.status == "SUCCESS"
    assert result.stage == "pattern_fix"
    assert result.fixed_code == "var r = new Aspose.Pdf.Rectangle();"


def test_pattern_fix_no_match_continues_to_next_stage(config, task):
    runner = _make_runner(config)
    runner.llm.available = False

    failed_baseline = StageOutcome(
        success=False, code="// broken", build_log="error CS9999: unknown"
    )
    failed_regen = StageOutcome(success=False, code="// still broken", build_log="still failing")

    with patch("pipeline.runner.stages") as mock_stages, \
         patch("pipeline.runner.detect_and_fix_known_patterns", return_value=(None, None)):
        mock_stages.run_baseline.return_value = failed_baseline
        mock_stages.run_context_enrichment.return_value = "enriched task"
        mock_stages.run_regen_loop.return_value = failed_regen

        result = runner.execute(task)

    assert result.status == "FAILED"


# ── All stages exhausted ───────────────────────────────────────────────────────

def test_all_stages_fail_returns_failed(config, task):
    runner = _make_runner(config)
    runner.llm.available = False

    failed = StageOutcome(success=False, code="// code", build_log="error")

    with patch("pipeline.runner.stages") as mock_stages, \
         patch("pipeline.runner.detect_and_fix_known_patterns", return_value=(None, None)):
        mock_stages.run_baseline.return_value = failed
        mock_stages.run_context_enrichment.return_value = "enriched"
        mock_stages.run_regen_loop.return_value = failed

        result = runner.execute(task)

    assert result.status == "FAILED"
    assert result.stage == "exhausted"


# ── Result metadata ────────────────────────────────────────────────────────────

def test_result_preserves_task_and_category(config, task):
    runner = _make_runner(config)
    runner.llm.available = False

    with patch("pipeline.runner.stages") as mock_stages:
        mock_stages.run_baseline.return_value = StageOutcome(success=True, code="// ok")
        result = runner.execute(task)

    assert result.task == "Convert PDF to DOCX"
    assert result.category == "conversion"


def test_failed_result_includes_build_log(config, task):
    runner = _make_runner(config)
    runner.llm.available = False

    failed = StageOutcome(success=False, code="// code", build_log="error CS0246: type not found")

    with patch("pipeline.runner.stages") as mock_stages, \
         patch("pipeline.runner.detect_and_fix_known_patterns", return_value=(None, None)):
        mock_stages.run_baseline.return_value = failed
        mock_stages.run_context_enrichment.return_value = "enriched"
        mock_stages.run_regen_loop.return_value = failed

        result = runner.execute(task)

    assert "CS0246" in result.build_log
