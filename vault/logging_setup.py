"""Structured logging that can never carry document content.

Every log line is one JSON object with a fixed, whitelisted set of fields:
timestamp, level, stage, doc_id, status, duration_ms, error_class. There is
no field for free-text messages, so a call site cannot accidentally log a
filename, an extracted sentence, or an LLM prompt/response - it simply has
nowhere to put one.
"""
from __future__ import annotations

import json
import logging
import time
from pathlib import Path

_LOGGER_NAME = "vault"


def setup_logging(log_dir: str | Path, level: int = logging.INFO) -> logging.Logger:
    log_dir = Path(log_dir).expanduser()
    log_dir.mkdir(parents=True, exist_ok=True)

    logger = logging.getLogger(_LOGGER_NAME)
    logger.setLevel(level)
    logger.propagate = False
    if logger.handlers:
        return logger

    handler = logging.FileHandler(log_dir / "vault.log")
    handler.setFormatter(_JsonFormatter())
    logger.addHandler(handler)
    return logger


class _JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(record.created)),
            "level": record.levelname,
            "stage": getattr(record, "stage", record.name),
        }
        for key in ("doc_id", "status", "duration_ms", "error_class"):
            val = getattr(record, key, None)
            if val is not None:
                payload[key] = val
        return json.dumps(payload, sort_keys=True)


def log_event(
    logger: logging.Logger,
    stage: str,
    *,
    doc_id: str | None = None,
    status: str | None = None,
    duration_ms: float | None = None,
    error: BaseException | None = None,
    level: int = logging.INFO,
) -> None:
    """The only sanctioned way to write a vault log line.

    `error`, when given, is reduced to its class name - never str(error),
    which could echo a path or a bit of parsed document content.
    """
    extra = {"stage": stage}
    if doc_id is not None:
        extra["doc_id"] = doc_id
    if status is not None:
        extra["status"] = status
    if duration_ms is not None:
        extra["duration_ms"] = round(duration_ms, 1)
    if error is not None:
        extra["error_class"] = type(error).__name__
        level = max(level, logging.ERROR)
    logger.log(level, stage, extra=extra)
