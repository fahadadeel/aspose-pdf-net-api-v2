"""
pipeline/error_parser.py — Extract and parse build errors, apply known pattern fixes.
"""

import json
import re
from typing import List, Optional, Tuple

from pipeline.models import ParsedError


def strip_local_paths(text: str) -> str:
    """Remove local absolute file paths from error messages."""
    text = re.sub(r"/[^:]+/(\w+\.\w+)", r"\1", text)
    text = re.sub(r"[A-Z]:[^:]+\\(\w+\.\w+)", r"\1", text)
    return text


def extract_errors(error_output: str, limit: int = 30) -> List[str]:
    """Extract error/warning lines from dotnet build output."""
    lines: List[str] = []
    for line in error_output.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        lower = stripped.lower()
        if "error" in lower or "warning" in lower:
            lines.append(strip_local_paths(stripped))
        elif "exception" in lower or "unhandled" in lower:
            lines.append(strip_local_paths(stripped))
        elif stripped.startswith("at ") and "." in stripped and lines:
            lines.append(strip_local_paths(stripped[:200]))
        if len(lines) >= limit:
            break

    # Fallback: if no structured errors found
    if not lines and error_output.strip():
        raw = [l.strip() for l in error_output.splitlines() if l.strip()]
        for t in raw[-5:]:
            lines.append(strip_local_paths(t[:200]))
    return lines


def parse_error_codes(error_lines: List[str]) -> List[ParsedError]:
    """Parse structured error info from raw error lines."""
    errors: List[ParsedError] = []
    seen: set = set()

    for line in error_lines:
        # Compiler errors: error CS1061: ...
        m = re.search(r"error (CS\d{4}):\s*(.+)", line)
        if m:
            code, message = m.group(1), m.group(2).strip()
            member_match = re.search(r"does not contain a definition for '(\w+)'", message)
            member = member_match.group(1) if member_match else ""
            key = f"{code}:{member}"
            if key not in seen:
                seen.add(key)
                errors.append(ParsedError(code=code, message=message[:200], member=member))
            continue

        # Runtime exceptions
        exc = re.search(r"(?:Unhandled exception\.\s*)?(?:System\.)?(\w*Exception):\s*(.+)", line)
        if exc:
            exc_type, exc_msg = exc.group(1), exc.group(2).strip()
            key = f"RUNTIME:{exc_type}"
            if key not in seen:
                seen.add(key)
                errors.append(ParsedError(code="RUNTIME", message=f"{exc_type}: {exc_msg[:200]}", member=exc_type))

    return errors


