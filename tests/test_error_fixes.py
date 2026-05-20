"""Tests for knowledge/error_fixes.py — error fix matching and scoring."""

from knowledge.error_fixes import match_error_fixes, format_error_fixes_for_prompt


SAMPLE_FIXES = {
    "fix_path_ambiguous": {
        "errors": ["error CS0104: 'Path' is an ambiguous reference"],
        "note": "Use fully qualified System.IO.Path",
        "code": "var path = System.IO.Path.Combine(dir, file);",
        "_confidence": 1.0,
    },
    "fix_missing_using": {
        "errors": ["error CS0246: The type or namespace name 'Document' could not be found"],
        "note": "Add using Aspose.Pdf",
        "code": "using Aspose.Pdf;",
        "_confidence": 1.0,
    },
    "fix_auto_learned": {
        "errors": ["error CS0246: The type or namespace name 'PdfFileEditor'"],
        "note": "Use Facades namespace",
        "code": "using Aspose.Pdf.Facades;",
        "_confidence": 0.5,
    },
}


def test_matches_error_code_and_ranks():
    error_output = "error CS0104: 'Path' is an ambiguous reference between 'System.IO.Path' and 'Aspose.Pdf.Drawing.Path'"
    error_codes = ["CS0104"]

    results = match_error_fixes(SAMPLE_FIXES, error_output, error_codes)
    assert len(results) >= 1
    assert results[0]["id"] == "fix_path_ambiguous"


def test_confidence_weighting():
    error_output = "error CS0246: The type or namespace name 'PdfFileEditor' could not be found"
    error_codes = ["CS0246"]

    results = match_error_fixes(SAMPLE_FIXES, error_output, error_codes)
    assert len(results) >= 2
    # Curated fix (confidence 1.0) should rank above auto-learned (0.5)
    ids = [r["id"] for r in results]
    curated_idx = ids.index("fix_missing_using")
    auto_idx = ids.index("fix_auto_learned")
    assert curated_idx < auto_idx


def test_no_match_returns_empty():
    error_output = "error CS9999: Something completely unrelated"
    error_codes = ["CS9999"]

    results = match_error_fixes(SAMPLE_FIXES, error_output, error_codes)
    assert results == []


def test_format_error_fixes_for_prompt():
    fixes = [{"id": "fix1", "note": "Add using", "code": "using Aspose.Pdf;"}]
    text = format_error_fixes_for_prompt(fixes)
    assert "VERIFIED ERROR FIXES" in text
    assert "Add using" in text
    assert "using Aspose.Pdf;" in text


def test_format_empty_returns_empty():
    assert format_error_fixes_for_prompt([]) == ""
