# Retry Instruction Prompts

Escalating constraints injected on each retry attempt when the previous build failed.
The instructions become stricter with each attempt to resolve ambiguous type references
and namespace conflicts.

## Attempt 1

No additional instruction injected — the original prompt is retried as-is with pattern fixes applied.

## Attempt 2 (with CS0104 / CS0234 errors)

Triggered when compiler errors include ambiguous type references:

```
IMPORTANT: Use fully qualified Aspose.Pdf type names to avoid CS0104 ambiguity errors.
Examples: Aspose.Pdf.Color (not Color), Aspose.Pdf.Rectangle (not Rectangle),
Aspose.Pdf.Text.Font (not Font).
Do NOT add 'using System.Drawing;'.
```

## Attempt 2 (no specific error codes)

```
IMPORTANT: Use fully qualified Aspose.Pdf type names to avoid CS0104 ambiguity errors.
Do NOT add 'using System.Drawing;'.
```

## Attempt 3+ (critical escalation)

Applied on the third attempt regardless of error codes:

```
CRITICAL: Every Aspose.Pdf type MUST use its full namespace prefix.
Replace Color->Aspose.Pdf.Color, Rectangle->Aspose.Pdf.Rectangle,
Font->Aspose.Pdf.Text.Font, Point->Aspose.Pdf.Point.
Remove 'using System.Drawing;' and 'using Aspose.Pdf.Saving;'.
Only use: 'using Aspose.Pdf;', 'using Aspose.Pdf.Text;',
'using Aspose.Pdf.Tagged;', 'using Aspose.Pdf.LogicalStructure;' as needed.
```

## Why

The most common class of build failures in generated C# is CS0104 ambiguity between
`System.Drawing` types (Color, Rectangle, Font) and `Aspose.Pdf` types with the same name.
Escalating fully-qualified type enforcement resolves this without requiring LLM inference
about which namespace to prefer.

## Source

`pipeline/prompt_builder.py` → `build_retry_instruction()`
