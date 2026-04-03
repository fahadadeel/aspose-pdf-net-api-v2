"""
pipeline/llm_client.py — LLM client for code fixing, decomposition, and PR generation.
"""

import json
import re
from typing import Optional

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from config import AppConfig


class LLMClient:
    """OpenAI-compatible LLM client using LITELLM_* configuration."""

    def __init__(self, config: AppConfig, usage_tracker=None):
        self.config = config
        self._usage_tracker = usage_tracker
        self._session = requests.Session()
        retry = Retry(total=2, backoff_factor=0.5, status_forcelist=[502, 503, 504])
        adapter = HTTPAdapter(max_retries=retry, pool_connections=4, pool_maxsize=4)
        self._session.mount("http://", adapter)
        self._session.mount("https://", adapter)

    @property
    def available(self) -> bool:
        return bool(self.config.llm.api_key and self.config.llm.api_base)

    def chat(self, system: str, user: str, temperature: float = 0.0, max_tokens: int = 4000, timeout: int = None) -> Optional[str]:
        """Generic chat completion. Returns content string or None."""
        if not self.available:
            return None
        if timeout is None:
            timeout = self.config.llm.timeout
        try:
            resp = self._session.post(
                f"{self.config.llm.api_base}/chat/completions",
                headers={
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {self.config.llm.api_key}",
                },
                json={
                    "model": self.config.llm.model,
                    "messages": [
                        {"role": "system", "content": system},
                        {"role": "user", "content": user},
                    ],
                    "temperature": temperature,
                    "max_tokens": max_tokens,
                },
                timeout=timeout,
            )
            if resp.status_code == 200:
                data = resp.json()
                msg = data["choices"][0]["message"]
                text = msg.get("content") or msg.get("reasoning_content") or ""
                # Track token usage if tracker is attached
                if self._usage_tracker:
                    usage = data.get("usage", {})
                    total_tokens = usage.get("total_tokens", 0)
                    if total_tokens:
                        self._usage_tracker.add_llm_usage(total_tokens)
                    else:
                        self._usage_tracker.add_llm_call()
                return text.strip() if text else None
            return None
        except Exception as e:
            print(f"LLM chat error: {e}")
            return None

    def validate_against_rules(self, code: str, rules_text: str) -> Optional[str]:
        """Two-pass validation: check generated code against critical rules.

        Asks the LLM to review the code for rule violations and return the
        fixed version.  Returns fixed code if violations were found, or
        None if the code is already compliant (or on error).
        """
        if not rules_text or not code:
            return None

        system = (
            "You are a strict C# code reviewer for Aspose.PDF. "
            "Check the given code against the CRITICAL RULES below. "
            "If the code violates ANY rule, fix ALL violations and return "
            'ONLY a JSON object: {"violations_found": true, "fixed_code": "...the complete fixed C# code..."}\n'
            "If the code is compliant with all rules, return: "
            '{"violations_found": false}'
        )
        user = f"CRITICAL RULES:\n{rules_text}\n\nCODE TO REVIEW:\n```csharp\n{code}\n```"

        content = self.chat(system, user, temperature=0.0, max_tokens=4000,
                            timeout=self.config.llm.timeout)
        if not content:
            return None

        # Strip markdown fences
        if content.startswith("```"):
            content = re.sub(r"^```(?:json)?\s*", "", content)
            content = re.sub(r"\s*```$", "", content)

        try:
            data = json.loads(content)
            if data.get("violations_found") and data.get("fixed_code"):
                return data["fixed_code"]
            return None  # compliant or no fixed_code
        except json.JSONDecodeError:
            # Try to extract code directly
            code_match = re.search(r"```csharp\s*(.*?)```", content, re.DOTALL)
            if code_match:
                return code_match.group(1).strip()
            return None

    def extract_metadata(self, task: str, code: str, category: str = "") -> dict:
        """Extract metadata from compiled C# code for index.json enrichment.

        Called once per passed example, after the final code compiles.
        Returns a dict with: title, filename, description, tags, apis_used, difficulty.
        Returns empty dict on failure (caller falls back to defaults).
        """
        prompt = f"""Analyze this C# code example and return a JSON object with metadata.

TASK DESCRIPTION:
{task}

CATEGORY:
{category or "uncategorized"}

CODE:
```csharp
{code}
```

Return a JSON object with exactly these keys:
{{
  "title": "<concise human-readable title, e.g. 'Add Text Watermark to PDF Pages'>",
  "filename": "<kebab-case name without .cs, max 60 chars, e.g. 'add-text-watermark-to-pdf-pages'>",
  "description": "<1-2 sentences describing what this example demonstrates>",
  "tags": ["<keyword1>", "<keyword2>", "<keyword3>"],
  "apis_used": ["<Aspose.Pdf.ClassName>", "<Aspose.Pdf.Namespace.MethodName>"],
  "difficulty": "<beginner|intermediate|advanced>"
}}

Rules:
- "title" should be concise and descriptive
- "filename" must be lowercase kebab-case, max 60 chars
- "tags" max 5 short keywords relevant to the example
- "apis_used" list ONLY Aspose.Pdf classes/methods actually used in the code (not System types)
- "difficulty" based on complexity: simple API calls = beginner, multi-step = intermediate, advanced patterns = advanced
- Output ONLY the JSON object, no other text"""

        content = self.chat("", prompt, temperature=0.0, max_tokens=1000)
        if not content:
            return {}

        # Strip markdown fences if present
        content = content.strip()
        if content.startswith("```"):
            content = re.sub(r"^```(?:json)?\s*", "", content)
            content = re.sub(r"\s*```$", "", content.strip()).strip()

        try:
            data = json.loads(content)
            if isinstance(data, dict):
                # Ensure expected keys exist
                return {
                    "title": data.get("title", ""),
                    "filename": data.get("filename", ""),
                    "description": data.get("description", ""),
                    "tags": data.get("tags", []),
                    "apis_used": data.get("apis_used", []),
                    "difficulty": data.get("difficulty", ""),
                }
        except (json.JSONDecodeError, ValueError):
            pass
        return {}

    def fix_code(self, task: str, code: str, build_error: str, user_rules: str = "") -> Optional[str]:
        """Ask LLM to fix broken code. Returns fixed code or None."""
        system = (
            "You are a senior C#/.NET developer specializing in Aspose.PDF. "
            "Fix the build error and return ONLY a JSON object: "
            '{"fixed_code": "...the complete fixed C# code...", "rules": "...any patterns learned..."}'
        )
        user = f"TASK:\n{task}\n\nPROGRAM.CS:\n```csharp\n{code}\n```\n\nBUILD ERROR:\n```\n{build_error}\n```"
        if user_rules:
            user += f"\n\nEXTRA CONTEXT:\n{user_rules}"

        content = self.chat(system, user, temperature=0.0, max_tokens=4000, timeout=self.config.llm.timeout)
        if not content:
            return None

        # Strip markdown fences
        if content.startswith("```"):
            content = re.sub(r"^```(?:json)?\s*", "", content)
            content = re.sub(r"\s*```$", "", content)

        try:
            data = json.loads(content)
            return data.get("fixed_code")
        except json.JSONDecodeError:
            # Try to extract code directly
            code_match = re.search(r"```csharp\s*(.*?)```", content, re.DOTALL)
            if code_match:
                return code_match.group(1).strip()
            return None

    def decompose_task(self, task: str, context: str = "") -> Optional[str]:
        """Decompose task into atomic steps. Returns enriched task or None."""
        system = (
            "Rewrite the TASK into atomic steps and workflow rules. "
            "Return STRICT JSON: "
            '{"atomic_steps": ["step1", "step2", ...], "workflow_rules": ["rule1", "rule2", ...]}'
        )
        user = f"TASK:\n{task}"
        if context:
            user += f"\n\nEXTRA CONTEXT:\n{context}"

        content = self.chat(system, user, temperature=0.0, max_tokens=1000, timeout=self.config.llm.timeout)
        if not content:
            return None

        if content.startswith("```"):
            content = re.sub(r"^```(?:json)?\s*", "", content)
            content = re.sub(r"\s*```$", "", content)

        try:
            data = json.loads(content)
            steps = data.get("atomic_steps", [])
            rules = data.get("workflow_rules", [])
            parts = []
            if steps:
                parts.append("Decomposed plan:\n" + "\n".join(f"- {s}" for s in steps))
            if rules:
                parts.append("Workflow rules:\n" + "\n".join(f"- {r}" for r in rules))
            return "\n\n".join(parts) if parts else None
        except json.JSONDecodeError:
            return None

    def generate_commit_message(self, prompt: str, category: str, code_snippet: str) -> Optional[dict]:
        """Generate commit title and description. Returns {title, description} or None."""
        system = (
            "You are a git commit message expert. Generate a clear commit message.\n"
            'Return ONLY JSON: {"title": "...", "description": "..."}\n'
            "Title: 50 chars max, imperative mood. Description: 2-3 sentences."
        )
        user = (
            f"Category: {category}\nTask: {prompt}\n"
            f"Code Preview:\n```csharp\n{code_snippet[:500]}\n```"
        )
        content = self.chat(system, user, temperature=0.3, max_tokens=300, timeout=15)
        if not content:
            return None

        if content.startswith("```"):
            content = re.sub(r"^```(?:json)?\s*", "", content)
            content = re.sub(r"\s*```$", "", content)

        try:
            data = json.loads(content)
            if "title" in data and "description" in data:
                return data
        except json.JSONDecodeError:
            pass
        return None

    def generate_code(self, task: str, chunks_text: str = "",
                      rules_text: str = "", category: str = "") -> Optional[dict]:
        """Generate C# code using the same prompt structure as MCP /generate.

        Replicates the MCP server's prompt.py build_prompt() — single user message
        with rules, task, documentation context, and output requirements.

        Returns a dict with keys:
            code        — the generated C# source code (required)
            title       — human-readable example title
            filename    — recommended kebab-case filename stem (no .cs)
            description — 1-2 sentence summary of what the example demonstrates
            tags        — list of short keyword strings
            apis_used   — list of Aspose.Pdf API class/method names used
            difficulty  — beginner / intermediate / advanced
        Returns None if generation fails.
        """
        prompt = f"""You are an Aspose.Pdf expert for NET.

==============================
RULE EXECUTION CONTRACT
==============================

You are provided with executable code rules.

CRITICAL INSTRUCTIONS:

1) LIFECYCLE RULES (MANDATORY)
- You MUST use the provided create, load and save rules.
- You are NOT allowed to write your own Document creation or saving code.

2) FEATURE RULES (CONDITIONAL STRICT)
- If a rule exists that matches the requested operation, you MUST use the rule instead of inventing your own implementation.
- You are allowed to generate free-form code ONLY when NO matching rule exists.
- Don't apply rules blindly, instead only apply for the portion of the element where applicable.

3) TEMPLATE USAGE POLICY
- You MUST preserve rule structure.
- You MAY only replace placeholders inside rules.
- You MUST NOT restructure rule logic.

4) VIOLATION POLICY
- Do NOT invent alternative APIs if a rule is available.
- Do NOT duplicate lifecycle logic.
- Do NOT bypass available rules.

AVAILABLE RULES:
----------------
{rules_text}
----------------

TASK:
{task}

GROUND TRUTH DOCUMENTATION:
{chunks_text}

CODE STYLE RULES (MANDATORY — violations will be rejected):
- NEVER use `var`. Always declare the explicit type: `Document doc = new Document();` NOT `var doc = new Document();`
- NEVER use implicit usings. Always write every `using` directive explicitly at the top of the file.
- ALWAYS use fully qualified type names when ambiguity exists: `Aspose.Pdf.Color`, `Aspose.Pdf.Rectangle`, `Aspose.Pdf.Image`.
- ALWAYS use explicit float literals: `0.5f` or `(float)0.5`, never assign a double literal to a float variable.
- ALWAYS wrap `Document` operations in `using` blocks: `using (Document doc = new Document()) {{ ... }}`
- Output path must be a simple filename: `doc.Save("output.pdf");` — no directory paths.

OUTPUT REQUIREMENTS:
Return a JSON object with exactly these keys:
{{
  "code": "<valid C# source code — no markdown fences, compilable>",
  "title": "<concise human-readable title, e.g. 'Add Text Annotation to PDF Page'>",
  "filename": "<kebab-case filename stem without extension, e.g. 'add-text-annotation'>",
  "description": "<1-2 sentences describing what the example demonstrates>",
  "tags": ["<keyword1>", "<keyword2>"],
  "apis_used": ["<Aspose.Pdf.ClassName>", "<Aspose.Pdf.Namespace.MethodName>"],
  "difficulty": "<beginner|intermediate|advanced>"
}}

Rules for the JSON:
- "code" must be pure C# — no markdown, no JSON wrapper inside it, must compile
- "filename" must be lowercase kebab-case, max 60 chars, no .cs extension
- "tags" max 5 short keywords
- "apis_used" list the main Aspose.Pdf classes/methods actually used in the code
- Output ONLY the JSON object, no other text
"""
        # MCP server uses temperature=0.1, single user message (no system prompt)
        content = self.chat("", prompt, temperature=0.1, max_tokens=4500)
        if not content:
            return None

        # Strip markdown fences if present
        content = content.strip()
        if content.startswith("```"):
            content = re.sub(r"^```(?:json)?\s*", "", content)
            content = re.sub(r"\s*```$", "", content.strip()).strip()

        # Parse JSON response
        try:
            data = json.loads(content)
            if isinstance(data, dict) and data.get("code"):
                return data
        except (json.JSONDecodeError, ValueError):
            pass

        # Fallback: treat entire response as raw code (backward compat)
        if content.strip():
            return {"code": content.strip()}
        return None

    def generate_pr_details(self, results_summary: list) -> Optional[dict]:
        """Generate PR title and body. Returns {title, body} or None."""
        passed = [r for r in results_summary if r.get("status") == "PASSED"]
        categories = sorted(set(r.get("category", "uncategorized") for r in results_summary if r.get("category")))

        examples_text = ""
        for r in passed[:30]:
            examples_text += f"  [{r.get('category', 'uncategorized')}] {r.get('task', '')[:100]}\n"

        system = (
            "You are a GitHub PR expert. Generate PR title and body.\n"
            'Return ONLY JSON: {"title": "...", "body": "..."}\n'
            "Title: under 70 chars. Body: markdown with summary and categories.\n"
            "Do NOT include any test statistics, pass/fail counts, or pass rates in the body.\n"
            "Each category is a SINGLE name — do NOT split category names on dashes or hyphens."
        )
        cat_list = "\n".join(f'  - "{c}"' for c in categories) if categories else '  - "uncategorized"'
        user = (
            f"Added {len(passed)} code example(s)\n"
            f"Categories (each line is ONE category):\n{cat_list}\n"
            f"Examples:\n{examples_text}"
        )
        content = self.chat(system, user, temperature=0.3, max_tokens=1000, timeout=20)
        if not content:
            return None

        if content.startswith("```"):
            content = re.sub(r"^```(?:json)?\s*", "", content)
            content = re.sub(r"\s*```$", "", content)

        try:
            data = json.loads(content)
            if "title" in data and "body" in data:
                return data
        except json.JSONDecodeError:
            pass
        return None
