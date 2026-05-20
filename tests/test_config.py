"""Tests for config.py — configuration loading and env overrides."""

import os
import pytest


def test_defaults_load_without_env(monkeypatch):
    # Clear any env vars that would override defaults
    for key in ["BUILD_TFM", "NUGET_VERSION", "LLM_FIX_ATTEMPTS", "RESUME_BATCH"]:
        monkeypatch.delenv(key, raising=False)

    from config import AppConfig
    cfg = AppConfig()

    assert cfg.build.tfm == "net10.0"
    assert cfg.pipeline.llm_fix_attempts == 3
    assert cfg.pipeline.regen_attempts == 3
    assert cfg.dotnet.build_timeout == 30


def test_env_vars_override_defaults(monkeypatch):
    monkeypatch.setenv("BUILD_TFM", "net9.0")
    monkeypatch.setenv("NUGET_VERSION", "26.5.0")
    monkeypatch.setenv("LLM_FIX_ATTEMPTS", "5")
    monkeypatch.setenv("RESUME_BATCH", "false")

    from config import load_config
    cfg = load_config()

    assert cfg.build.tfm == "net9.0"
    assert cfg.build.nuget_version == "26.5.0"
    assert cfg.pipeline.llm_fix_attempts == 5
    assert cfg.resume_batch is False
