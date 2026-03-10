"""
git_ops/agents_content.py — Extract prescriptive content from resource files
for enhanced agents.md generation.

Reads error_catalog.json, error_fixes.json, and kb.json to produce
actionable sections: anti-patterns, domain knowledge, code conventions,
command reference, and category-specific tips.
"""

import json
import re
from pathlib import Path
from typing import Dict, List, Optional


def _load_json(path: str) -> any:
    """Safely load a JSON file, returning [] or {} on failure."""
    try:
        p = Path(path)
        if p.exists():
            return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        pass
    return []


def _extract_code_block(code: str, marker: str) -> List[str]:
    """Extract lines from a code string that start after `marker`."""
    lines = []
    capture = False
    for line in code.splitlines():
        stripped = line.strip()
        if marker in stripped:
            capture = True
            continue
        if capture:
            if stripped.startswith("//") and any(k in stripped.upper() for k in ["WRONG", "CORRECT", "OPTION"]):
                capture = False
                continue
            if stripped:
                lines.append(line)
    return lines


def _truncate_code(code: str, max_lines: int = 12) -> str:
    """Return first N non-empty lines of code."""
    lines = [l for l in code.splitlines() if l.strip()]
    if len(lines) > max_lines:
        return "\n".join(lines[:max_lines]) + "\n// ..."
    return "\n".join(lines)


def load_anti_patterns(
    error_catalog_path: str,
    error_fixes_path: str,
    max_count: int = 10,
) -> str:
    """Build a 'Common Mistakes' section from error_catalog + error_fixes.

    Returns markdown with wrong/right code pairs.
    """
    entries = []

    # --- From error_fixes.json (has code examples) ---
    fixes_data = _load_json(error_fixes_path)
    if isinstance(fixes_data, dict):
        for rule_id, fix in list(fixes_data.items()):
            code = fix.get("code", "")
            note = fix.get("note", "")
            if not code or "// WRONG" not in code:
                continue

            # Split into CORRECT and WRONG blocks
            correct_lines = []
            wrong_lines = []
            current_target = None
            for line in code.splitlines():
                stripped = line.strip()
                if "// CORRECT" in stripped:
                    current_target = correct_lines
                    continue
                elif "// WRONG" in stripped:
                    current_target = wrong_lines
                    continue
                if current_target is not None and stripped:
                    current_target.append(line)

            if not wrong_lines or not correct_lines:
                continue

            wrong_block = _truncate_code("\n".join(wrong_lines), 6)
            correct_block = _truncate_code("\n".join(correct_lines), 8)
            # Clean comment markers from code
            wrong_block = re.sub(r"^// ?", "", wrong_block, flags=re.MULTILINE)

            # Extract a short title from the rule_id
            title = rule_id.replace("-", " ").title()
            short_note = note[:200] if note else ""

            entries.append({
                "title": title,
                "note": short_note,
                "wrong": wrong_block,
                "correct": correct_block,
                "source": "error_fixes",
            })

    # --- From error_catalog.json (has fix_guidance) ---
    catalog_data = _load_json(error_catalog_path)
    if isinstance(catalog_data, list):
        for item in catalog_data:
            guidance = item.get("fix_guidance", "")
            error_code = item.get("error_code", "")
            if not guidance:
                continue

            # Extract title from first line
            first_line = guidance.split("\n")[0].strip()
            title = first_line.rstrip(":")

            entries.append({
                "title": f"{error_code}: {title}",
                "note": guidance.replace("\n", " ").strip()[:300],
                "wrong": "",
                "correct": "",
                "source": "error_catalog",
            })

    # Deduplicate — prefer entries with code examples
    seen_titles = set()
    unique = []
    for e in entries:
        key = e["title"].lower()[:40]
        if key not in seen_titles:
            seen_titles.add(key)
            unique.append(e)

    # Prioritize entries with code examples
    unique.sort(key=lambda x: (0 if x["wrong"] else 1))
    selected = unique[:max_count]

    if not selected:
        return ""

    md = "## Common Mistakes (Anti-Patterns)\n\n"
    md += "These are verified mistakes that cause build failures. **Never** use the wrong patterns.\n\n"

    for entry in selected:
        md += f"### {entry['title']}\n"
        if entry["note"]:
            md += f"{entry['note']}\n\n"
        if entry["wrong"]:
            md += "```csharp\n// WRONG\n"
            md += entry["wrong"] + "\n"
            md += "```\n\n"
        if entry["correct"]:
            md += "```csharp\n// CORRECT\n"
            md += entry["correct"] + "\n"
            md += "```\n\n"

    return md


