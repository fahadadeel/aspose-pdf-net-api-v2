"""
pipeline/prompt_builder.py — Build enhanced prompts for retry stages.
"""

from typing import List


def build_namespace_restriction(category: str, exclude_namespaces: list = None) -> str:
    """Return a prompt instruction forbidding excluded namespaces for non-facade categories.

    Mirrors the logic in mcp_client.py — facade categories are allowed to use
    Aspose.Pdf.Facades, all others must not.
    """
    cat_lower = (category or "").lower()
    if "facades" in cat_lower:
        return ""  # Facade categories are allowed
    ns_list = exclude_namespaces or ["Aspose.Pdf.Plugins", "Aspose.Pdf.Facades"]
    if not ns_list:
        return ""
    ns_str = ", ".join(ns_list)
    return (
        f"NAMESPACE RESTRICTION: Do NOT use the following namespaces: {ns_str}. "
        f"Do not add 'using {ns_list[0]};' or 'using {ns_list[-1]};'. "
        "Use only the core Aspose.Pdf.* APIs (e.g. Document, Page, TextFragment, Table, "
        "TextAbsorber) — not Facades wrappers like PdfFileEditor, FormEditor, PdfFileSecurity, "
        "PdfFileStamp, PdfFileMend."
    )


def build_retry_instruction(attempt: int, error_codes: List[str] = None) -> str:
    """Return attempt-specific coding constraint for retry prompt."""
    if attempt <= 1:
        return ""

    parts = []
    if error_codes:
        code_set = set(error_codes)
        if "CS0104" in code_set or "CS0234" in code_set:
            parts.append(
                "IMPORTANT: Use fully qualified Aspose.Pdf type names to avoid CS0104 "
                "ambiguity errors. Examples: Aspose.Pdf.Color (not Color), "
                "Aspose.Pdf.Rectangle (not Rectangle), Aspose.Pdf.Text.Font (not Font). "
                "Do NOT add 'using System.Drawing;'."
            )

    if attempt >= 3:
        parts.append(
            "CRITICAL: Every Aspose.Pdf type MUST use its full namespace prefix. "
            "Replace Color->Aspose.Pdf.Color, Rectangle->Aspose.Pdf.Rectangle, "
            "Font->Aspose.Pdf.Text.Font, Point->Aspose.Pdf.Point. "
            "Remove 'using System.Drawing;' and 'using Aspose.Pdf.Saving;'. "
            "Only use: 'using Aspose.Pdf;', 'using Aspose.Pdf.Text;', "
            "'using Aspose.Pdf.Tagged;', 'using Aspose.Pdf.LogicalStructure;' as needed."
        )
    elif attempt == 2 and not parts:
        parts.append(
            "IMPORTANT: Use fully qualified Aspose.Pdf type names to avoid CS0104 "
            "ambiguity errors. Do NOT add 'using System.Drawing;'."
        )

    return "\n\n".join(parts)


def format_rules_for_prompt(rules: List[dict]) -> str:
    """Format KB rules into structured prompt block."""
    if not rules:
        return ""
    parts = ["=== Relevant API Patterns (from knowledge base) ==="]
    for i, rule in enumerate(rules, 1):
        confidence = rule.get("confidence", 0.95)
        category = rule.get("category", "")
        header = f"\n[Pattern {i}] {rule.get('id', '')}"
        if category:
            header += f"  ({category})"
        if confidence >= 0.97:
            header += "  * high confidence"
        parts.append(header)
        parts.append(f"Summary: {rule.get('semantic_summary', '')}")
        api = rule.get("api_surface", [])
        if api:
            parts.append(f"Key APIs: {', '.join(api)}")
        warnings = rule.get("warnings", [])
        if warnings:
            parts.append("IMPORTANT NOTES:")
            for w in warnings:
                parts.append(f"  - {w}")
        patterns = rule.get("rules", [])
        if patterns:
            parts.append("Implementation:")
            for p in patterns:
                parts.append(f"  - {p}")
    return "\n".join(parts)


def build_enriched_prompt(
    task: str,
    error_summary: str,
    catalog_guidance: List[str] = None,
    error_fixes_text: str = "",
    retry_instruction: str = "",
    rules_text: str = "",
    chunks_text: str = "",
    decomposed_plan: str = "",
) -> str:
    """Build the full enhanced prompt for MCP regeneration."""
    parts = [task]

    if decomposed_plan:
        parts.append(f"\n\n{decomposed_plan}")

    parts.append(f"\n\nPrevious attempt had these errors:\n{error_summary}")

    if catalog_guidance:
        parts.append("\n\n=== KNOWN API FIXES (apply these first) ===\n" + "\n\n".join(catalog_guidance))

    if error_fixes_text:
        parts.append(f"\n\n{error_fixes_text}")

    if retry_instruction:
        parts.append(f"\n\n{retry_instruction}")

    if rules_text:
        parts.append(f"\n\n{rules_text}")

    if chunks_text:
        parts.append(f"\n\n{chunks_text}")

    parts.append("\n\nPlease generate corrected code that fixes the above errors.")
    return "".join(parts)
