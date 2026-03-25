#!/usr/bin/env python3
"""
scripts/populate_generation_rules.py

One-time script to auto-populate generation rules from MCP /retrieve.
For each category, sends representative tasks to MCP retrieve,
collects API chunks, deduplicates, and writes auto_generation_rules.json.

Usage:
    python scripts/populate_generation_rules.py
    python scripts/populate_generation_rules.py --categories "Basic Operations" "Pages"
    python scripts/populate_generation_rules.py --limit 30  # chunks per query
"""

import argparse
import json
import re
import sys
import time
from pathlib import Path
from collections import OrderedDict

import requests

# ── Configuration ──
MCP_RETRIEVE_URL = "http://172.20.1.175:7050/mcp/retrieve"
CATEGORIES_API_URL = "http://172.20.1.175:7001/api/categories?product=aspose.pdf"
RETRIEVE_LIMIT = 25
TIMEOUT = 60
OUTPUT_PATH = Path(__file__).resolve().parent.parent / "resources" / "auto_generation_rules.json"

# Representative tasks per category to pull diverse API surface
CATEGORY_TASKS = {
    "Basic Operations": [
        "Create a new PDF document and add a page with text",
        "Open an existing PDF and extract all text",
        "Merge two PDF files into one",
        "Split a PDF into individual pages",
        "Get PDF document properties like page count and metadata",
        "Set PDF metadata title, author, subject",
        "Compress and optimize a PDF to reduce file size",
        "Rotate pages in a PDF document",
        "Delete specific pages from a PDF",
        "Copy pages from one PDF to another",
    ],
    "Conversion": [
        "Convert PDF to Word DOCX format",
        "Convert PDF to HTML",
        "Convert PDF to image PNG/JPEG",
        "Convert HTML to PDF",
        "Convert PDF to Excel XLSX",
        "Convert PDF to PDF/A format for archiving",
        "Convert Word DOCX to PDF",
        "Convert PDF to SVG",
        "Convert Markdown to PDF",
        "Convert PDF to EPUB",
    ],
    "Working With Text": [
        "Add text to a PDF page with specific font and size",
        "Search and replace text in a PDF",
        "Extract text from specific pages",
        "Add text with formatting bold italic underline",
        "Use TextFragmentAbsorber to find text",
        "Add multiline text with TextParagraph",
        "Set text alignment and line spacing",
        "Add superscript and subscript text",
        "Use custom fonts in PDF text",
        "Add text watermark to PDF pages",
    ],
    "Working With Images": [
        "Add an image to a PDF page",
        "Extract images from a PDF document",
        "Replace an image in a PDF",
        "Resize images in a PDF",
        "Convert PDF pages to images",
        "Add image stamp to PDF",
        "Set image as page background",
        "Delete images from a PDF page",
        "Get image properties from PDF",
        "Add SVG image to PDF",
    ],
    "Working with Tables": [
        "Create a table in a PDF with rows and columns",
        "Add table with borders and styling",
        "Extract tables from a PDF page",
        "Set table column widths and row heights",
        "Add table with merged cells",
        "Style table with alternating row colors",
        "Add table that spans multiple pages",
        "Add nested table inside a cell",
        "Set table alignment on page",
        "Remove a table from PDF page",
    ],
    "Working with Forms": [
        "Add text field to a PDF form",
        "Add checkbox field to a PDF form",
        "Fill form fields programmatically",
        "Extract form field values from PDF",
        "Add dropdown/combo box to PDF form",
        "Add radio button group to PDF form",
        "Flatten form fields in a PDF",
        "Set form field properties like readonly",
        "Add submit button to PDF form",
        "Delete form fields from PDF",
    ],
    "Working with Annotations": [
        "Add text annotation to a PDF page",
        "Add highlight annotation to text",
        "Extract annotations from PDF",
        "Delete annotations from a page",
        "Add link annotation to PDF",
        "Add stamp annotation",
        "Add free text annotation with formatting",
        "Add line annotation",
        "Modify existing annotation properties",
        "Add popup annotation",
    ],
    "Working with Attachments": [
        "Add file attachment to a PDF",
        "Extract attachments from PDF",
        "Delete an attachment from PDF",
        "Get attachment properties",
        "Add embedded file with description",
    ],
    "Working with Graphs": [
        "Draw a rectangle on a PDF page",
        "Draw a circle on a PDF page",
        "Draw a line on a PDF page",
        "Create filled shapes with colors",
        "Draw an arc on a PDF page",
        "Add graph with transparency",
        "Draw ellipse shape",
        "Create dashed line pattern",
    ],
    "Pages": [
        "Add a new blank page to PDF",
        "Get page dimensions width and height",
        "Set page size like A4 Letter",
        "Add page numbers to PDF",
        "Set page margins",
        "Insert page at specific position",
        "Get total page count",
        "Set page orientation landscape portrait",
    ],
    "Stamping": [
        "Add text stamp to PDF pages",
        "Add image stamp to PDF pages",
        "Add page number stamp",
        "Add header and footer to PDF",
        "Add watermark stamp to all pages",
        "Set stamp opacity and rotation",
    ],
    "Securing and signing PDF": [
        "Encrypt PDF with password",
        "Decrypt a password protected PDF",
        "Set PDF permissions restrict printing",
        "Digitally sign a PDF document",
        "Add timestamp to digital signature",
        "Remove password from PDF",
    ],
    "Accessibility and Tagged PDFs": [
        "Create tagged PDF with structure elements",
        "Add heading elements to tagged PDF",
        "Add paragraph elements to tagged PDF",
        "Add table to tagged PDF with proper structure",
        "Add image with alt text to tagged PDF",
        "Set document language for tagged PDF",
        "Create table of contents in tagged PDF",
        "Add list elements to tagged PDF",
    ],
    "Working with XML": [
        "Create PDF from XML template",
        "Bind XML data to PDF form",
        "Extract XML from PDF form",
    ],
    "JavaScript": [
        "Add JavaScript action to PDF document",
        "Add JavaScript to form field",
        "Remove JavaScript from PDF",
    ],
    "Parse PDF": [
        "Parse PDF and extract structured text",
        "Extract text with position information",
        "Parse PDF tables into structured data",
    ],
    "Compare PDF": [
        "Compare two PDF documents for differences",
        "Highlight differences between PDFs",
    ],
    "Document": [
        "Get PDF document information",
        "Set PDF viewer preferences",
        "Add bookmarks to PDF",
        "Add table of contents to PDF",
        "Set PDF open action",
        "Validate PDF against PDF/A standard",
    ],
    "Operators": [
        "Use PDF operators to draw graphics",
        "Use content stream operators",
        "Add graphics state operators",
    ],
    "Graphs - ZUGFeRD - Operators": [
        "Create ZUGFeRD compliant invoice PDF",
        "Add structured invoice data to PDF",
        "Validate ZUGFeRD PDF compliance",
    ],
}