def load_domain_knowledge(kb_path: str, max_count: int = 7) -> str:
    """Build a 'Domain Knowledge' section from kb.json cross-cutting rules.

    Picks high-confidence rules that apply broadly.
    """
    data = _load_json(kb_path)
    if not isinstance(data, list):
        return ""

    # Collect cross-cutting rules (appear in multiple categories or have high confidence)
    rule_map: Dict[str, dict] = {}  # rule_text -> {categories, confidence, warnings}

    for entry in data:
        rules = entry.get("rules", [])
        category = entry.get("category", "")
        confidence = entry.get("confidence", 0)
        warnings = entry.get("warnings", [])

        for rule in rules:
            rule_lower = rule.lower().strip()
            if len(rule_lower) < 20:
                continue
            if rule_lower not in rule_map:
                rule_map[rule_lower] = {
                    "text": rule,
                    "categories": set(),
                    "confidence": confidence,
                    "warnings": [],
                }
            rule_map[rule_lower]["categories"].add(category)
            rule_map[rule_lower]["confidence"] = max(rule_map[rule_lower]["confidence"], confidence)
            rule_map[rule_lower]["warnings"].extend(warnings)

    # Pick rules that appear in 2+ categories (cross-cutting)
    cross_cutting = [
        v for v in rule_map.values()
        if len(v["categories"]) >= 2 and v["confidence"] >= 0.9
    ]
    cross_cutting.sort(key=lambda x: (-len(x["categories"]), -x["confidence"]))

    selected = cross_cutting[:max_count]
    if not selected:
        return ""

    md = "## Domain Knowledge\n\n"
    md += "Cross-cutting rules that apply across multiple categories.\n\n"

    for item in selected:
        cats = ", ".join(sorted(item["categories"])[:3])
        if len(item["categories"]) > 3:
            cats += f" (+{len(item['categories']) - 3} more)"
        md += f"- **{item['text']}**\n"
        md += f"  _(Applies to: {cats})_\n"

    md += "\n"
    return md


_CATEGORY_STOP_WORDS = frozenset({
    "working", "with", "and", "the", "for", "from", "using",
    "pdf", "pdfs", "document", "documents", "aspose", "net",
})


