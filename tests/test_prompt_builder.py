"""Tests for pipeline/prompt_builder.py — prompt construction."""

from pipeline.prompt_builder import (
    build_namespace_restriction,
    build_retry_instruction,
    build_enriched_prompt,
    format_rules_for_prompt,
)


# ── build_namespace_restriction ────────────────────────────────────────────────

def test_non_facade_category_restricts_namespaces():
    result = build_namespace_restriction("annotations")
    assert "Aspose.Pdf.Facades" in result
    assert "Do NOT use" in result


def test_facades_category_returns_empty():
    result = build_namespace_restriction("facades")
    assert result == ""


def test_facades_in_category_name_returns_empty():
    result = build_namespace_restriction("pdf-facades-stamps")
    assert result == ""


def test_empty_category_restricts():
    result = build_namespace_restriction("")
    assert "Aspose.Pdf.Facades" in result


def test_custom_exclude_namespaces():
    result = build_namespace_restriction("conversion", exclude_namespaces=["My.Namespace"])
    assert "My.Namespace" in result


def test_empty_exclude_list_falls_back_to_defaults():
    # [] is falsy — code falls back to default excluded namespaces
    result = build_namespace_restriction("annotations", exclude_namespaces=[])
    assert "Aspose.Pdf.Facades" in result


# ── build_retry_instruction ────────────────────────────────────────────────────

def test_attempt_1_returns_empty():
    assert build_retry_instruction(1) == ""


def test_attempt_2_no_errors_returns_instruction():
    result = build_retry_instruction(2)
    assert "fully qualified" in result.lower()
    assert "System.Drawing" in result


def test_attempt_2_with_cs0104_returns_specific_instruction():
    result = build_retry_instruction(2, error_codes=["CS0104"])
    assert "CS0104" in result or "ambiguity" in result.lower()


def test_attempt_3_returns_critical_instruction():
    result = build_retry_instruction(3)
    assert "CRITICAL" in result
    assert "Aspose.Pdf.Color" in result
    assert "Aspose.Pdf.Rectangle" in result


def test_attempt_4_also_returns_critical():
    result = build_retry_instruction(4)
    assert "CRITICAL" in result


# ── format_rules_for_prompt ────────────────────────────────────────────────────

def test_format_single_rule():
    rules = [{
        "id": "rule-001",
        "category": "conversion",
        "semantic_summary": "Use Document.Save() to convert",
        "api_surface": ["Document.Save"],
        "warnings": ["Always dispose Document"],
        "rules": ["Call doc.Save(outputPath)"],
        "confidence": 0.98,
    }]
    result = format_rules_for_prompt(rules)
    assert "rule-001" in result
    assert "Document.Save" in result
    assert "Always dispose Document" in result
    assert "high confidence" in result


def test_format_empty_rules_returns_empty():
    assert format_rules_for_prompt([]) == ""


def test_format_rule_without_optional_fields():
    rules = [{"id": "rule-002", "semantic_summary": "Basic rule", "confidence": 0.9}]
    result = format_rules_for_prompt(rules)
    assert "rule-002" in result
    assert "Basic rule" in result


# ── build_enriched_prompt ──────────────────────────────────────────────────────

def test_enriched_prompt_contains_task():
    result = build_enriched_prompt("Convert PDF to DOCX", "error CS0246")
    assert "Convert PDF to DOCX" in result


def test_enriched_prompt_contains_errors():
    result = build_enriched_prompt("task", "error CS0246: type not found")
    assert "error CS0246" in result
    assert "Previous attempt" in result


def test_enriched_prompt_includes_decomposed_plan():
    result = build_enriched_prompt("task", "error", decomposed_plan="Step 1: Load PDF")
    assert "Step 1: Load PDF" in result


def test_enriched_prompt_includes_catalog_guidance():
    result = build_enriched_prompt("task", "error", catalog_guidance=["Use Document.Save()"])
    assert "KNOWN API FIXES" in result
    assert "Document.Save()" in result


def test_enriched_prompt_includes_retry_instruction():
    result = build_enriched_prompt("task", "error", retry_instruction="Use fully qualified names")
    assert "Use fully qualified names" in result


def test_enriched_prompt_ends_with_correction_request():
    result = build_enriched_prompt("task", "error")
    assert "generate corrected code" in result.lower()


def test_enriched_prompt_omits_empty_sections():
    result = build_enriched_prompt("task", "error")
    assert "KNOWN API FIXES" not in result
    assert "Relevant API Patterns" not in result
