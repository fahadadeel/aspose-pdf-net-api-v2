# Aspose.PDF for .NET Examples Generator — Release Pipeline, Self-Learning Rules & Structured Metadata

**March 2026 · Fahad Adeel**

---

When we [first introduced the Aspose.PDF for .NET Examples Generator](https://professionalizeagents.wordpress.com/2026/03/04/aspose-pdf-for-net-examples-generator-03-03-2026/) earlier this month, the tool could generate, compile, and publish examples to GitHub. Several major capabilities have shipped since then. This post covers all of them.

The short version: it has evolved from a code generator into a complete release pipeline — one that manages versioning, stages examples safely before they reach main, validates every file through CI, makes the entire library discoverable by AI coding agents, and gets measurably smarter with every run.

---

## A Complete Release Pipeline

The original workflow was linear: generate → compile → PR to main. The new workflow is version-aware and staged:

```
New Release
    ↓
Tags the current version on GitHub + creates a clean staging branch
    ↓
Batch Generate per category → each PR targets the staging branch (main untouched)
    ↓
GitHub Actions validates every PR automatically
    ↓
Review and merge each category PR into the staging branch
    ↓
Merge to Main → staging branch becomes the new release
```

Main is never touched during generation. Every category arrives as its own pull request, goes through its own CI check, and gets reviewed independently before anything ships.

---

## Version Lifecycle Management

The generator now manages the full release lifecycle — from tagging the outgoing version to creating a clean staging branch for the next one, and finally promoting that staging branch to main once all categories are reviewed.

When a new release cycle begins:
- The outgoing version (e.g. `v26.2.0`) is tagged on GitHub with a full GitHub Release
- A clean empty staging branch (e.g. `release/26.3.0`) is created with no prior history
- All subsequent pull requests automatically target that staging branch — main is never touched during generation

When all categories are generated, reviewed, and merged into the staging branch, the promotion step:
- Creates a pull request from the staging branch into main
- Tags the new version on GitHub
- Resets the PR target back to main, ready for the next cycle

Today this is triggered manually from the UI. The design is intentionally automation-ready — the same steps can be initiated by a webhook, a scheduled job, or a CI event when a new Aspose.PDF version is detected on NuGet.

---

## Batch Generate — One Click Per Category

The batch mode (previously called Sweep) processes an entire category in one run. Select one or more categories, click **Batch Generate**, and the pipeline:

- Runs every task in each selected category
- Creates a dedicated branch per category
- Commits all example files alongside structured metadata (more on this below)
- Opens a pull request per category targeting the staging branch with a rich, contextual description

Here's what that looks like in practice — all of these were generated and merged as part of the current `release/26.3.0` cycle:

- [PR #106](https://github.com/aspose-pdf/agentic-net-examples/pull/106) — 56 Basic Operations examples
- [PR #111](https://github.com/aspose-pdf/agentic-net-examples/pull/111) — 27 Compare PDF examples covering page ranges, exclusion zones, encrypted PDFs, multi-threaded batch processing
- [PR #113](https://github.com/aspose-pdf/agentic-net-examples/pull/113) — 105 Facades Annotations examples covering binding, deleting, exporting, importing, flattening, streaming, and validation
- [PR #115](https://github.com/aspose-pdf/agentic-net-examples/pull/115) — 40 PDF-to-image conversion examples across PNG, JPEG, BMP, and TIFF at varying DPI settings
- [PR #117](https://github.com/aspose-pdf/agentic-net-examples/pull/117) — 208 Facades Edit Document examples covering annotations, bookmarks, JavaScript actions, text replacement, security, metadata, and form manipulation

Each PR includes the `.cs` files, structured metadata, and AI discoverability files — all committed together and validated before merge.

---

## Making Examples Discoverable by AI Coding Agents

Code examples have always been written for humans. But the way developers work is changing — AI coding assistants are now the first stop for most questions. If your examples aren't structured in a way these agents can find and understand, they effectively don't exist.

In a [comment on the agents.md post](https://professionalizeagents.wordpress.com/2026/03/02/agents-md-2026-03-02/) that referenced our [original Examples Generator blog post](https://professionalizeagents.wordpress.com/2026/03/04/aspose-pdf-for-net-examples-generator-03-03-2026/), Ben Li put out a direct ask: *"Since it is a must to include agents.md in each GitHub repository, we have so many examples across so many GitHub repositories to add agents.md. May you pilot and prove it and then work with all product teams to that?"*

This is that pilot. Rather than writing and maintaining `agents.md` files by hand across hundreds of example repositories, the generator now produces and ships them automatically — alongside every single category, with every release.

[Andrey Spilney's follow-up in the same thread](https://professionalizeagents.wordpress.com/2026/03/02/agents-md-2026-03-02/comment-page-1/#comment-2694) frames why this matters at scale: `agents.md` is the *internal view* of a repository — a machine-readable guide for tools that will actually touch the code. It tells coding assistants, IDE agents, and autonomous dev bots what the conventions are, what the rules are, and what not to do. Not as documentation for humans to read, but as structured context for agents to act on.

Two files now ship with every category automatically.

### agents.md

Every category folder now contains an `agents.md` alongside the `.cs` files. The root of the repository has one too.

An AI coding agent that reads `agents.md` before generating or modifying any example immediately knows:

- How many verified examples are in the folder and what they cover
- Direct links to every `.cs` file in the category
- Category-specific API tips, patterns, and gotchas
- Hard rules — explicit types (never `var`), 1-based page indexing, fully qualified type names for ambiguous classes — with correct and incorrect code examples side by side
- How to build and run any example (`dotnet build`, `dotnet run`)

The root [agents.md](https://github.com/aspose-pdf/agentic-net-examples/blob/release/26.3.0/agents.md) covers repository-wide conventions, common anti-patterns extracted from real compilation errors across thousands of generation runs, and domain-specific knowledge about the Aspose.PDF API surface.

The result: an AI assistant working in a project that references this repository can generate new examples that match the existing style, follow the right conventions, and avoid the most common API mistakes — without the developer having to explain any of it.

### index.json

Each category folder also contains an `index.json` — a machine-readable catalog of every example. Here is a real entry from [compare-pdf/index.json](https://github.com/aspose-pdf/agentic-net-examples/blob/release/26.3.0/compare-pdf/index.json):

```json
{
  "title": "Compare Selected Page Range of Two PDFs",
  "filename": "compare-pdf-page-range__v2.cs",
  "description": "Loads two PDF files, sets a page range in ComparisonOptions, and compares the selected pages, saving a visual diff PDF.",
  "tags": ["pdf", "comparison", "pages", "csharp"],
  "apis_used": ["Document", "ComparisonOptions", "TextPdfComparer.CompareDocumentsPageByPage"],
  "difficulty": "intermediate",
  "status": "verified"
}
```

Every example gets a plain-English title and description, searchable tags, the actual Aspose.PDF classes and methods it uses, a difficulty rating, and a `status` of `verified` — meaning it compiled and ran successfully before it was ever committed.

This opens up use cases beyond direct agent consumption:

- **Search and filtering** — find all beginner-level examples that use a specific API class
- **Documentation sites** — generate structured API coverage pages from the catalog automatically
- **Gap analysis** — identify which API methods have no examples yet
- **AI retrieval** — an agent queries `index.json` to find the most relevant example before reading a single file

Neither file is manually maintained. Both are generated automatically as part of every batch run and committed in the same pull request as the examples themselves.

---

## CI Validation on Every Pull Request

A GitHub Actions workflow now runs automatically on every pull request targeting the staging branch or main. It validates only the `.cs` files changed in that PR — not the entire repository — so each category PR completes in roughly two minutes regardless of how many total examples exist.

For each changed file, the workflow:
- Compiles it against the correct .NET framework and NuGet version
- **Fails the PR if any file does not compile** — the merge is blocked until the issue is resolved
- Runs the example with a timeout to catch obvious runtime failures — informational, does not block merge
- Publishes a detailed result table to the GitHub Actions summary for review

The NuGet version is read directly from the repository's `index.json`, so it stays in sync automatically as versions change.

---

## Self-Learning Rule Engine

The pipeline now learns from every successful fix it makes.

When an example fails to compile and the system repairs it — whether through pattern matching or AI-assisted correction — it extracts the fix as a structured rule. Each rule captures the error pattern, the correct API approach, and a plain-English explanation of why the error happens.

These auto-learned rules appear in a **Learned Rules** tab in the UI. You can review them individually, approve the ones that look correct, or promote the entire batch at once. Approved rules immediately feed into future generation runs — the system gets better with each release cycle.

Over multiple runs, the rule engine has accumulated patterns covering Facades API naming, constructor constraints, type qualification requirements, and dozens of other Aspose.PDF-specific issues that don't appear in general C# documentation.

---

## Where the Repository Stands Today

The `release/26.3.0` branch currently contains:

| | |
|---|---|
| Verified C# examples | **866** |
| Categories | **11** |
| `index.json` catalogs | **11** (one per category) |
| `agents.md` guides | **12** (one per category + root) |
| Merged PRs | **11** |

All examples compiled and validated before commit. The repository is public:
**[github.com/aspose-pdf/agentic-net-examples](https://github.com/aspose-pdf/agentic-net-examples)**

The remaining categories are generating now and will be merged to the staging branch before promotion to main.

---

## What's Next

**Remaining categories** — the current release cycle is still running. Working With Annotations, Conversion, Forms, Images, Tables, Text, Graphs, Security, Stamps, and the remaining Facades categories will all follow the same pattern: Batch Generate → CI validation → PR review → merge to staging.

**Deduplication of the rule engine** — the curated rules library has grown significantly. An automated pass will consolidate near-duplicate entries while preserving the most precise version of each.

**Input file support** — examples that work with real PDF content (extraction, form filling, annotations on existing documents) currently use generated placeholder files. The next phase will link examples to actual Aspose sample files for more realistic outputs.

---

*The [first post](https://professionalizeagents.wordpress.com/2026/03/04/aspose-pdf-for-net-examples-generator-03-03-2026/) covered the generator architecture and how it works end-to-end. This post covers what has shipped since then. All numbers, links, and repository contents referenced above are live as of the publication date.*

@msabir74 FYI
