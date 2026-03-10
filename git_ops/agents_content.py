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


def load_category_tips(kb_path: str, category_name: str, max_count: int = 5) -> str:
    """Build category-specific tips from kb.json for a particular category.

    Returns markdown with API surface info, rules, and warnings.

    Matching strategy:
    1. Exact match (case-insensitive, hyphen/space agnostic)
    2. Keyword fallback — split the category name into keywords and match
       KB categories that contain any keyword (min 4 chars).
       e.g. "Facades - Secure Documents" matches "Facades" and "Security-Signatures".

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
        """Check if a KB entry belongs to the Facades namespace."""
        ns = entry.get("namespace", "").lower()
        cat = entry.get("category", "").lower()
        return "facades" in ns or "facades" in cat

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
        keywords = [w for w in re.split(r"[\s\-_]+", category_name.lower()) if len(w) >= 4]
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