def load_category_tips(kb_path: str, category_name: str, max_count: int = 5) -> str:
    """Build category-specific tips from kb.json for a particular category.

    Returns markdown with API surface info, rules, and warnings.

    Matching strategy:
    1. Exact match (case-insensitive, hyphen/space agnostic)
    2. Keyword fallback — split the category name into meaningful keywords
       (filtering stop-words like "working", "with", "pdf") and match KB
       categories that contain any keyword (min 3 chars).
       e.g. "working-with-xml" → keyword "xml" → matches "Working-With-XML-XSLT".

    Facades handling (mirrors pipeline/mcp_client.py):
    - If "facades" is in the category name → prefer Facades-namespace entries
    - If "facades" is NOT in the category name → exclude Facades-namespace entries
    """
    data = _load_json(kb_path)
    if not isinstance(data, list):
        return ""

    def _norm(s: str) -> str:
        return s.lower().replace("-", " ").replace("_", " ").strip()

    def _is_facades_entry(entry: dict) -> bool:
        """Check if a KB entry belongs to the Facades namespace.

        Checks category, namespace, AND api_surface — entries whose APIs
        are predominantly ``Aspose.Pdf.Facades.*`` are treated as Facades
        entries even when their KB category is something else (e.g. an
        entry filed under 'Text' that uses PdfContentEditor).
        """
        ns = entry.get("namespace", "").lower()
        cat = entry.get("category", "").lower()
        if "facades" in ns or "facades" in cat:
            return True
        # Check if majority of api_surface is Facades
        apis = entry.get("api_surface", [])
        if apis:
            facades_count = sum(1 for a in apis if "Facades" in a)
            if facades_count > len(apis) * 0.5:
                return True
        return False

    norm = _norm(category_name)
    is_facades_category = "facades" in category_name.lower()
    matches = []

    # Pass 1: exact match
    for entry in data:
        entry_cat = _norm(entry.get("category", ""))
        if entry_cat == norm:
            matches.append(entry)

    # Pass 2: keyword fallback if no exact match
    if not matches:
        keywords = [
            w for w in re.split(r"[\s\-_]+", category_name.lower())
            if len(w) >= 3 and w not in _CATEGORY_STOP_WORDS
        ]
        if keywords:
            for entry in data:
                entry_cat = _norm(entry.get("category", ""))
                if any(kw in entry_cat for kw in keywords):
                    matches.append(entry)

    if not matches:
        return ""

    # Facades-aware filtering (mirrors MCP generate/retrieve logic):
    # - Facades categories: keep Facades entries, exclude non-Facades duplicates
    # - Non-Facades categories: exclude Facades entries entirely
    if is_facades_category:
        # Prefer Facades entries; keep non-Facades only if they add unique info
        facades_matches = [e for e in matches if _is_facades_entry(e)]
        if facades_matches:
            matches = facades_matches
    else:
        # Exclude Facades entries to avoid polluting non-Facades categories
        filtered = [e for e in matches if not _is_facades_entry(e)]
        if filtered:
            matches = filtered

    # Sort by confidence
    matches.sort(key=lambda x: -x.get("confidence", 0))

    md = "## Category-Specific Tips\n\n"

    # Collect unique rules and warnings
    all_rules = []
    all_warnings = []
    all_apis = set()

    for entry in matches[:max_count * 2]:
        for rule in entry.get("rules", []):
            if rule not in all_rules:
                all_rules.append(rule)
        for warn in entry.get("warnings", []):
            if warn not in all_warnings:
                all_warnings.append(warn)
        for api in entry.get("api_surface", []):
            all_apis.add(api)

    if all_apis:
        md += "### Key API Surface\n"
        for api in sorted(all_apis)[:15]:
            md += f"- `{api}`\n"
        md += "\n"

    if all_rules:
        md += "### Rules\n"
        for rule in all_rules[:max_count]:
            md += f"- {rule}\n"
        md += "\n"

    if all_warnings:
        md += "### Warnings\n"
        for warn in all_warnings[:max_count]:
            md += f"- {warn}\n"
        md += "\n"

    return md


def build_command_reference(tfm: str = "net10.0", nuget_version: str = "26.2.0") -> str:
    """Build a 'Command Reference' section with dotnet build/run commands."""
    version_display = tfm.replace("net", "").replace(".0", ".0")
    return f"""## Command Reference

### Build and Run
```bash
# Create a new project (if needed)
dotnet new console -n ExampleProject --framework {tfm}

# Add Aspose.PDF NuGet package
dotnet add package Aspose.PDF --version {nuget_version}

# Build
dotnet build --configuration Release --verbosity minimal

# Run
dotnet run
```

### Project File (.csproj)
```xml
<Project Sdk="Microsoft.NET.Sdk">
  <PropertyGroup>
    <OutputType>Exe</OutputType>
    <TargetFramework>{tfm}</TargetFramework>
  </PropertyGroup>
  <ItemGroup>
    <PackageReference Include="Aspose.PDF" Version="{nuget_version}" />
  </ItemGroup>
</Project>
```

### Environment
- .NET SDK: {version_display} or higher
- NuGet: Aspose.PDF {nuget_version}
- All examples are standalone Console Applications
- Each `.cs` file can be compiled and run independently

"""


