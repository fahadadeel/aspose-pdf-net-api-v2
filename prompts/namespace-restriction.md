# Namespace Restriction Prompt

Injected into generation prompts for non-facade categories to prevent use of deprecated or
restricted Aspose.PDF namespaces.

**Trigger**: Any category whose name does not contain `facades`.

**Excluded namespaces**: `Aspose.Pdf.Plugins`, `Aspose.Pdf.Facades`

## Template

```
NAMESPACE RESTRICTION: Do NOT use the following namespaces: Aspose.Pdf.Plugins, Aspose.Pdf.Facades.
Do not add 'using Aspose.Pdf.Plugins;' or 'using Aspose.Pdf.Facades;'.
Use only the core Aspose.Pdf.* APIs (e.g. Document, Page, TextFragment, Table,
TextAbsorber) -- not Facades wrappers like PdfFileEditor, FormEditor, PdfFileSecurity,
PdfFileStamp, PdfFileMend.
```

## Why

`Aspose.Pdf.Facades` is a legacy wrapper layer. Generated examples should demonstrate the
modern core API. `Aspose.Pdf.Plugins` is excluded for non-plugin categories to keep examples
focused and avoid dependency on plugin-specific assemblies.

## Source

`pipeline/prompt_builder.py` → `build_namespace_restriction()`
