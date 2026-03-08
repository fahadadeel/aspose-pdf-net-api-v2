"""
pipeline/anthropic_client.py — Anthropic Claude client for post-pipeline rule learning.

Uses the official anthropic SDK to analyze failed pipeline tasks,
fix code, and extract reusable error fix rules.
"""

import json
import re
from typing import Optional

import anthropic

from config import AppConfig


class AnthropicClient:
    """Client for Anthropic Claude API — used for post-pipeline rule learning."""

    def __init__(self, config: AppConfig):
        self.config = config
        self._client = anthropic.Anthropic(api_key=config.anthropic.api_key)
        self.model = config.anthropic.model

    @property
    def available(self) -> bool:
        return bool(self.config.anthropic.api_key)

    def fix_and_extract_rule(
        self,
        task: str,
        original_code: str,
        build_error: str,
        fixes_context: str = "",
    ) -> Optional[dict]:
        """Ask Claude to fix the code AND generate a structured rule.

        Returns dict with keys:
            - fixed_code: str (the corrected C# code)
            - rule_id: str (slug identifier)
            - rule: dict matching error_fixes.json format:
                - note: str
                - errors: list[str]
                - code: str
        Returns None if Claude cannot fix or parse fails.
        """
        if not self.available:
            return None

        tfm = self.config.build.tfm
        nuget_pkg = self.config.build.nuget_package
        nuget_ver = self.config.build.nuget_version

        system_prompt = (
            "You are a senior C#/.NET developer specializing in Aspose.PDF for .NET. "
            "Your job is to:\n"
            "1. Fix the broken C# code so it compiles and runs successfully.\n"
            "2. Extract a reusable rule that describes what was wrong and how to fix it.\n\n"
            f"BUILD ENVIRONMENT:\n"
            f"- Target framework: {tfm}\n"
            f"- NuGet package: {nuget_pkg} v{nuget_ver}\n"
            f"- ImplicitUsings: disable (you must include ALL using directives explicitly)\n"
            f"- The program runs as a standalone console app\n\n"
            "CRITICAL RULES FOR WORKING CODE:\n"
            "- Use explicit casts for float literals: use (float)0.5 or 0.5f, never assign double to float.\n"
            "- Always use fully qualified Aspose.Pdf.Rectangle and Aspose.Pdf.Color to avoid ambiguity with System.Drawing.\n"
            "- Do NOT create or load external PDF files (no File.Open, no loading from disk paths). "
            "Create new Document() from scratch and save to a simple filename like 'output.pdf'.\n"
            "- Wrap Document operations in using statements or try/finally with doc.Dispose().\n"
            "- When adding Graph objects: create Graph with dimensions, add shapes to Graph.Shapes, "
            "then add Graph to page.Paragraphs.\n"
            "- For runtime errors at Document.Save(): check that all objects are properly initialized "
            "before saving — null references in page content cause Save() to crash internally.\n"
            "- Ensure all added objects (graphs, shapes, annotations) have valid non-null properties.\n\n"
            "Return ONLY a JSON object with this exact structure:\n"
            "{\n"
            '  "fixed_code": "...the complete fixed C# program...",\n'
            '  "rule_id": "short-kebab-case-slug-describing-the-fix",\n'
            '  "rule": {\n'
            '    "note": "A clear human-readable explanation of the error and the correct approach",\n'
            '    "errors": [\n'
            '      "The exact or representative error message pattern that this rule fixes"\n'
            "    ],\n"
            '    "code": "// A minimal CORRECT code snippet showing the fix pattern\\n..."\n'
            "  }\n"
            "}\n\n"
            "Guidelines for the rule:\n"
            "- The 'note' should explain WHY the error happens and what the correct API usage is.\n"
            "- The 'errors' array should contain the key error messages (with CS codes) that this rule addresses. "
            "Include the error code like 'CS1061' or 'CS0246' if applicable.\n"
            "- The 'code' should be a minimal, self-contained snippet showing CORRECT usage, "
            "with comments showing the WRONG approach.\n"
            "- The 'rule_id' should be a unique kebab-case slug, e.g., 'fix-border-no-parameterless-ctor'.\n"
            "- Focus on Aspose.PDF API-specific patterns, not general C# syntax.\n"
            "- Do NOT invent errors that are not present in the build output.\n"
            "- Return ONLY the JSON object, no markdown fences, no extra text."
        )

        user_prompt = (
            f"TASK:\n{task}\n\n"
            f"ORIGINAL CODE (Program.cs):\n```csharp\n{original_code}\n```\n\n"
            f"BUILD/RUN ERROR:\n```\n{build_error[:4000]}\n```"
        )

        # Append matched error fixes as proven reference patterns
        if fixes_context:
            user_prompt += (
                f"\n\nREFERENCE — These are proven fixes for similar errors. "
                f"Study them carefully and apply the same patterns:\n{fixes_context}"
            )

        try:
            message = self._client.messages.create(
                model=self.model,
                max_tokens=4096,
                messages=[
                    {"role": "user", "content": user_prompt},
                ],
                system=system_prompt,
                temperature=0.0,
            )

            content = message.content[0].text.strip()

            # Strip markdown fences if present
            if content.startswith("```"):
                content = re.sub(r"^```(?:json)?\s*", "", content)
                content = re.sub(r"\s*```$", "", content)

            data = json.loads(content)

            # Validate required fields
            fixed_code = data.get("fixed_code")
            rule_id = data.get("rule_id")
            rule = data.get("rule")

            if not fixed_code or not rule_id or not rule:
                return None

            if not isinstance(rule, dict):
                return None

            if "note" not in rule or "errors" not in rule or "code" not in rule:
                return None

            return {
                "fixed_code": fixed_code,
                "rule_id": rule_id,
                "rule": rule,
            }

        except anthropic.APIError as e:
            print(f"Anthropic API error: {e}")
            return None
        except json.JSONDecodeError as e:
            print(f"Failed to parse Anthropic response as JSON: {e}")
            return None
        except Exception as e:
            print(f"Anthropic client error: {e}")
            return None