def build_enhanced_conventions() -> str:
    """Build an expanded 'Code Conventions' section with code examples."""
    return """## Code Conventions

### Explicit Types (No `var`)
Always use explicit type declarations. Never use `var`.

```csharp
// CORRECT
Document document = new Document("input.pdf");
Page page = document.Pages[1];
TextFragmentAbsorber absorber = new TextFragmentAbsorber("search");

// WRONG
// var document = new Document("input.pdf");
// var page = document.Pages[1];
```

### One-Based Indexing
Aspose.PDF uses 1-based indexing for Pages, Annotations, and EmbeddedFiles.

```csharp
// CORRECT — first page is index 1
Page firstPage = document.Pages[1];
Annotation firstAnnotation = page.Annotations[1];
FileSpecification firstFile = document.EmbeddedFiles[1];

// WRONG — index 0 throws IndexOutOfRangeException
// Page page = document.Pages[0];
```

### Fully Qualified Ambiguous Types
When using both `Aspose.Pdf` and `Aspose.Pdf.Drawing`, qualify ambiguous types.

```csharp
// CORRECT
Aspose.Pdf.Rectangle rect = new Aspose.Pdf.Rectangle(100, 200, 300, 400);
Aspose.Pdf.Drawing.Rectangle drawRect = new Aspose.Pdf.Drawing.Rectangle(50, 50, 200, 100);
Aspose.Pdf.Color pdfColor = Aspose.Pdf.Color.Blue;

// WRONG — ambiguous CS0104
// Rectangle rect = new Rectangle(100, 200, 300, 400);
// Color color = Color.Blue;
```

### Resource Cleanup
Always use `using` blocks or explicit `Dispose()` for IDisposable objects.

```csharp
// CORRECT
using (Document document = new Document("input.pdf"))
{
    // work with document
    document.Save("output.pdf");
}
```

### Save Pattern
Always save the document after modifications.

```csharp
Document document = new Document("input.pdf");
// ... make modifications ...
document.Save("output.pdf");
```

"""


# ---------------------------------------------------------------------------
# Code Intelligence — analyse actual .cs files for enriched agents.md
# ---------------------------------------------------------------------------

_RE_USING = re.compile(r"^\s*using\s+([\w.]+)\s*;", re.MULTILINE)

_UNIVERSAL_NAMESPACES = frozenset({
    "System", "System.IO", "System.Collections.Generic",
    "System.Linq", "System.Text", "System.Threading",
    "System.Threading.Tasks", "System.Collections",
})

_RE_LOAD_OPTIONS = re.compile(r"new\s+(\w+LoadOptions)\s*\(")
_RE_DOC_CTOR = re.compile(r"new\s+Document\s*\(([^)]*)\)")
_RE_SAVE = re.compile(r"\.\s*Save\s*\(\s*([^)]+)\)")
_RE_FACADES_CLASS = re.compile(
    r"new\s+(Form|PdfFileEditor|PdfContentEditor|PdfAnnotationEditor|"
    r"PdfFileSecurity|PdfFileSigner|PdfBookmarkEditor|PdfExtractor|"
    r"PdfFileMend|PdfFileStamp|PdfFileInfo|PdfConverter|PdfPageEditor)\s*\("
)
_RE_KEY_API = re.compile(
    r"new\s+((?:Aspose\.Pdf\.)?(?:\w+(?:Absorber|Editor|Stamp|Annotation|"
    r"LoadOptions|SaveOptions|Device|Converter|Fragment|Builder|"
    r"Optimizer|Collection|Action|Destination|Selector|Extractor|"
    r"Security|Signer|Info|Privilege)))\s*\("
)
_RE_ASPOSE_NEW = re.compile(r"new\s+((?:Aspose\.Pdf\.)[\w.]+)\s*\(")


