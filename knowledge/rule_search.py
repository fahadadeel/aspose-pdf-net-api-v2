"""
knowledge/rule_search.py — Hybrid semantic + keyword search for KB rules.
"""

import json
import math
import re
from pathlib import Path
from typing import Dict, List, Optional

_STOPWORDS = frozenset({
    'a', 'an', 'the', 'and', 'or', 'but', 'in', 'on', 'at', 'to', 'for',
    'of', 'with', 'by', 'from', 'as', 'is', 'are', 'was', 'were', 'be',
    'been', 'being', 'have', 'has', 'had', 'do', 'does', 'did', 'will',
    'would', 'could', 'should', 'may', 'might', 'shall', 'can',
    'not', 'no', 'nor', 'so', 'yet', 'both', 'either', 'neither',
    'each', 'few', 'more', 'most', 'other', 'some', 'such', 'than',
    'too', 'very', 'just', 'also', 'how', 'what', 'which', 'when', 'where',
    'code', 'example', 'using', 'return', 'value', 'true', 'false', 'null',
})


class RuleSearchEngine:
    """Hybrid cosine + IDF keyword search for KB rules."""

    def __init__(self):
        self._model = None
        self._embeddings = None
        self._items: List[dict] = []
        self._texts: List[str] = []
        self._idf: dict = {}
        self._loaded = False

    def load(self, path: str, shared_model=None) -> bool:
        """Load rules from kb.json and build embeddings + IDF."""
        if self._loaded:
            return True

        p = Path(path)
        if not p.exists():
            return False

        try:
            from sentence_transformers import SentenceTransformer
        except ImportError:
            print("sentence-transformers not installed — rule search disabled")
            return False

        try:
            if shared_model:
                self._model = shared_model
            elif self._model is None:
                self._model = SentenceTransformer("all-MiniLM-L6-v2")

            data = json.loads(p.read_text(encoding="utf-8"))
            items = data if isinstance(data, list) else data.get("items", [])
            if not items:
                return False

            texts = []
            for item in items:
                parts = [item.get("semantic_summary", "")]
                api = item.get("api_surface", [])
                if api:
                    parts.append(" | ".join(api))
                rules_text = " ".join(item.get("rules", []))
                if rules_text:
                    parts.append(rules_text)
                warnings_text = " ".join(item.get("warnings", []))
                if warnings_text:
                    parts.append(warnings_text)
                texts.append(" | ".join(parts))

            self._idf = self._build_idf(texts)
            self._embeddings = self._model.encode(texts, convert_to_tensor=True)
            self._items = items
            self._texts = texts
            self._loaded = True
            print(f"Rule search ready: {len(items)} rules indexed")
            return True

        except Exception as e:
            print(f"Failed to load rules: {e}")
            return False

    def find_top_rules(self, query: str, top_k: int, error_codes: List[str] = None, history_boosts: Dict[str, float] = None) -> List[dict]:
        """Return top-k rules via hybrid search."""
        if not self._loaded or not self._items:
            return []
        try:
            return self._hybrid_search(query, top_k, error_codes, history_boosts)
        except Exception as e:
            print(f"Rule search error: {e}")
            return []

    def _hybrid_search(self, query: str, top_k: int, error_codes: List[str] = None, history_boosts: Dict[str, float] = None) -> List[dict]:
        from sentence_transformers import util
        import numpy as np

        sem_w, kw_w = 0.55, 0.45
        if error_codes:
            api_codes = {"CS1061", "CS1729", "CS0234", "CS0030"}
            if any(c in api_codes for c in error_codes):
                sem_w, kw_w = 0.35, 0.65

        query_tokens = self._tokenize(query)
        q_emb = self._model.encode(query, convert_to_tensor=True)
        sem_scores = util.cos_sim(q_emb, self._embeddings)[0].cpu().numpy().astype(float)
        kw_scores = np.array([self._keyword_score(query_tokens, self._texts[i]) for i in range(len(self._texts))], dtype=float)

        def norm(arr):
            lo, hi = arr.min(), arr.max()
            return (arr - lo) / (hi - lo + 1e-8)

        fused = sem_w * norm(sem_scores) + kw_w * norm(kw_scores)

        if history_boosts:
            for idx, item in enumerate(self._items):
                rid = item.get("id", "")
                if rid and rid in history_boosts:
                    fused[idx] += history_boosts[rid]

        k = min(top_k, len(self._items))
        top_indices = np.argsort(fused)[::-1][:k]
        return [self._items[int(i)] for i in top_indices]

    def _tokenize(self, text: str) -> List[str]:
        raw = re.findall(r"[A-Za-z0-9_.:/\-]+", text)
        tokens = []
        for chunk in raw:
            for tok in self._split_camel(chunk):
                if len(tok) > 4:
                    if tok.endswith("ies"): tok = tok[:-3] + "y"
                    elif tok.endswith("es") and len(tok) > 5: tok = tok[:-2]
                    elif tok.endswith("s"): tok = tok[:-1]
                if tok and len(tok) > 2 and tok not in _STOPWORDS:
                    tokens.append(tok)
        return tokens

    @staticmethod
    def _split_camel(text: str) -> List[str]:
        tokens = []
        for part in re.split(r"[.\s/_\-:(){}\[\],;]+", text):
            if not part:
                continue
            for cp in re.findall(r"[A-Z][a-z]*|[a-z]+|[0-9]+", part):
                tokens.append(cp.lower())
        return tokens

    def _build_idf(self, texts: List[str]) -> dict:
        n = len(texts)
        df = {}
        for text in texts:
            for tok in set(self._tokenize(text)):
                df[tok] = df.get(tok, 0) + 1
        return {tok: math.log((n + 1) / (d + 1)) + 1.0 for tok, d in df.items()}

    def _keyword_score(self, query_tokens: List[str], rule_text: str) -> float:
        if not query_tokens:
            return 0.0
        rule_tokens = set(self._tokenize(rule_text))
        overlap = [t for t in query_tokens if t in rule_tokens]
        num = sum(self._idf.get(t, 0.0) for t in overlap)
        den = sum(self._idf.get(t, 0.0) for t in query_tokens)
        return num / den if den > 0 else 0.0

    @staticmethod
    def compute_adaptive_top_k(attempt: int, current_codes: List[str], prev_codes: List[str], current_count: int, prev_count: int) -> int:
        """Compute adaptive top_k based on error dynamics."""
        base = {1: 10, 2: 7, 3: 5}.get(attempt, 4)
        if attempt == 1:
            return base

        curr_set = set(current_codes or [])
        prev_set = set(prev_codes or [])
        new_codes = curr_set - prev_set
        fixed_codes = prev_set - curr_set
        persistent = curr_set & prev_set
        adj = 0

        if prev_count > 0 and current_count < prev_count * 0.6:
            adj += 1
        if persistent and not new_codes and not fixed_codes:
            adj -= 2
        if len(new_codes) >= 2:
            adj += 2
        if len(curr_set) == 1:
            adj -= 1
        if len(curr_set) >= 4:
            adj += 1

        return max(3, min(12, base + adj))