# Generic tasks for Facades categories
FACADES_TASKS = {
    "Facades - AcroForms": [
        "Fill AcroForm fields using FormEditor",
        "Export form data to FDF/XFDF",
        "Import form data from FDF/XFDF",
        "Flatten form using FormEditor",
    ],
    "Facades - Annotations": [
        "Add annotation using PdfAnnotationEditor",
        "Extract annotations using PdfAnnotationEditor",
        "Delete annotations using PdfAnnotationEditor",
        "Modify annotation using PdfAnnotationEditor",
    ],
    "Facades - Bookmarks": [
        "Add bookmarks using PdfBookmarkEditor",
        "Extract bookmarks using PdfBookmarkEditor",
        "Delete bookmarks using PdfBookmarkEditor",
    ],
    "Facades - Convert Documents": [
        "Convert PDF using PdfConverter",
        "Convert PDF pages to images using PdfConverter",
    ],
    "Facades - Documents": [
        "Concatenate PDFs using PdfFileEditor",
        "Split PDF using PdfFileEditor",
        "Append pages using PdfFileEditor",
    ],
    "Facades - Edit Document": [
        "Edit PDF using PdfContentEditor",
        "Add text using PdfContentEditor",
        "Replace text using PdfContentEditor",
    ],
    "Facades - Extract Images and Text": [
        "Extract images using PdfExtractor",
        "Extract text using PdfExtractor",
    ],
    "Facades - Fill Forms": [
        "Fill form using Form facade",
        "Submit form data using Form facade",
    ],
    "Facades - Forms": [
        "Create form fields using FormEditor",
        "Delete form fields using FormEditor",
        "Modify form field using FormEditor",
    ],
    "Facades - Metadata": [
        "Get PDF metadata using PdfFileInfo",
        "Set PDF metadata using PdfFileInfo",
    ],
    "Facades - Pages": [
        "Manipulate pages using PdfPageEditor",
        "Set page size using PdfPageEditor",
        "Rotate page using PdfPageEditor",
    ],
    "Facades - Secure Documents": [
        "Encrypt PDF using PdfFileSecurity",
        "Decrypt PDF using PdfFileSecurity",
        "Set PDF permissions using PdfFileSecurity",
    ],
    "Facades - Sign Documents": [
        "Sign PDF using PdfFileSignature",
        "Verify signature using PdfFileSignature",
    ],
    "Facades - Stamps": [
        "Add text stamp using PdfFileStamp",
        "Add image stamp using PdfFileStamp",
        "Add page number using PdfFileStamp",
    ],
    "Facades - Texts and Images": [
        "Replace text using PdfContentEditor",
        "Add image using PdfContentEditor",
    ],
}