def read_category_files(
    repo_path: str, category: str, filenames: List[str],
) -> Dict[str, str]:
    """Read .cs file contents from disk for a single category.

    Returns ``{filename: file_content_string}``.
    Returns empty dict if *repo_path* is unavailable or the folder is missing.
    """
    if not repo_path:
        return {}
    cat_dir = Path(repo_path) / category
    if not cat_dir.is_dir():
        return {}
    contents: Dict[str, str] = {}
    for fname in filenames:
        fp = cat_dir / fname
        try:
            contents[fname] = fp.read_text(encoding="utf-8")
        except Exception:
            pass
    return contents


def extract_required_namespaces(file_contents: Dict[str, str]) -> str:
    """Analyse ``using`` statements across all files and rank by frequency.

    Returns a markdown section like::

        ## Required Namespaces
        - ``using Aspose.Pdf;`` (16/16 files)
        - ``using Aspose.Pdf.Annotations;`` (14/16 files) ← category-specific
    """
    if not file_contents:
        return ""

    total = len(file_contents)
    counts: Dict[str, int] = {}

    for content in file_contents.values():
        seen_in_file: set = set()
        for m in _RE_USING.finditer(content):
            ns = m.group(1)
            if ns not in seen_in_file:
                seen_in_file.add(ns)
                counts[ns] = counts.get(ns, 0) + 1

    if not counts:
        return ""

    # Sort: Aspose namespaces first (most interesting), then by frequency
    def _sort_key(item):
        ns, cnt = item
        is_aspose = ns.startswith("Aspose")
        return (0 if is_aspose else 1, -cnt, ns)

    sorted_ns = sorted(counts.items(), key=_sort_key)

    md = "## Required Namespaces\n\n"
    for ns, cnt in sorted_ns:
        tag = ""
        if ns not in _UNIVERSAL_NAMESPACES and cnt >= total * 0.5:
            tag = " ← category-specific"
        md += f"- `using {ns};` ({cnt}/{total} files){tag}\n"
    md += "\n"
    return md


def extract_common_code_pattern(file_contents: Dict[str, str]) -> str:
    """Detect the dominant workflow pattern across files.

    Looks for LoadOptions, Document constructor style, Facades classes,
    and Save pattern. Returns a code skeleton or ``""`` if no clear pattern.
    """
    if not file_contents:
        return ""

    total = len(file_contents)

    # Collect pattern signals
    load_opts: Dict[str, int] = {}
    facades_cls: Dict[str, int] = {}
    has_doc_ctor = 0
    has_empty_ctor = 0
    has_save = 0
    has_using_block = 0

    for content in file_contents.values():
        for m in _RE_LOAD_OPTIONS.finditer(content):
            opt = m.group(1)
            load_opts[opt] = load_opts.get(opt, 0) + 1
        for m in _RE_FACADES_CLASS.finditer(content):
            cls = m.group(1)
            facades_cls[cls] = facades_cls.get(cls, 0) + 1
        doc_matches = _RE_DOC_CTOR.findall(content)
        if doc_matches:
            has_doc_ctor += 1
            if any(not args.strip() for args in doc_matches):
                has_empty_ctor += 1
        if _RE_SAVE.search(content):
            has_save += 1
        if "using (" in content or "using(" in content:
            has_using_block += 1

    # Determine dominant LoadOptions (if any used in >30% of files)
    dominant_opt = ""
    if load_opts:
        top_opt, top_cnt = max(load_opts.items(), key=lambda x: x[1])
        if top_cnt >= total * 0.3:
            dominant_opt = top_opt

    # Determine dominant Facades class
    dominant_facade = ""
    if facades_cls:
        top_f, top_fc = max(facades_cls.items(), key=lambda x: x[1])
        if top_fc >= total * 0.3:
            dominant_facade = top_f

    # Need at least some pattern to show
    if has_doc_ctor < total * 0.3 and not dominant_facade:
        return ""

    md = "## Common Code Pattern\n\n"

    if dominant_facade:
        # Facades-style pattern
        md += f"Most files in this category use `{dominant_facade}` from `Aspose.Pdf.Facades`:\n\n"
        md += "```csharp\n"
        md += f'{dominant_facade} tool = new {dominant_facade}();\n'
        md += 'tool.BindPdf("input.pdf");\n'
        md += f"// ... {dominant_facade} operations ...\n"
        md += 'tool.Save("output.pdf");\n'
        md += "```\n\n"
    elif dominant_opt:
        # LoadOptions pattern
        md += f"Most files in this category load documents with `{dominant_opt}`:\n\n"
        md += "```csharp\n"
        md += f"{dominant_opt} options = new {dominant_opt}();\n"
        md += 'using (Document doc = new Document("input.pdf", options))\n'
        md += "{\n"
        md += "    // ... operations ...\n"
        md += '    doc.Save("output.pdf");\n'
        md += "}\n"
        md += "```\n\n"
    else:
        # Standard Document pattern
        ctor_style = '("input.pdf")' if has_doc_ctor > has_empty_ctor else "()"
        save_line = '    doc.Save("output.pdf");\n' if has_save >= total * 0.3 else ""
        if has_using_block >= total * 0.4:
            md += "Most files follow this pattern:\n\n"
            md += "```csharp\n"
            md += f"using (Document doc = new Document{ctor_style})\n"
            md += "{\n"
            md += "    // ... operations ...\n"
            md += save_line
            md += "}\n"
            md += "```\n\n"
        else:
            md += "Most files follow this pattern:\n\n"
            md += "```csharp\n"
            md += f"Document doc = new Document{ctor_style};\n"
            md += "// ... operations ...\n"
            md += 'doc.Save("output.pdf");\n'
            md += "```\n\n"

    return md


