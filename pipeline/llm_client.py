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

    def __init__(self, config: AppConfig):
        self.config = config
        self._session = requests.Session()
        retry = Retry(total=2, backoff_factor=0.5, status_forcelist=[502, 503, 504])
        adapter = HTTPAdapter(max_retries=retry, pool_connections=4, pool_maxsize=4)
        self._session.mount("http://", adapter)
        self._session.mount("https://", adapter)

    @property
    def available(self) -> bool:
        return bool(self.config.llm.api_key and self.config.llm.api_base)

    def chat(self, system: str, user: str, temperature: float = 0.0, max_tokens: int = 4000, timeout: int = 30) -> Optional[str]:
        """Generic chat completion. Returns content string or None."""
        if not self.available:
            return None
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
                msg = resp.json()["choices"][0]["message"]
                text = msg.get("content") or msg.get("reasoning_content") or ""
                return text.strip() if text else None
            return None
        except Exception as e:
            print(f"LLM chat error: {e}")
            return None

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

        content = self.chat(system, user, temperature=0.0, max_tokens=4000, timeout=30)
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

        content = self.chat(system, user, temperature=0.0, max_tokens=1000, timeout=20)
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
            "Do NOT include any test statistics, pass/fail counts, or pass rates in the body."
        )
        user = (
            f"Added {len(passed)} code example(s)\n"
            f"Categories: {', '.join(categories) if categories else 'uncategorized'}\n"
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
