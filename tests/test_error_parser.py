"""Tests for pipeline/error_parser.py — error extraction and pattern fixes."""

import pytest
from pipeline.error_parser import (
    strip_local_paths,
    extract_errors,
    parse_error_codes,
    detect_and_fix_known_patterns,
)


# ── strip_local_paths ──────────────────────────────────────────────────────────

def test_strip_unix_path():
    line = "/home/user/projects/build/Program.cs(10,5): error CS0246"
    assert strip_local_paths(line) == "Program.cs(10,5): error CS0246"


def test_strip_windows_path():
    line = r"C:\fahad\project\Program.cs(10,5): error CS0246"
    assert strip_local_paths(line) == "Program.cs(10,5): error CS0246"


def test_strip_paths_no_path():
    line = "error CS0246: type not found"
    assert strip_local_paths(line) == line


# ── extract_errors ─────────────────────────────────────────────────────────────

def test_extract_compiler_error():
    output = "Program.cs(5,1): error CS0246: The type 'Document' could not be found"
    lines = extract_errors(output)
    assert len(lines) == 1
    assert "CS0246" in lines[0]


def test_extract_runtime_exception():
    output = "Unhandled exception.\nSystem.IndexOutOfRangeException: Index was outside bounds."
    lines = extract_errors(output)
    assert any("IndexOutOfRangeException" in ln or "exception" in ln.lower() for ln in lines)


def test_extract_multiple_errors():
    output = (
        "Program.cs(5,1): error CS0246: Document not found\n"
        "Program.cs(8,3): error CS0104: Color is ambiguous\n"
        "Build FAILED."
    )
    lines = extract_errors(output)
    assert len(lines) == 2


def test_extract_respects_limit():
    lines_in = "\n".join(f"error CS000{i}: msg" for i in range(50))
    lines = extract_errors(lines_in, limit=10)
    assert len(lines) == 10


def test_extract_fallback_on_no_errors():
    output = "Something went wrong\nUnexpected state"
    lines = extract_errors(output)
    assert len(lines) > 0


def test_extract_empty_output():
    assert extract_errors("") == []


# ── parse_error_codes ──────────────────────────────────────────────────────────

def test_parse_cs_error_code():
    lines = ["error CS0246: The type or namespace name 'Document' could not be found"]
    errors = parse_error_codes(lines)
    assert len(errors) == 1
    assert errors[0].code == "CS0246"


def test_parse_member_name():
    lines = ["error CS1061: 'Page' does not contain a definition for 'AddText'"]
    errors = parse_error_codes(lines)
    assert errors[0].code == "CS1061"
    assert errors[0].member == "AddText"


def test_parse_runtime_exception():
    lines = ["Unhandled exception. System.IndexOutOfRangeException: Index was outside the bounds."]
    errors = parse_error_codes(lines)
    assert any(e.code == "RUNTIME" for e in errors)


def test_parse_deduplicates():
    lines = [
        "error CS0246: The type 'Foo' could not be found",
        "error CS0246: The type 'Foo' could not be found",
    ]
    errors = parse_error_codes(lines)
    assert len(errors) == 1


def test_parse_empty():
    assert parse_error_codes([]) == []


# ── detect_and_fix_known_patterns ──────────────────────────────────────────────

def test_fix_rectangle_ambiguity():
    code = "var r = new Rectangle(0, 0, 100, 100);"
    error = "error CS0104: 'Rectangle' is an ambiguous reference between 'Aspose.Pdf.Rectangle' and 'System.Drawing.Rectangle'"
    fixed, rule = detect_and_fix_known_patterns(code, error)
    assert fixed is not None
    assert "Aspose.Pdf.Rectangle" in fixed


def test_fix_point_ambiguity():
    code = "var p = new Point(10, 20);"
    error = "error CS0104: 'Point' is an ambiguous reference"
    fixed, rule = detect_and_fix_known_patterns(code, error)
    assert fixed is not None
    assert "Aspose.Pdf.Point" in fixed


def test_fix_checkbox_casing():
    code = "var cb = new CheckBoxField(page, rect);"
    error = "error CS0246: The type or namespace name 'CheckBoxField' could not be found"
    fixed, rule = detect_and_fix_known_patterns(code, error)
    assert fixed is not None
    assert "CheckboxField" in fixed


def test_fix_markdown_load_options():
    code = "var opts = new MarkdownLoadOptions();"
    error = "error CS0246: The type or namespace name 'MarkdownLoadOptions' could not be found"
    fixed, rule = detect_and_fix_known_patterns(code, error)
    assert fixed is not None
    assert "MdLoadOptions" in fixed


def test_fix_tex_load_options_casing():
    code = "var opts = new TexLoadOptions();"
    error = "error CS0246: The type or namespace name 'TexLoadOptions' could not be found"
    fixed, rule = detect_and_fix_known_patterns(code, error)
    assert fixed is not None
    assert "TeXLoadOptions" in fixed


def test_no_fix_returns_none():
    code = "var doc = new Document();"
    error = "error CS9999: some unknown error"
    fixed, rule = detect_and_fix_known_patterns(code, error)
    assert fixed is None
    assert rule is None


def test_fix_returns_rule_json():
    code = "var r = new Rectangle(0, 0, 100, 100);"
    error = "error CS0104: 'Rectangle' is an ambiguous reference"
    fixed, rule = detect_and_fix_known_patterns(code, error)
    assert rule is not None
    assert "description" in rule


def test_fix_unqualified_rectangle_only():
    # The regex targets bare `Rectangle` — already-qualified usage is a separate case
    # handled upstream by namespace restriction prompts, not by pattern fixes
    code = "var r = new Rectangle(0, 0, 100, 100);"
    error = "error CS0104: 'Rectangle' is an ambiguous reference"
    fixed, rule = detect_and_fix_known_patterns(code, error)
    assert fixed is not None
    assert "Aspose.Pdf.Rectangle" in fixed
