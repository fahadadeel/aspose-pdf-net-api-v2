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
    metadata: dict = field(default_factory=dict)
    # metadata keys (populated by own-LLM path only):
    #   title, filename, description, tags, apis_used, difficulty


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
    build_log: str = ""  # Last build error log (for post-pipeline rule learning)
    metadata: dict = field(default_factory=dict)
    # metadata keys (from baseline LLM generation, kept as-is even if code is fixed later):
    #   title       — human-readable example title
    #   filename    — recommended kebab-case filename stem (no .cs)
    #   description — 1-2 sentence summary of what the example demonstrates
    #   tags        — list of short keyword strings
    #   apis_used   — list of Aspose.Pdf API class/method names
    #   difficulty  — beginner / intermediate / advanced


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
