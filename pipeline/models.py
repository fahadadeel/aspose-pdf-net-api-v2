"""
pipeline/models.py — Data classes used throughout the pipeline.
"""

from dataclasses import dataclass, field
from typing import List, Optional


@dataclass
class TaskInput:
    """Input to the pipeline."""
    task: str
    category: str = ""
    product: str = "aspose.pdf"


@dataclass
class BuildResult:
    """Result of a .NET build or run operation."""
    ok: bool
    log: str


@dataclass
class StageOutcome:
    """Result of one pipeline stage."""
    success: bool
    code: str = ""
    stage: str = ""
    rule: str = ""
    build_log: str = ""


@dataclass
class PipelineResult:
    """Final result returned by PipelineRunner.execute()."""
    task: str
    category: str
    product: str
    generated_code: str = ""
    fixed_code: str = ""
    rule: str = ""
    status: str = ""  # SUCCESS, FAILED, API_FAILED
    stage: str = ""   # baseline, pattern_fix, llm_fix, regen, final_llm
    attempts: int = 1


@dataclass
class ParsedError:
    """Structured error parsed from build output."""
    code: str       # CS1061, RUNTIME, etc.
    message: str
    member: str = ""


@dataclass
class RunOptions:
    """Per-run overrides for pipeline behavior."""
    use_retrieve_examples_on_llm_fail: bool = True
    decompose_on_llm_fail: bool = False
    final_llm_after_regen_fail: bool = True