# Known pattern fixes — applied before LLM/MCP retry
_KNOWN_FIXES = [
    {
        "pattern": r"error CS0103.*'TextAnnotationIcon' does not exist",
        "old": "TextAnnotationIcon",
        "new": "TextIcon",
        "regex": False,
        "rule": {"description": "Use TextIcon enum instead of TextAnnotationIcon", "pattern": "Icon = TextIcon.{IconType}"},
    },
    {
        "pattern": r"(?s)error CS0104.*'Point' is an ambiguous reference",
        "old": r"\bPoint\b",
        "new": "Aspose.Pdf.Point",
        "regex": True,
        "rule": {"description": "Disambiguate Point to Aspose.Pdf.Point", "pattern": "Aspose.Pdf.Point"},
    },
    {
        "pattern": r"(?s)error CS0104.*'Rectangle' is an ambiguous reference",
        "old": r"\bRectangle\b",
        "new": "Aspose.Pdf.Rectangle",
        "regex": True,
        "rule": {"description": "Disambiguate Rectangle to Aspose.Pdf.Rectangle", "pattern": "Aspose.Pdf.Rectangle"},
    },

    {
        "pattern": r"(?s)error CS0246.*'MhtSaveOptions'",
        "old": "MhtSaveOptions",
        "new": "HtmlSaveOptions",
        "regex": False,
        "rule": {"description": "MhtSaveOptions does not exist; use HtmlSaveOptions or SaveFormat.MHT", "pattern": "HtmlSaveOptions"},
    },
    {
        "pattern": r"(?s)error CS0103.*'CaretAnnotationSymbol'",
        "old": "CaretAnnotationSymbol",
        "new": "CaretSymbol",
        "regex": False,
        "rule": {"description": "CaretAnnotationSymbol enum does not exist; use CaretSymbol", "pattern": "CaretSymbol"},
    },
    {
        "pattern": r"(?s)error CS0117.*'WatermarkAnnotation'.*'Rotation'",
        "old": ".Rotation",
        "new": ".Rotate",
        "regex": False,
        "rule": {"description": "WatermarkAnnotation has no Rotation property; use Rotate", "pattern": ".Rotate"},
    },
    {
        "pattern": r"(?s)error CS0117.*'ScreenAnnotation'.*'ActivateOn'",
        "old": r"ActivateOn\s*=\s*[^,;]+[,;]?\s*\n?",
        "new": "",
        "regex": True,
        "rule": {"description": "ScreenAnnotation has no ActivateOn property; remove it", "pattern": "Remove ActivateOn"},
    },
    {
        "pattern": r"(?s)error CS0138.*'LoadOptions'.*is a type",
        "old": "using Aspose.Pdf.LoadOptions;\n",
        "new": "",
        "regex": False,
        "rule": {"description": "LoadOptions is a class, not a namespace; remove the using directive", "pattern": "Remove using Aspose.Pdf.LoadOptions"},
    },
    {
        "pattern": r"(?s)error CS0104.*'Color' is an ambiguous reference",
        "old": r"(?<!\.)(?<!Aspose\.Pdf\.)(?<!System\.Drawing\.)Color\.",
        "new": "Aspose.Pdf.Color.",
        "regex": True,
        "rule": {"description": "Disambiguate Color to Aspose.Pdf.Color", "pattern": "Aspose.Pdf.Color"},
    },

    # ── Facades Stamps patterns ──
    {
        "pattern": r"(?s)error CS0104.*'Stamp' is an ambiguous reference",
        "old": r"(?<!Aspose\.Pdf\.Facades\.)(?<!Aspose\.Pdf\.)\bStamp\b",
        "new": "Aspose.Pdf.Facades.Stamp",
        "regex": True,
        "rule": {"description": "Disambiguate Stamp to Aspose.Pdf.Facades.Stamp", "pattern": "Aspose.Pdf.Facades.Stamp"},
    },
    {
        "pattern": r"(?s)error CS1061.*'Stamp'.*'SetText'",
        "old": r"\.SetText\(",
        "new": ".BindLogo(",
        "regex": True,
        "rule": {"description": "Stamp has no SetText method; use BindLogo(formattedText)", "pattern": "stamp.BindLogo(ft)"},
    },
    {
        "pattern": r"(?s)error CS1061.*'Stamp'.*'SetOpacity'",
        "old": r"\.SetOpacity\(([^)]+)\)",
        "new": r".Opacity = \1",
        "regex": True,
        "rule": {"description": "Stamp has no SetOpacity method; use Opacity property", "pattern": "stamp.Opacity = value"},
    },
    {
        "pattern": r"(?s)error CS1061.*'Stamp'.*'(?:SetFont|SetFontSize|SetTextColor)'",
        "old": r"[ \t]*\w+\.(?:SetFont|SetFontSize|SetTextColor)\(.*?\);\s*\n?",
        "new": "",
        "regex": True,
        "rule": {"description": "Stamp has no SetFont/SetFontSize/SetTextColor; configure FormattedText via constructor", "pattern": "Remove SetFont/SetFontSize/SetTextColor calls"},
    },
    {
        "pattern": r"(?s)error CS0618.*'PdfFileStamp\.InputFile'.*obsolete",
        "old": r"(\w+)\.InputFile\s*=\s*([^;]+);",
        "new": r"\1.BindPdf(\2);",
        "regex": True,
        "rule": {"description": "PdfFileStamp.InputFile is obsolete; use BindPdf()", "pattern": "fileStamp.BindPdf(inputFile)"},
    },
    {
        "pattern": r"(?s)error CS0618.*'PdfFileStamp\.OutputFile'.*obsolete",
        "old": r"(\w+)\.OutputFile\s*=\s*([^;]+);",
        "new": r"\1.Save(\2);",
        "regex": True,
        "rule": {"description": "PdfFileStamp.OutputFile is obsolete; use Save()", "pattern": "fileStamp.Save(outputFile)"},
    },
    {
        "pattern": r"(?s)error CS0618.*'PdfFileStamp\.PdfFileStamp\(string,\s*string\)'.*obsolete",
        "old": r"new\s+PdfFileStamp\(\s*([^,]+),\s*([^)]+)\)",
        "new": r"new PdfFileStamp()",
        "regex": True,
        "rule": {"description": "PdfFileStamp(string,string) is obsolete; use parameterless constructor + BindPdf + Save", "pattern": "new PdfFileStamp()"},
    },

    # ── LoadOptions class name fixes ──
    {
        "pattern": r"(?s)error CS0246.*'MarkdownLoadOptions'",
        "old": "MarkdownLoadOptions",
        "new": "MdLoadOptions",
        "regex": False,
        "rule": {"description": "MarkdownLoadOptions does not exist; use MdLoadOptions", "pattern": "new MdLoadOptions()"},
    },
    {
        "pattern": r"(?s)error CS0246.*'TexLoadOptions'",
        "old": "TexLoadOptions",
        "new": "TeXLoadOptions",
        "regex": False,
        "rule": {"description": "TexLoadOptions has wrong casing; use TeXLoadOptions", "pattern": "new TeXLoadOptions()"},
    },
    {
        "pattern": r"(?s)error CS0246.*'XsltLoadOptions'",
        "old": "XsltLoadOptions",
        "new": "XslFoLoadOptions",
        "regex": False,
        "rule": {"description": "XsltLoadOptions does not exist; use XslFoLoadOptions", "pattern": "new XslFoLoadOptions()"},
    },
    {
        "pattern": r"(?s)error CS0246.*'LatexLoadOptions'",
        "old": "LatexLoadOptions",
        "new": "TeXLoadOptions",
        "regex": False,
        "rule": {"description": "LatexLoadOptions does not exist; use TeXLoadOptions", "pattern": "new TeXLoadOptions()"},
    },
    {
        "pattern": r"(?s)error CS0246.*'FoLoadOptions'",
        "old": "FoLoadOptions",
        "new": "XslFoLoadOptions",
        "regex": False,
        "rule": {"description": "FoLoadOptions does not exist; use XslFoLoadOptions", "pattern": "new XslFoLoadOptions()"},
    },

    # ── DefaultAppearance: Aspose.Pdf.Color → System.Drawing.Color ──
    {
        "pattern": r"(?s)error CS1503.*cannot convert from 'Aspose\.Pdf\.Color' to 'System\.Drawing\.Color'",
        "old": r"new\s+DefaultAppearance\(([^,]+),\s*([^,]+),\s*Aspose\.Pdf\.Color\.(\w+)\)",
        "new": r"new DefaultAppearance(\1, \2, System.Drawing.Color.\3)",
        "regex": True,
        "rule": {"description": "DefaultAppearance constructor takes System.Drawing.Color, not Aspose.Pdf.Color", "pattern": "new DefaultAppearance(font, size, System.Drawing.Color.X)"},
    },

    # ── CheckBoxField → CheckboxField (lowercase b) ──
    {
        "pattern": r"(?s)error CS0246.*'CheckBoxField'",
        "old": "CheckBoxField",
        "new": "CheckboxField",
        "regex": False,
        "rule": {"description": "CheckBoxField has wrong casing; use CheckboxField (lowercase b)", "pattern": "CheckboxField"},
    },

    # ── JavaScriptAction → JavascriptAction (lowercase s) ──
    {
        "pattern": r"(?s)error CS0246.*'JavaScriptAction'",
        "old": "JavaScriptAction",
        "new": "JavascriptAction",
        "regex": False,
        "rule": {"description": "JavaScriptAction has wrong casing; use JavascriptAction (lowercase s)", "pattern": "JavascriptAction"},
    },

    # ── PasswordBoxField → TextBoxField ──
    {
        "pattern": r"(?s)error CS1729.*'PasswordBoxField'.*does not contain a constructor",
        "old": r"new\s+PasswordBoxField\(",
        "new": "new TextBoxField(",
        "regex": True,
        "rule": {"description": "PasswordBoxField has no public constructor; use TextBoxField", "pattern": "new TextBoxField(page, rect)"},
    },

    # ── DefaultAppearance CS0246 → add using Aspose.Pdf.Annotations ──
    {
        "pattern": r"(?s)error CS0246.*'DefaultAppearance'.*could not be found",
        "old": "using Aspose.Pdf.Forms;",
        "new": "using Aspose.Pdf.Forms;\nusing Aspose.Pdf.Annotations;",
        "regex": False,
        "rule": {"description": "DefaultAppearance is in Aspose.Pdf.Annotations namespace", "pattern": "using Aspose.Pdf.Annotations;"},
    },
]


