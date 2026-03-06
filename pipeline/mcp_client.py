"""
pipeline/mcp_client.py — MCP API client for code generation and retrieval.
"""

import os
from typing import List, Optional

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from config import AppConfig


class MCPClient:
    """HTTP client for MCP /generate and /retrieve endpoints."""

    def __init__(self, config: AppConfig):
        self.config = config
        self._session = requests.Session()
        retry = Retry(total=2, backoff_factor=0.5, status_forcelist=[502, 503, 504])
        adapter = HTTPAdapter(max_retries=retry, pool_connections=4, pool_maxsize=4)
        self._session.mount("http://", adapter)
        self._session.mount("https://", adapter)

    def generate(
        self,
        task: str,
        category: str = "",
        product: str = None,
        platform: str = None,
        retrieval_mode: str = None,
        limit: int = None,
        exclude_namespaces: list = None,
    ) -> Optional[str]:
        """Call /mcp/generate and return generated code or None."""
        cfg = self.config.mcp

        # Facade handling: adjust namespaces and task text
        cat_lower = (category or "").lower()
        if "facades" in cat_lower or "facades" in task.lower():
            ns = ["Aspose.Pdf.Plugins"]
            task_req = task + " use Aspose.Pdf.Facades"
        else:
            ns = exclude_namespaces or list(cfg.exclude_namespaces)
            task_req = task

        # Always use config product/platform for MCP — the task-level
        # "product" (e.g. "aspose.pdf") is a display name, not the MCP key.
        payload = {
            "task": task_req,
            "product": cfg.product,
            "platform": cfg.platform,
            "retrieval_mode": retrieval_mode or cfg.retrieval_mode,
            "exclude_namespaces": ns,
            "limit": limit or cfg.retrieval_limit,
        }

        try:
            resp = self._session.post(cfg.generate_url, json=payload, timeout=cfg.timeout)
            resp.raise_for_status()
            data = resp.json()
            # Look for code in common response fields
            return data.get("code") or data.get("example") or data.get("content") or data.get("program_cs") or data.get("generated_code")
        except Exception as e:
            print(f"MCP generate error: {e}")
            return None

    def retrieve(
        self,
        task: str,
        retrieval_mode: str = None,
        limit: int = None,
        exclude_namespaces: list = None,
    ) -> List[dict]:
        """Call /mcp/retrieve and return list of chunks."""
        cfg = self.config.mcp
        retrieve_url = cfg.retrieve_url

        # Always use config product/platform (same fix as generate)
        payload = {
            "task": task,
            "product": cfg.product,
            "platform": cfg.platform,
            "retrieval_mode": retrieval_mode or cfg.retrieval_mode,
            "limit": limit or self.config.pipeline.retrieve_limit,
            "exclude_namespaces": exclude_namespaces or list(cfg.exclude_namespaces),
        }

        try:
            resp = self._session.post(retrieve_url, json=payload, timeout=cfg.timeout)
            resp.raise_for_status()
            data = resp.json()
            return data.get("chunks", [])
        except Exception as e:
            print(f"MCP retrieve error: {e}")
            return []

    @staticmethod
    def format_chunks(chunks: List[dict], max_chars: int = 12000) -> str:
        """Format retrieved chunks into text for prompt injection."""
        if not chunks:
            return ""
        parts = ["=== Retrieved API Documentation ==="]
        total = 0
        for chunk in chunks:
            ns = chunk.get("namespace", "")
            tn = chunk.get("type_name", "")
            mk = chunk.get("member_kind", "")
            text = chunk.get("text", "")
            header = f"\n[{ns}.{tn} ({mk})]" if ns else f"\n[{tn}]"
            entry = f"{header}\n{text}"
            if total + len(entry) > max_chars:
                break
            parts.append(entry)
            total += len(entry)
        return "\n".join(parts)
