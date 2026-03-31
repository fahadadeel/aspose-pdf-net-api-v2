"""
git_ops/agents_content.py — Extract prescriptive content from resource files
for enhanced agents.md generation.

Reads error_catalog.json, error_fixes.json, and kb.json to produce
actionable sections: anti-patterns, domain knowledge, code conventions,
command reference, category-specific tips, and GitHub-recommended
sections (frontmatter, persona, boundaries, testing guide).
"""

import json
import re
from pathlib import Path
from typing import Dict, List, Optional


# ---------------------------------------------------------------------------
# GitHub Best-Practices: frontmatter, persona, boundaries, testing guide
# ---------------------------------------------------------------------------

def build_frontmatter(
    tfm: str = "net10.0",
    nuget_version: str = "26.2.0",
    is_category: bool = False,
    category_name: str = "",
) -> str:
    """Return YAML frontmatter block for agents.md."""
    if is_category:
        return f"""---
name: {category_name}
description: C# examples for {category_name} using Aspose.PDF for .NET
language: csharp
framework: {tfm}
parent: ../agents.md
---

"""
    return f"""---
name: aspose-pdf-examples
description: AI-friendly C# code examples for Aspose.PDF for .NET
language: csharp
framework: {tfm}
package: Aspose.PDF {nuget_version}
---

"""


def build_persona(
    is_category: bool = False,
    category_name: str = "",
) -> str:
    """Return persona section defining the agent's role."""
    if is_category:
        return f"""## Persona

You are a C# developer specializing in PDF processing using Aspose.PDF for .NET,
working within the **{category_name}** category.
This folder contains standalone C# examples for {category_name} operations.
See the root [agents.md](../agents.md) for repository-wide conventions and boundaries.

"""
    return """## Persona

You are a C# developer specializing in PDF processing using Aspose.PDF for .NET.
When working in this repository:
- Each `.cs` file is a **standalone Console Application** — do not create multi-file projects
- All examples must **compile and run** without errors using `dotnet build` and `dotnet run`
- Follow the conventions, boundaries, and anti-patterns documented below exactly
- Use the **Command Reference** section for build/run commands

"""


def build_boundaries() -> str:
    """Return structured boundaries section (Always / Ask First / Never).

    Replaces ``build_enhanced_conventions()`` in templates — merges the same
    code examples into GitHub's recommended three-tier boundary framework.
    """
    return """## Boundaries

### ✅ Always

These rules are mandatory for every example.

#### Use explicit types — never use `var`
```csharp
// CORRECT
Document document = new Document("input.pdf");
Page page = document.Pages[1];
TextFragmentAbsorber absorber = new TextFragmentAbsorber("search");

// WRONG
// var document = new Document("input.pdf");
// var page = document.Pages[1];
```

#### Use 1-based indexing for Pages, Annotations, EmbeddedFiles
```csharp
// CORRECT — first page is index 1
Page firstPage = document.Pages[1];
Annotation firstAnnotation = page.Annotations[1];
FileSpecification firstFile = document.EmbeddedFiles[1];

// WRONG — index 0 throws IndexOutOfRangeException
// Page page = document.Pages[0];
```

#### Fully qualify ambiguous types (Rectangle, Color, Path, Image, Point, Matrix)
```csharp
// CORRECT
Aspose.Pdf.Rectangle rect = new Aspose.Pdf.Rectangle(100, 200, 300, 400);
Aspose.Pdf.Drawing.Rectangle drawRect = new Aspose.Pdf.Drawing.Rectangle(50, 50, 200, 100);
Aspose.Pdf.Color pdfColor = Aspose.Pdf.Color.Blue;

// WRONG — ambiguous CS0104
// Rectangle rect = new Rectangle(100, 200, 300, 400);
// Color color = Color.Blue;
```

#### Use `using` blocks for IDisposable objects
```csharp
// CORRECT
using (Document document = new Document("input.pdf"))
{
    // work with document
    document.Save("output.pdf");
}
```

#### Save the document after all modifications
```csharp
Document document = new Document("input.pdf");
// ... make modifications ...
document.Save("output.pdf");
```

### ⚠️ Ask First

Check with a human before doing any of these:
- **Creating multi-file projects** — each example must be a single `.cs` file
- **Using deprecated APIs** — check the Aspose.PDF changelog for the current API surface
- **Adding NuGet packages** beyond `Aspose.PDF` — the `.csproj` template only includes Aspose.PDF
- **Modifying shared infrastructure** — `.csproj` templates, `agents.md` files, CI configs

### 🚫 Never

See the full **Common Mistakes** section below for code-level prohibitions with examples.
- Never use `var` for variable declarations
- Never use 0-based indexing for `Pages`, `Annotations`, or `EmbeddedFiles`
- Never use unqualified type names for `Rectangle`, `Color`, `Path`, `Image`, `Matrix`, `Point`
- Never use `Aspose.Pdf.Saving` namespace (it does not exist)
- Never mix `Aspose.Pdf.LogicalStructure` and `Aspose.Pdf.Structure` namespaces
- Never modify `agents.md` files — they are auto-generated
- Never modify the `.csproj` template — it is generated

"""


