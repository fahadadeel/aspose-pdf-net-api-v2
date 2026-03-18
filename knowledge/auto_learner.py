"""
knowledge/auto_learner.py — Self-learning: extract reusable rules from successful fixes.

When the pipeline fails at Stage 1 but succeeds at a later stage, the code diff
contains a valuable signal. This module uses the LLM to generalize that fix into
an error_fixes.json-compatible rule that helps future runs avoid the same error.

All learning runs in daemon threads so it never blocks the pipeline.
"""

import difflib
import json
import re
import time
import threading
from typing import Optional

from config import AppConfig
from knowledge.auto_fixes import save_auto_fix, is_duplicate_rule, load_auto_fixes
from knowledge.error_fixes import load_error_fixes


_GENERALIZE_SYSTEM = """\
You are an Aspose.PDF for .NET API expert. You analyze code diffs from build error fixes
and extract reusable rules in a structured JSON format.

Your job: given a failing C# code snippet, the build errors, and the fixed code,
extract the API-level fix pattern (not the whole program) into a compact rule.

Output ONLY valid JSON with this exact structure:
{
  "rule_id": "kebab-case-descriptive-id",
  "rule": {
    "note": "One sentence explaining the API fix pattern",
    "code": "Minimal C# snippet showing the correct API usage (not the full program)",
    "errors": ["error pattern 1 that this fix resolves", "error pattern 2"]
  }
}

Guidelines:
- rule_id should describe the fix (e.g. "use-mhtmlloadoptions-for-mhtml", "qualify-rectangle-type")
- note should be a prescriptive instruction (e.g. "Use MhtLoadOptions instead of HtmlLoadOptions for MHTML files")
- code should be the MINIMAL snippet showing correct usage, not the entire program
- errors should contain the actual error messages/patterns this fix addresses
- Focus on Aspose.PDF API patterns, not general C# fixes
- If the diff is purely task-specific with no reusable pattern, return {"skip": true}
"""

_CATALOG_SYSTEM = """\
You are an Aspose.PDF for .NET API expert. Given a C# build error and its fix,
generate a concise error catalog entry.

Output ONLY valid JSON:
{
  "pattern": "regex-safe string matching the error message",
  "error_code": "CS1061",
  "fix_guidance": "1-2 sentence prescriptive fix instruction"
}

If the error is too generic or task-specific to be useful as a catalog entry, return {"skip": true}
"""


