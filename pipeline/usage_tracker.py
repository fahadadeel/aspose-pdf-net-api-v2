"""
pipeline/usage_tracker.py — Thread-safe usage counters for a single job run.

Tracks LLM token usage and API call counts. Passed into LLMClient and MCPClient
so they can report usage without any global state.
"""

import threading


class UsageTracker:
    """Accumulates token usage and API call counts for a single job."""

    def __init__(self):
        self._lock = threading.Lock()
        self._llm_tokens = 0
        self._llm_calls = 0
        self._mcp_generate_calls = 0
        self._mcp_retrieve_calls = 0

    def add_llm_usage(self, tokens: int):
        """Record tokens from one LLM chat() call."""
        with self._lock:
            self._llm_tokens += tokens
            self._llm_calls += 1

    def add_llm_call(self):
        """Record an LLM call that returned no usage data."""
        with self._lock:
            self._llm_calls += 1

    def add_mcp_generate(self):
        """Record one MCP generate call."""
        with self._lock:
            self._mcp_generate_calls += 1

    def add_mcp_retrieve(self):
        """Record one MCP retrieve call."""
        with self._lock:
            self._mcp_retrieve_calls += 1

    @property
    def total_tokens(self) -> int:
        with self._lock:
            return self._llm_tokens

    @property
    def total_api_calls(self) -> int:
        with self._lock:
            return self._llm_calls + self._mcp_generate_calls + self._mcp_retrieve_calls

    def snapshot(self) -> dict:
        """Return a point-in-time copy of all counters."""
        with self._lock:
            return {
                "llm_tokens": self._llm_tokens,
                "llm_calls": self._llm_calls,
                "mcp_generate_calls": self._mcp_generate_calls,
                "mcp_retrieve_calls": self._mcp_retrieve_calls,
                "total_api_calls": self._llm_calls + self._mcp_generate_calls + self._mcp_retrieve_calls,
            }