def build_testing_guide(tfm: str = "net10.0") -> str:
    """Return testing instructions section."""
    return """## Testing Guide

Every example must pass these verification steps.

### Build Verification
```bash
dotnet build --configuration Release --verbosity minimal
```
- **Success**: Exit code 0, no `CS` error codes in output
- **Failure**: Any `error CS####` line indicates a build failure

### Run Verification
```bash
dotnet run
```
- **Success**: Exit code 0, no unhandled exception stack traces
- **Failure**: `Unhandled exception`, `System.Exception`, or non-zero exit code

### Expected Output Patterns
- Console output confirming the operation (e.g., "PDF saved successfully")
- Output files created in the working directory (e.g., `output.pdf`)
- No `NullReferenceException`, `IndexOutOfRangeException`, or `FileNotFoundException`

### Common Error Codes
| Code | Meaning | Fix |
|------|---------|-----|
| `CS0104` | Ambiguous type reference | Use fully qualified name (`Aspose.Pdf.Rectangle`) |
| `CS1061` | Member does not exist on type | Check API docs for correct property/method |
| `CS0246` | Type or namespace not found | Add missing `using` directive |
| `CS0029` | Cannot convert type | Cast explicitly or use correct type |

"""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

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


_GENERIC_RULE_PATTERNS = [
    re.compile(r"save.*\{?(doc|document)\}?.*\{?(output|file)", re.IGNORECASE),
    re.compile(r"persist.*calling.*save", re.IGNORECASE),
    re.compile(r"persist.*pdf.*calling", re.IGNORECASE),
    re.compile(r"^load a pdf", re.IGNORECASE),
    re.compile(r"^load.*\{?doc\}?.*using.*new document", re.IGNORECASE),
    re.compile(r"^save the modified", re.IGNORECASE),
    re.compile(r"^create.*new.*document\(\)", re.IGNORECASE),
]

_GENERIC_WORDS = frozenset({
    "document", "modified", "changes", "output", "input",
    "file", "path", "save", "load", "persist", "call",
    "invoke", "create", "open", "close", "the", "pdf",
})


def _is_generic_rule(text: str) -> bool:
    """Return True if a rule is a trivial save/load/persist variation."""
    lower = text.lower()
    for pattern in _GENERIC_RULE_PATTERNS:
        if pattern.search(lower):
            return True
    words = [w for w in re.findall(r"[a-z]+", lower) if len(w) > 3]
    if not words:
        return True
    generic_count = sum(1 for w in words if w in _GENERIC_WORDS)
    return generic_count / len(words) > 0.6


def _is_semantic_duplicate(text: str, existing: List[str], threshold: float = 0.7) -> bool:
    """Check if text is too similar to any existing rule."""
    tokens_new = set(re.findall(r"[a-z]+", text.lower()))
    for ex in existing:
        tokens_ex = set(re.findall(r"[a-z]+", ex.lower()))
        if not tokens_new or not tokens_ex:
            continue
        overlap = len(tokens_new & tokens_ex) / min(len(tokens_new), len(tokens_ex))
        if overlap > threshold:
            return True
    return False


