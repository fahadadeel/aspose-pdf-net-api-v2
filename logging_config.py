"""
logging_config.py -- Structured JSON logging for the service.

Replaces the ad-hoc ``print()`` calls scattered across the service code
path. Log records are emitted as one JSON object per line, suitable for
ingestion by Loki / Datadog / CloudWatch Logs Insights / etc. without
extra regex work.

Setup:
    from logging_config import setup_logging, get_logger
    setup_logging()
    logger = get_logger(__name__)
    logger.info("started", extra={"job_id": job_id})

Configuration:
    LOG_LEVEL env var (DEBUG / INFO / WARNING / ERROR / CRITICAL).
    Defaults to INFO.

CLI tools (``cli.py``, ``scripts/*.py``) intentionally keep using
``print()`` — they speak to humans on stdout. Service code goes
through this module.
"""

from __future__ import annotations

import json
import logging
import os
import sys
from datetime import datetime, timezone

# Standard LogRecord attributes — anything not in this set is treated as
# caller-supplied context (via the ``extra=`` kwarg) and surfaced in the
# JSON output.
_STANDARD_LOGRECORD_ATTRS = frozenset({
    "name", "msg", "args", "levelname", "levelno", "pathname", "filename",
    "module", "exc_info", "exc_text", "stack_info", "lineno", "funcName",
    "created", "msecs", "relativeCreated", "thread", "threadName",
    "processName", "process", "message", "taskName",
})


class JsonFormatter(logging.Formatter):
    """One JSON object per log line.

    Standard keys (always present): ``timestamp``, ``level``, ``logger``,
    ``message``. ``exception`` is added when the record carries traceback
    info. Any caller-supplied ``extra={"key": value}`` keys are merged
    in at the top level.
    """

    def format(self, record: logging.LogRecord) -> str:
        payload: dict = {
            "timestamp": datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        # Merge extras
        for key, value in record.__dict__.items():
            if key in _STANDARD_LOGRECORD_ATTRS or key.startswith("_"):
                continue
            try:
                json.dumps(value)
                payload[key] = value
            except (TypeError, ValueError):
                payload[key] = repr(value)
        if record.exc_info and record.exc_info[0]:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)


def setup_logging(level: str | None = None) -> None:
    """Install a JSON-formatted handler on the root logger.

    Idempotent: calling twice doesn't add a second handler.
    """
    resolved = (level or os.getenv("LOG_LEVEL", "INFO")).upper()
    numeric_level = getattr(logging, resolved, logging.INFO)
    root = logging.getLogger()
    root.setLevel(numeric_level)

    # Replace any existing handlers so we don't double-emit if Uvicorn
    # has already installed its plain-text formatter.
    if root.handlers:
        for h in list(root.handlers):
            root.removeHandler(h)

    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(JsonFormatter())
    handler.setLevel(numeric_level)
    root.addHandler(handler)


def get_logger(name: str) -> logging.Logger:
    """Return a named logger for the calling module.

    Convention: pass ``__name__`` so log records inherit the module
    hierarchy. Configure logger levels via standard ``logging`` calls
    if you need to override the root level for a specific subsystem.
    """
    return logging.getLogger(name)
