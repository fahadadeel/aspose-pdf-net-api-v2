"""Tests for the feature flag mechanism (features/__init__.py)."""

import os

import pytest

import features


@pytest.fixture(autouse=True)
def reset_cache():
    features.refresh()
    yield
    features.refresh()


# ── Registry loading ────────────────────────────────────────────────────────

def test_registry_loads_all_declared_flags():
    flags = features.list_flags()
    assert "use_own_llm" in flags
    assert "auto_learn_on_success" in flags
    assert "auto_learn_catalog" in flags
    assert len(flags) >= 7  # at least the seven pipeline gates


def test_each_registry_entry_has_required_fields():
    for name, entry in features.list_flags().items():
        for field in ("description", "owner", "default", "env_var", "added"):
            assert field in entry, f"flag {name!r} missing field {field!r}"
        assert isinstance(entry["default"], bool), f"{name}: default must be bool"


# ── is_enabled resolution order ─────────────────────────────────────────────

def test_is_enabled_uses_registry_default(monkeypatch):
    monkeypatch.delenv("USE_OWN_LLM", raising=False)
    features.refresh()
    # use_own_llm has default true in the registry
    assert features.is_enabled("use_own_llm") is True


def test_is_enabled_env_var_overrides_default_true(monkeypatch):
    monkeypatch.setenv("USE_OWN_LLM", "false")
    features.refresh()
    assert features.is_enabled("use_own_llm") is False


def test_is_enabled_env_var_overrides_default_false(monkeypatch):
    monkeypatch.setenv("DECOMPOSE_ON_LLM_FAIL", "true")
    features.refresh()
    assert features.is_enabled("decompose_on_llm_fail") is True


def test_env_var_truthy_variants(monkeypatch):
    for raw in ("true", "TRUE", "True", "1", "yes", "YES"):
        monkeypatch.setenv("USE_OWN_LLM", raw)
        features.refresh()
        assert features.is_enabled("use_own_llm") is True, f"failed for {raw!r}"


def test_env_var_falsy_variants(monkeypatch):
    for raw in ("false", "FALSE", "0", "no", "off", ""):
        monkeypatch.setenv("USE_OWN_LLM", raw)
        features.refresh()
        assert features.is_enabled("use_own_llm") is False, f"failed for {raw!r}"


# ── Unknown flag handling ───────────────────────────────────────────────────

def test_unknown_flag_with_default_returns_default():
    assert features.is_enabled("not_declared", default=True) is True
    assert features.is_enabled("not_declared", default=False) is False


def test_unknown_flag_without_default_raises():
    with pytest.raises(KeyError, match="not_declared"):
        features.is_enabled("not_declared")


# ── get_flag / snapshot ─────────────────────────────────────────────────────

def test_get_flag_returns_entry():
    entry = features.get_flag("use_own_llm")
    assert entry is not None
    assert entry["env_var"] == "USE_OWN_LLM"
    assert entry["scope"] == "pipeline"


def test_get_flag_unknown_returns_none():
    assert features.get_flag("not_declared") is None


def test_snapshot_returns_bool_per_flag():
    snap = features.snapshot()
    for name in features.list_flags():
        assert name in snap
        assert isinstance(snap[name], bool)


# ── Cache behaviour ─────────────────────────────────────────────────────────

def test_refresh_reloads_registry(monkeypatch):
    # First load
    flags1 = features.list_flags()
    # Mutate cache via refresh and reload
    features.refresh()
    flags2 = features.list_flags()
    assert flags1 == flags2  # same content
    assert flags1 is not flags2  # but a fresh dict (cache rebuilt)