def load_domain_knowledge(kb_path: str, max_count: int = 7) -> str:
    """Build a 'Domain Knowledge' section from kb.json.

    Picks high-confidence, non-generic rules. Filters out trivial
    save/load variations and deduplicates semantically similar rules.
    Falls back to high-confidence single-category rules with warnings
    (indicating gotchas) if not enough cross-cutting rules survive.
    """
    # Legacy KB categories that don't map to any real repo category.
    # Rules filed under these should not appear in agents.md output.
    _EXCLUDED_CATEGORIES = frozenset({
        "TechnicalArticles", "App_Start", "Examples.Web",
        "QuickStart", "Miscellaneous",
    })

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

        # Skip legacy categories that don't exist in the repo
        if category in _EXCLUDED_CATEGORIES:
            continue

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

    # Cross-cutting non-generic rules (2+ categories)
    candidates = [
        v for v in rule_map.values()
        if len(v["categories"]) >= 2
        and v["confidence"] >= 0.9
        and not _is_generic_rule(v["text"])
    ]

    # Fallback: high-confidence single-category rules with warnings (gotchas)
    if len(candidates) < max_count:
        gotchas = [
            v for v in rule_map.values()
            if v["confidence"] >= 0.95
            and v["warnings"]
            and not _is_generic_rule(v["text"])
        ]
        gotchas.sort(key=lambda x: (-len(x["warnings"]), -x["confidence"]))
        candidates.extend(gotchas)

    # Sort: cross-cutting first, then by warnings count, then confidence
    candidates.sort(key=lambda x: (
        -len(x["categories"]),
        -len(x.get("warnings", [])),
        -x["confidence"],
    ))

    # Deduplicate semantically
    selected = []
    selected_texts: List[str] = []
    for item in candidates:
        if len(selected) >= max_count:
            break
        if not _is_semantic_duplicate(item["text"], selected_texts):
            selected.append(item)
            selected_texts.append(item["text"])

    if not selected:
        return ""

    md = "## Domain Knowledge\n\n"
    md += "Cross-cutting rules and API-specific gotchas.\n\n"

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
    # Use ALL meaningful keywords and require the entry to match ALL of them
    # (not just any one). This prevents "Facades - Metadata" from matching
    # "Facades - Fill Forms" just because both share the "facades" keyword.
    if not matches:
        keywords = [
            w for w in re.split(r"[\s\-_]+", category_name.lower())
            if len(w) >= 3 and w not in _CATEGORY_STOP_WORDS
        ]
        if keywords:
            for entry in data:
                entry_cat = _norm(entry.get("category", ""))
                # Require ALL keywords to match (AND logic instead of OR)
                if all(kw in entry_cat for kw in keywords):
                    matches.append(entry)

    # Pass 3: single-keyword fallback (OR logic) but only if no multi-keyword match
    if not matches:
        keywords = [
            w for w in re.split(r"[\s\-_]+", category_name.lower())
            if len(w) >= 4 and w not in _CATEGORY_STOP_WORDS and w != "facades"
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

    The category display name (e.g. "Facades - Metadata") is normalised to
    its folder slug (e.g. "facades-metadata") before the path is built, so
    this works regardless of how the caller spells the category.
    """
    if not repo_path:
        return {}

    import re as _re

    def _to_slug(name: str) -> str:
        s = name.strip().lower()
        s = _re.sub(r"[^a-z0-9]+", "-", s)
        return _re.sub(r"-+", "-", s).strip("-")

    root = Path(repo_path)
    # Try slug first, then original name as fallback
    slug = _to_slug(category)
    cat_dir = root / slug
    if not cat_dir.is_dir():
        cat_dir = root / category
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
    index_metadata: dict = None,
) -> str:
    """Generate a compact per-file summary table.

    Returns a markdown table with file link, key APIs, and description.
    Replaces the plain file-list when code intelligence is available.

    index_metadata: optional dict from per-category index.json
        {filename_stem: {title, description, tags, apis_used, difficulty}}
    """
    if not file_contents:
        return ""

    examples_meta = (index_metadata or {}).get("examples", {})

    rows = []
    for fname in sorted(file_contents.keys()):
        content = file_contents[fname]
        stem = fname.replace(".cs", "")
        display = stem
        meta_entry = examples_meta.get(stem, {})

        # --- Title: prefer LLM-provided, fall back to humanised filename ---
        title = meta_entry.get("title", "").strip()
        if not title:
            title = display.replace("-", " ")
            if title:
                title = title[0].upper() + title[1:]

        # --- Key APIs: prefer LLM-provided apis_used, fall back to regex ---
        llm_apis = meta_entry.get("apis_used", [])
        if llm_apis:
            apis = [a.split(".")[-1] for a in llm_apis[:3]]
        else:
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

        # --- Description: prefer LLM-provided, fall back to humanised title ---
        desc = meta_entry.get("description", "").strip() or title
        if len(desc) > 100:
            desc = desc[:97] + "..."

        rows.append((display, fname, api_str, desc, title))

    if not rows:
        return ""

    md = "## Files in this folder\n\n"
    md += "| File | Title | Key APIs | Description |\n"
    md += "|------|-------|----------|-------------|\n"

    for display, fname, api_str, desc, title in rows[:max_rows]:
        short_display = display[:50] + "..." if len(display) > 50 else display
        short_title = title[:60] + "..." if len(title) > 60 else title
        md += f"| [{short_display}](./{fname}) | {short_title} | {api_str} | {desc} |\n"

    if len(rows) > max_rows:
        md += f"| ... | | | *and {len(rows) - max_rows} more files* |\n"

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

    # Load per-category index.json for LLM-generated titles/descriptions
    index_metadata = _load_category_index_for_agents(repo_path, category)

    namespaces_section = extract_required_namespaces(contents)
    pattern_section = extract_common_code_pattern(contents)
    files_section = extract_file_summaries(contents, index_metadata=index_metadata)

    return namespaces_section + pattern_section + files_section


def _load_category_index_for_agents(repo_path: str, category: str) -> dict:
    """Load per-category index.json from the target repo for agents.md enrichment."""
    import json as _json
    import re as _re
    root = Path(repo_path)
    norm = _re.sub(r"\s+", "-", category.strip()).lower()
    norm = _re.sub(r"[^a-z0-9-]", "-", norm)
    norm = _re.sub(r"-+", "-", norm).strip("-")
    for folder in [norm, category]:
        idx = root / folder / "index.json"
        if idx.exists():
            try:
                return _json.loads(idx.read_text(encoding="utf-8"))
            except Exception:
                pass
    return {}


def extract_category_metadata(
    repo_path: str, category: str, filenames: List[str],
) -> dict:
    """Extract structured metadata for a category (for index.json).

    Returns a dict with ``required_namespaces`` and ``key_apis`` lists,
    or empty lists if *repo_path* is unavailable.
    """
    contents = read_category_files(repo_path, category, filenames)
    if not contents:
        return {"required_namespaces": [], "key_apis": []}

    # --- Namespaces (Aspose-specific only, sorted by frequency) ---
    ns_counts: Dict[str, int] = {}
    for content in contents.values():
        seen: set = set()
        for m in _RE_USING.finditer(content):
            ns = m.group(1)
            if ns not in seen:
                seen.add(ns)
                ns_counts[ns] = ns_counts.get(ns, 0) + 1

    aspose_ns = sorted(
        [(ns, cnt) for ns, cnt in ns_counts.items() if ns.startswith("Aspose")],
        key=lambda x: (-x[1], x[0]),
    )
    required_namespaces = [ns for ns, _ in aspose_ns]

    # --- Key APIs (deduplicated, sorted by frequency) ---
    api_counts: Dict[str, int] = {}
    for content in contents.values():
        seen_apis: set = set()
        for m in _RE_KEY_API.finditer(content):
            cls = m.group(1).split(".")[-1]
            if cls not in seen_apis:
                seen_apis.add(cls)
                api_counts[cls] = api_counts.get(cls, 0) + 1
        if not seen_apis:
            for m in _RE_FACADES_CLASS.finditer(content):
                cls = m.group(1)
                if cls not in seen_apis:
                    seen_apis.add(cls)
                    api_counts[cls] = api_counts.get(cls, 0) + 1

    key_apis = sorted(
        api_counts.keys(),
        key=lambda k: (-api_counts[k], k),
    )

    return {
        "required_namespaces": required_namespaces,
        "key_apis": key_apis,
    }