def extract_file_summaries(
    file_contents: Dict[str, str], max_rows: int = 30,
) -> str:
    """Generate a compact per-file summary table.

    Returns a markdown table with file link, key APIs, and description.
    Replaces the plain file-list when code intelligence is available.
    """
    if not file_contents:
        return ""

    rows = []
    for fname in sorted(file_contents.keys()):
        content = file_contents[fname]
        display = fname.replace(".cs", "")

        # --- Extract key APIs ---
        apis: List[str] = []
        for m in _RE_KEY_API.finditer(content):
            cls = m.group(1).split(".")[-1]
            if cls not in apis:
                apis.append(cls)
        if not apis:
            for m in _RE_ASPOSE_NEW.finditer(content):
                cls = m.group(1).split(".")[-1]
                if cls not in apis and cls not in ("Document", "Page"):
                    apis.append(cls)
        if not apis:
            for m in _RE_FACADES_CLASS.finditer(content):
                cls = m.group(1)
                if cls not in apis:
                    apis.append(cls)
        api_str = ", ".join(f"`{a}`" for a in apis[:3]) if apis else ""

        # --- Description from filename ---
        desc = display.replace("-", " ")
        # Capitalize first letter, truncate
        if desc:
            desc = desc[0].upper() + desc[1:]
        if len(desc) > 80:
            desc = desc[:77] + "..."

        rows.append((display, fname, api_str, desc))

    if not rows:
        return ""

    md = "## Files in this folder\n\n"
    md += "| File | Key APIs | Description |\n"
    md += "|------|----------|-------------|\n"

    for display, fname, api_str, desc in rows[:max_rows]:
        # Truncate display name for table readability
        short_display = display[:60] + "..." if len(display) > 60 else display
        md += f"| [{short_display}](./{fname}) | {api_str} | {desc} |\n"

    if len(rows) > max_rows:
        md += f"| ... | | *and {len(rows) - max_rows} more files* |\n"

    md += "\n"
    return md


def build_code_intelligence_sections(
    repo_path: str, category: str, filenames: List[str],
) -> str:
    """Orchestrator: read files and build all code intelligence sections.

    Returns combined markdown (namespaces + pattern + file summaries),
    or ``""`` if *repo_path* is unavailable.
    """
    contents = read_category_files(repo_path, category, filenames)
    if not contents:
        return ""

    namespaces_section = extract_required_namespaces(contents)
    pattern_section = extract_common_code_pattern(contents)
    files_section = extract_file_summaries(contents)

    return namespaces_section + pattern_section + files_section