# Merge all tasks
ALL_TASKS = {**CATEGORY_TASKS, **FACADES_TASKS}


def fetch_categories() -> list:
    """Fetch category list from API."""
    try:
        resp = requests.get(CATEGORIES_API_URL, timeout=15)
        if resp.status_code == 200:
            return [c["name"] for c in resp.json()]
    except Exception:
        pass
    return list(ALL_TASKS.keys())


def retrieve_chunks(task: str, category: str = "", limit: int = RETRIEVE_LIMIT) -> list:
    """Call MCP /retrieve for a task."""
    is_facades = "Facades" in category
    payload = {
        "task": task,
        "product": "pdf",
        "platform": "net",
        "retrieval_mode": "embedding",
        "limit": limit,
        "exclude_namespaces": ["Aspose.Pdf.Plugins"] if is_facades else ["Aspose.Pdf.Plugins", "Aspose.Pdf.Facades"],
    }
    try:
        resp = requests.post(MCP_RETRIEVE_URL, json=payload, timeout=TIMEOUT)
        if resp.status_code == 200:
            return resp.json().get("chunks", [])
    except Exception as e:
        print(f"  ⚠ Retrieve failed: {e}")
    return []


def chunk_to_rule_key(chunk: dict) -> str:
    """Generate a unique rule key from a chunk."""
    ns = chunk.get("namespace", "").replace(".", "-").lower()
    type_name = chunk.get("type_name", "unknown").lower()
    member = (chunk.get("member_name") or chunk.get("member_kind") or "").lower()
    member = re.sub(r"[^a-z0-9]+", "-", member).strip("-")

    key = f"{type_name}-{member}" if member else type_name
    if ns:
        key = f"{ns}-{key}"
    # Clean up
    key = re.sub(r"-+", "-", key).strip("-")
    return key[:80]


def chunk_to_rule(chunk: dict, category: str) -> dict:
    """Convert a retrieve chunk into a generation rule entry."""
    text = chunk.get("text", "").strip()
    ns = chunk.get("namespace", "")
    type_name = chunk.get("type_name", "")
    member_kind = chunk.get("member_kind", "")
    member_name = chunk.get("member_name", "")

    # Build a note from the chunk metadata
    parts = []
    if type_name:
        parts.append(f"{ns}.{type_name}" if ns else type_name)
    if member_name and member_kind:
        parts.append(f"{member_kind}: {member_name}")
    elif member_kind:
        parts.append(member_kind)

    note = " — ".join(parts) if parts else "API documentation chunk"

    rule = {
        "note": note,
        "code": text[:2000] if text else "",
        "category": category,
        "namespace": ns,
        "type": type_name,
    }
    if member_name:
        rule["member"] = member_name

    return rule