class AutoLearner:
    """Extracts reusable rules from successful pipeline fixes."""

    def __init__(self, config: AppConfig, llm_client):
        self.config = config
        self.llm = llm_client
        self._min_diff_lines = config.pipeline.auto_learn_min_diff_lines

    def learn_from_success(
        self,
        task: str,
        category: str,
        failing_code: str,
        fixed_code: str,
        error_output: str,
        error_codes: list,
        stage: str,
    ) -> None:
        """Extract a reusable rule from a successful fix. Runs in daemon thread."""
        try:
            self._learn_error_fix(task, category, failing_code, fixed_code, error_output, error_codes, stage)
        except Exception as e:
            print(f"[AutoLearner] Error in learn_from_success: {e}")

        # Phase 3: Also try to generate a catalog entry
        if self.config.pipeline.auto_learn_catalog:
            try:
                self._learn_catalog_entry(task, failing_code, fixed_code, error_output, error_codes)
            except Exception as e:
                print(f"[AutoLearner] Error in catalog learning: {e}")

    def _learn_error_fix(
        self, task, category, failing_code, fixed_code, error_output, error_codes, stage
    ) -> None:
        """Generate an error_fixes.json-compatible rule from a successful fix."""
        if stage == "baseline":
            return

        diff = self._compute_diff(failing_code, fixed_code)
        changed_lines = sum(1 for line in diff.split("\n") if line.startswith("+") or line.startswith("-"))
        if changed_lines < self._min_diff_lines:
            return

        if not self.llm or not self.llm.available:
            return

        user_prompt = (
            f"## Task\n{task[:300]}\n\n"
            f"## Build Errors\n{error_output[:2000]}\n\n"
            f"## Code Diff\n{diff[:3000]}\n\n"
            f"## Fixed Code (first 200 lines)\n{self._first_n_lines(fixed_code, 200)}"
        )

        response = self.llm.chat(
            system=_GENERALIZE_SYSTEM,
            user=user_prompt,
            temperature=0.1,
            max_tokens=1000,
            timeout=30,
        )
        if not response:
            return

        parsed = self._parse_json(response)
        if not parsed or parsed.get("skip"):
            return

        rule_id = parsed.get("rule_id", "")
        rule = parsed.get("rule", {})
        if not rule_id or not rule.get("errors"):
            return

        # Add auto-learning metadata
        rule["_auto"] = True
        rule["_confidence"] = 0.5
        rule["_created_at"] = time.time()
        rule["_hit_count"] = 0
        rule["_stage"] = stage
        rule["_category"] = category

        # Dedup against curated + existing auto fixes
        curated = load_error_fixes(self.config.error_fixes_path)
        if self._is_duplicate(rule_id, rule.get("errors", []), curated):
            return

        if is_duplicate_rule(self.config.auto_fixes_path, rule_id, rule.get("errors", [])):
            return

        save_auto_fix(self.config.auto_fixes_path, rule_id, rule)
        print(f"[AutoLearner] Learned rule: '{rule_id}' from {stage} success")

    def _learn_catalog_entry(self, task, failing_code, fixed_code, error_output, error_codes):
        """Generate an error_catalog.json entry from a successful fix."""
        if not error_codes or not self.llm or not self.llm.available:
            return

        diff = self._compute_diff(failing_code, fixed_code)

        user_prompt = (
            f"## Build Errors\n{error_output[:2000]}\n\n"
            f"## Error Codes\n{', '.join(error_codes[:5])}\n\n"
            f"## Code Diff\n{diff[:2000]}"
        )

        response = self.llm.chat(
            system=_CATALOG_SYSTEM,
            user=user_prompt,
            temperature=0.1,
            max_tokens=500,
            timeout=20,
        )
        if not response:
            return

        parsed = self._parse_json(response)
        if not parsed or parsed.get("skip"):
            return

        pattern = parsed.get("pattern", "")
        fix_guidance = parsed.get("fix_guidance", "")
        error_code = parsed.get("error_code", "")
        if not pattern or not fix_guidance:
            return

        # Add metadata
        entry = {
            "pattern": pattern,
            "error_code": error_code,
            "fix_guidance": fix_guidance,
            "_auto": True,
            "_confidence": 0.5,
            "_hit_count": 0,
            "_created_at": time.time(),
        }

        _save_auto_catalog_entry(self.config.auto_catalog_path, entry)

    def _is_duplicate(self, rule_id: str, errors: list, curated: dict) -> bool:
        """Check if rule duplicates a curated fix."""
        if rule_id in curated:
            return True
        new_set = set(e.lower().strip() for e in errors)
        for fix in curated.values():
            old_set = set(e.lower().strip() for e in fix.get("errors", []))
            if old_set and new_set:
                overlap = len(old_set & new_set)
                if overlap / min(len(old_set), len(new_set)) > 0.5:
                    return True
        return False

    @staticmethod
    def _compute_diff(old_code: str, new_code: str) -> str:
        """Compute unified diff between old and new code."""
        old_lines = old_code.splitlines(keepends=True)
        new_lines = new_code.splitlines(keepends=True)
        diff = difflib.unified_diff(old_lines, new_lines, fromfile="failing.cs", tofile="fixed.cs", n=3)
        return "".join(diff)

    @staticmethod
    def _first_n_lines(text: str, n: int) -> str:
        lines = text.split("\n")
        return "\n".join(lines[:n])

    @staticmethod
    def _parse_json(text: str) -> Optional[dict]:
        """Extract JSON from LLM response (handles markdown code blocks)."""
        # Try direct parse
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass
        # Try extracting from code block
        match = re.search(r"```(?:json)?\s*\n?(.*?)```", text, re.DOTALL)
        if match:
            try:
                return json.loads(match.group(1).strip())
            except json.JSONDecodeError:
                pass
        # Try finding first { ... }
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if match:
            try:
                return json.loads(match.group(0))
            except json.JSONDecodeError:
                pass
        return None


# ── Auto Error Catalog persistence ──

_CATALOG_LOCK = threading.Lock()
_MAX_CATALOG_ENTRIES = 200


def _save_auto_catalog_entry(path: str, entry: dict) -> bool:
    """Save a single auto-learned catalog entry. Thread-safe."""
    from pathlib import Path

    with _CATALOG_LOCK:
        p = Path(path)
        try:
            if p.exists():
                existing = json.loads(p.read_text(encoding="utf-8"))
                if not isinstance(existing, list):
                    existing = []
            else:
                existing = []

            # Dedup by pattern
            for e in existing:
                if e.get("pattern", "").lower() == entry["pattern"].lower():
                    return False

            existing.append(entry)

            # Prune oldest if over cap
            if len(existing) > _MAX_CATALOG_ENTRIES:
                existing = existing[-_MAX_CATALOG_ENTRIES:]

            p.write_text(json.dumps(existing, indent=2, ensure_ascii=False), encoding="utf-8")
            print(f"[AutoLearner] Learned catalog entry: {entry['pattern'][:60]}...")
            return True
        except Exception as e:
            print(f"[AutoLearner] Failed to save catalog entry: {e}")
            return False


def load_auto_error_catalog(path: str) -> list:
    """Load auto-learned error catalog entries."""
    from pathlib import Path

    with _CATALOG_LOCK:
        p = Path(path)
        if not p.exists():
            return []
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
            return data if isinstance(data, list) else []
        except (json.JSONDecodeError, Exception):
            return []
