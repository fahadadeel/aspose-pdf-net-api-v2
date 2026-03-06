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
]


def detect_and_fix_known_patterns(code: str, error_output: str) -> Tuple[Optional[str], Optional[str]]:
    """Apply hardcoded regex fixes for known errors. Returns (fixed_code, rule_json) or (None, None)."""
    for fix in _KNOWN_FIXES:
        if re.search(fix["pattern"], error_output):
            if fix.get("regex"):
                fixed = re.sub(fix["old"], fix["new"], code)
            else:
                fixed = code.replace(fix["old"], fix["new"])
            if fixed != code:
                return fixed, json.dumps(fix["rule"], indent=2)
    return None, None
