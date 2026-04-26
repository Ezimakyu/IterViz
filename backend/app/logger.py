"""Structured logging with optional DEBUG mode.

Usage:
    from app.logger import get_logger
    log = get_logger(__name__)
    log.info("event", extra={"key": "value"})

Set ``DEBUG=1`` in the environment to enable verbose debug-level logging.
"""

from __future__ import annotations

import json
import logging
import os
import sys
from typing import Any

_CONFIGURED = False


class JsonFormatter(logging.Formatter):
    """Render each record as a single JSON line for easy parsing."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        if record.exc_info:
            payload["exc_info"] = self.formatException(record.exc_info)

        # Attach any structured fields passed via ``extra=...``.
        skip = {
            "args", "asctime", "created", "exc_info", "exc_text", "filename",
            "funcName", "levelname", "levelno", "lineno", "message", "module",
            "msecs", "msg", "name", "pathname", "process", "processName",
            "relativeCreated", "stack_info", "thread", "threadName",
            "taskName",
        }
        for key, value in record.__dict__.items():
            if key in skip or key.startswith("_"):
                continue
            try:
                json.dumps(value)
                payload[key] = value
            except (TypeError, ValueError):
                payload[key] = repr(value)

        return json.dumps(payload, default=str)


def _configure_root() -> None:
    global _CONFIGURED
    if _CONFIGURED:
        return

    debug = os.environ.get("DEBUG", "0") not in ("", "0", "false", "False")
    level = logging.DEBUG if debug else logging.INFO

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())

    root = logging.getLogger("glasshouse")
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(level)
    root.propagate = False

    _CONFIGURED = True


def get_logger(name: str) -> logging.Logger:
    """Return a configured logger under the ``glasshouse`` namespace."""
    _configure_root()
    if not name.startswith("glasshouse"):
        name = f"glasshouse.{name}"
    return logging.getLogger(name)


def is_debug() -> bool:
    return os.environ.get("DEBUG", "0") not in ("", "0", "false", "False")
