"""Structured JSON logging with optional DEBUG mode.

Usage:
    from app.logger import get_logger
    log = get_logger(__name__)
    log.info("session created", extra={"session_id": sid})

Environment variables:
    DEBUG=1   -- emit DEBUG-level records (default: INFO).

Every record is serialized as a single line of JSON so downstream tools
(jq, logstash, datadog) can parse without regex gymnastics.
"""

from __future__ import annotations

import json
import logging
import os
import sys
from datetime import datetime, timezone
from typing import Any

DEBUG_MODE: bool = os.getenv("DEBUG", "0") == "1"

# Standard LogRecord attributes we should not duplicate as extras.
_RESERVED_ATTRS = {
    "args", "asctime", "created", "exc_info", "exc_text", "filename",
    "funcName", "levelname", "levelno", "lineno", "message", "module",
    "msecs", "msg", "name", "pathname", "process", "processName",
    "relativeCreated", "stack_info", "thread", "threadName", "taskName",
}


class StructuredFormatter(logging.Formatter):
    """Format LogRecords as a single JSON object per line."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "module": record.name,
            "message": record.getMessage(),
        }

        # Promote any user-supplied extras to top-level keys.
        for key, value in record.__dict__.items():
            if key in _RESERVED_ATTRS or key.startswith("_"):
                continue
            if key == "extra" and isinstance(value, dict):
                payload.update(value)
                continue
            payload[key] = value

        if record.exc_info:
            payload["exc_info"] = self.formatException(record.exc_info)

        return json.dumps(payload, default=str, sort_keys=False)


def get_logger(name: str) -> logging.Logger:
    """Return a logger configured with the structured JSON formatter.

    Idempotent: subsequent calls for the same name reuse the existing handler.
    """
    logger = logging.getLogger(name)
    level = logging.DEBUG if DEBUG_MODE else logging.INFO
    logger.setLevel(level)

    # Avoid duplicate handlers when called multiple times (e.g., re-imports).
    if not any(getattr(h, "_glasshouse_handler", False) for h in logger.handlers):
        handler = logging.StreamHandler(stream=sys.stderr)
        handler.setFormatter(StructuredFormatter())
        handler.setLevel(level)
        handler._glasshouse_handler = True  # type: ignore[attr-defined]
        logger.addHandler(handler)

    # Don't bubble to the root logger -- it would double-print.
    logger.propagate = False
    return logger