def deduplicate_rules(rules: dict) -> dict:
    """Remove near-duplicate rules by checking code similarity."""
    seen_codes = set()
    deduped = OrderedDict()

    for key, rule in rules.items():
        code = rule.get("code", "").strip()
        # Normalize whitespace for comparison
        normalized = re.sub(r"\s+", " ", code)[:200]
        if normalized in seen_codes:
            continue
        seen_codes.add(normalized)
        deduped[key] = rule

    return deduped


def main():
    parser = argparse.ArgumentParser(description="Auto-populate generation rules from MCP /retrieve")
    parser.add_argument("--categories", nargs="+", help="Specific categories to process")
    parser.add_argument("--limit", type=int, default=RETRIEVE_LIMIT, help="Chunks per retrieve call")
    parser.add_argument("--output", type=str, default=str(OUTPUT_PATH), help="Output file path")
    parser.add_argument("--delay", type=float, default=1.0, help="Delay between API calls (seconds)")
    args = parser.parse_args()

    # Determine categories
    if args.categories:
        categories = args.categories
    else:
        categories = fetch_categories()

    print(f"Processing {len(categories)} categories...")
    print(f"Output: {args.output}\n")

    all_rules = OrderedDict()
    stats = {"categories": 0, "tasks": 0, "chunks": 0, "rules": 0}

    for cat in categories:
        tasks = ALL_TASKS.get(cat, [])
        if not tasks:
            # Generate generic tasks for unknown categories
            tasks = [
                f"How to use {cat} features in Aspose.PDF",
                f"Common operations for {cat}",
            ]

        print(f"── {cat} ({len(tasks)} tasks) ──")
        cat_rules = OrderedDict()
        stats["categories"] += 1

        for task in tasks:
            print(f"  → {task[:60]}...", end=" ", flush=True)
            chunks = retrieve_chunks(task, category=cat, limit=args.limit)
            stats["tasks"] += 1
            stats["chunks"] += len(chunks)

            for chunk in chunks:
                key = chunk_to_rule_key(chunk)
                if key and key not in all_rules and key not in cat_rules:
                    rule = chunk_to_rule(chunk, cat)
                    if rule["code"]:  # Only keep rules with actual content
                        cat_rules[key] = rule

            print(f"({len(chunks)} chunks)")
            time.sleep(args.delay)

        # Add category section comment
        if cat_rules:
            section_key = f"__section_{cat.lower().replace(' ', '_')}__"
            all_rules[section_key] = f"=== {cat} ==="
            all_rules.update(cat_rules)
            print(f"  ✓ {len(cat_rules)} unique rules\n")
        else:
            print(f"  ✗ No rules generated\n")

    # Deduplicate across categories
    print("Deduplicating...")
    # Separate section comments from rules for dedup
    sections = {k: v for k, v in all_rules.items() if k.startswith("__section")}
    rule_entries = {k: v for k, v in all_rules.items() if not k.startswith("__section")}
    deduped = deduplicate_rules(rule_entries)

    # Rebuild with sections
    final_rules = OrderedDict()
    current_section_cats = set()
    for key, value in all_rules.items():
        if key.startswith("__section"):
            final_rules[key] = value
        elif key in deduped:
            final_rules[key] = deduped[key]

    stats["rules"] = len([k for k in final_rules if not k.startswith("__section")])

    # Write output
    output = {
        "product": "Aspose.Pdf",
        "language": "csharp",
        "version": "26.2.0",
        "_generated": True,
        "_note": "Auto-generated from MCP /retrieve. Review and merge into generation_rules.json.",
        "rules": final_rules,
    }

    output_path = Path(args.output)
    output_path.write_text(json.dumps(output, indent=2, ensure_ascii=False), encoding="utf-8")

    print(f"\n{'='*50}")
    print(f"Categories processed: {stats['categories']}")
    print(f"Tasks queried:        {stats['tasks']}")
    print(f"Total chunks:         {stats['chunks']}")
    print(f"Unique rules:         {stats['rules']}")
    print(f"Output:               {output_path}")
    print(f"{'='*50}")


if __name__ == "__main__":
    main()