def detect_and_fix_known_patterns(
    code: str, error_output: str, auto_patterns_path: str = ""
) -> Tuple[Optional[str], Optional[str]]:
    """Apply hardcoded regex fixes for known errors. Returns (fixed_code, rule_json) or (None, None).

    Also checks auto-learned patterns from auto_patterns.json (lower priority than curated).
    """
    # Try curated fixes first
    for fix in _KNOWN_FIXES:
        if re.search(fix["pattern"], error_output):
            if fix.get("regex"):
                fixed = re.sub(fix["old"], fix["new"], code)
            else:
                fixed = code.replace(fix["old"], fix["new"])
            if fixed != code:
                return fixed, json.dumps(fix["rule"], indent=2)

    # Then try auto-learned patterns
    if auto_patterns_path:
        try:
            from knowledge.pattern_tracker import load_auto_patterns
            for fix in load_auto_patterns(auto_patterns_path):
                pattern = fix.get("pattern", "")
                if pattern and re.search(pattern, error_output):
                    if fix.get("regex"):
                        fixed = re.sub(fix["old"], fix["new"], code)
                    else:
                        fixed = code.replace(fix["old"], fix["new"])
                    if fixed != code:
                        rule = fix.get("rule", {"description": "Auto-learned pattern fix"})
                        return fixed, json.dumps(rule, indent=2)
        except Exception:
            pass

    return None, None
