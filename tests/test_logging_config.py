"""Unit tests for logging_config.py."""

import io
import json
import logging

import pytest

import logging_config


# ── Test isolation ──────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def reset_root_logger():
    """Clear handlers between tests so each test starts clean."""
    root = logging.getLogger()
    saved = list(root.handlers)
    saved_level = root.level
    for h in list(root.handlers):
        root.removeHandler(h)
    yield
    for h in list(root.handlers):
        root.removeHandler(h)
    for h in saved:
        root.addHandler(h)
    root.setLevel(saved_level)


def _capture_handler():
    """Return a StreamHandler writing to an in-memory buffer + JsonFormatter."""
    buf = io.StringIO()
    h = logging.StreamHandler(buf)
    h.setFormatter(logging_config.JsonFormatter())
    return h, buf


# ── setup_logging ───────────────────────────────────────────────────────────

def test_setup_installs_handler():
    logging_config.setup_logging()
    root = logging.getLogger()
    assert len(root.handlers) == 1


def test_setup_is_idempotent():
    logging_config.setup_logging()
    logging_config.setup_logging()
    root = logging.getLogger()
    assert len(root.handlers) == 1


def test_setup_honors_explicit_level():
    logging_config.setup_logging(level="DEBUG")
    assert logging.getLogger().level == logging.DEBUG


def test_setup_honors_env_level(monkeypatch):
    monkeypatch.setenv("LOG_LEVEL", "ERROR")
    logging_config.setup_logging()
    assert logging.getLogger().level == logging.ERROR


def test_setup_unknown_level_falls_back_to_info():
    logging_config.setup_logging(level="GARBAGE")
    assert logging.getLogger().level == logging.INFO


# ── JsonFormatter ───────────────────────────────────────────────────────────

def test_format_emits_standard_keys():
    h, buf = _capture_handler()
    logger = logging.getLogger("test.standard")
    logger.addHandler(h)
    logger.setLevel(logging.INFO)
    logger.info("hello world")

    line = buf.getvalue().strip()
    record = json.loads(line)
    assert record["level"] == "INFO"
    assert record["logger"] == "test.standard"
    assert record["message"] == "hello world"
    assert "timestamp" in record
    assert record["timestamp"].endswith("Z")


def test_format_includes_extras():
    h, buf = _capture_handler()
    logger = logging.getLogger("test.extras")
    logger.addHandler(h)
    logger.setLevel(logging.INFO)
    logger.info("event", extra={"job_id": "abc-123", "stage": "baseline"})

    record = json.loads(buf.getvalue().strip())
    assert record["job_id"] == "abc-123"
    assert record["stage"] == "baseline"


def test_format_handles_exception():
    h, buf = _capture_handler()
    logger = logging.getLogger("test.exc")
    logger.addHandler(h)
    logger.setLevel(logging.ERROR)
    try:
        raise ValueError("boom")
    except ValueError:
        logger.exception("failed")

    record = json.loads(buf.getvalue().strip())
    assert record["level"] == "ERROR"
    assert "exception" in record
    assert "ValueError" in record["exception"]
    assert "boom" in record["exception"]


def test_format_skips_standard_logrecord_attrs():
    """Standard LogRecord attributes like 'pathname' should not leak into the JSON."""
    h, buf = _capture_handler()
    logger = logging.getLogger("test.no_leak")
    logger.addHandler(h)
    logger.setLevel(logging.INFO)
    logger.info("event")

    record = json.loads(buf.getvalue().strip())
    for leaked_key in ("pathname", "filename", "module", "lineno", "funcName"):
        assert leaked_key not in record, f"unexpected standard attr leaked: {leaked_key}"


def test_format_repr_falls_back_on_non_serializable():
    h, buf = _capture_handler()
    logger = logging.getLogger("test.non_serial")
    logger.addHandler(h)
    logger.setLevel(logging.INFO)

    class Weird:
        def __repr__(self):
            return "<Weird>"

    logger.info("event", extra={"weird": Weird()})
    record = json.loads(buf.getvalue().strip())
    assert record["weird"] == "<Weird>"


def test_format_per_line_is_valid_json():
    h, buf = _capture_handler()
    logger = logging.getLogger("test.per_line")
    logger.addHandler(h)
    logger.setLevel(logging.INFO)
    for i in range(5):
        logger.info("event", extra={"i": i})

    lines = buf.getvalue().strip().splitlines()
    assert len(lines) == 5
    for line in lines:
        record = json.loads(line)
        assert "timestamp" in record


# ── get_logger ──────────────────────────────────────────────────────────────

def test_get_logger_returns_named_logger():
    log = logging_config.get_logger("knowledge.auto_learner")
    assert log.name == "knowledge.auto_learner"


def test_get_logger_returns_same_instance_on_repeat_call():
    a = logging_config.get_logger("dup.test")
    b = logging_config.get_logger("dup.test")
    assert a is b
