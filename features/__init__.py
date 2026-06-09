"""
features — feature flag mechanism.

Single source of truth: resources/feature_flags.json declares every
boolean toggle the pipeline understands, with description, owner,
default, and env var name.

Resolution order at runtime (see also the `_resolution_order` field
in the registry JSON):

  1. Env var override (if `env_var` is set on the flag and the var
     is defined). Truthy values: "true", "1", "yes" (case-insensitive).
  2. Registry default.
  3. Caller-provided fallback in `is_enabled(name, default=...)`.

Adding a new flag:
  1. Add an entry to resources/feature_flags.json with owner + default
  2. Reference it from code via `features.is_enabled("name")`
  3. Document why in the description field

Reading the registry is cheap — values are cached for the lifetime
of the process. Call `refresh()` from tests when seeding new values.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Optional

_REGISTRY_PATH = Path(__file__).resolve().parent.parent / "resources" / "feature_flags.json"

_registry_cache: Optional[dict] = None


def _load_registry() -> dict:
    """Read and parse the registry file. Cached after first call."""
    global _registry_cache
    if _registry_cache is None:
        with _REGISTRY_PATH.open(encoding="utf-8") as fh:
            data = json.load(fh)
        _registry_cache = data.get("flags", {})
    return _registry_cache


def refresh() -> None:
    """Clear the in-memory cache. Use in tests or after live-editing the registry."""
    global _registry_cache
    _registry_cache = None


def is_enabled(name: str, default: Optional[bool] = None) -> bool:
    """Return True if the named flag is enabled.

    Raises KeyError if the flag is not declared in the registry and
    no fallback `default` is provided — declaring flags up front is
    the whole point of having a registry.
    """
    registry = _load_registry()
    flag = registry.get(name)

    if flag is None:
        if default is None:
            raise KeyError(
                f"Unknown feature flag: {name!r}. "
                f"Declare it in resources/feature_flags.json first."
            )
        return default

    env_var = flag.get("env_var")
    if env_var:
        raw = os.environ.get(env_var)
        if raw is not None:
            return raw.strip().lower() in ("true", "1", "yes")

    return bool(flag.get("default", default if default is not None else False))


def get_flag(name: str) -> Optional[dict]:
    """Return the registry entry for a flag, or None if undeclared."""
    return _load_registry().get(name)


def list_flags() -> dict:
    """Return a copy of the full registry."""
    return dict(_load_registry())


def snapshot() -> dict:
    """Return a {flag: bool} snapshot of all declared flags with their
    currently-resolved values. Useful for the /api/feature-flags
    endpoint and for diagnostics in CI logs.
    """
    return {name: is_enabled(name) for name in _load_registry()}
