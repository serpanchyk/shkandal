"""Structured JSON logging helpers."""

import contextvars
import logging
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from typing import Any

from pythonjsonlogger import json as jsonlogger

trace_id_var: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "trace_id",
    default=None,
)
session_id_var: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "session_id",
    default=None,
)
user_id_var: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "user_id",
    default=None,
)


@contextmanager
def bind_log_context(
    *,
    trace_id: str | None = None,
    session_id: str | None = None,
    user_id: str | None = None,
) -> Iterator[None]:
    """Bind contextual fields for logs emitted inside the context."""

    trace_token = trace_id_var.set(trace_id)
    session_token = session_id_var.set(session_id)
    user_token = user_id_var.set(user_id)
    try:
        yield
    finally:
        trace_id_var.reset(trace_token)
        session_id_var.reset(session_token)
        user_id_var.reset(user_token)


class ContextualJsonFormatter(jsonlogger.JsonFormatter):
    """JSON formatter that adds common Shkandal context fields."""

    def add_fields(
        self,
        log_record: dict[str, Any],
        record: logging.LogRecord,
        message_dict: dict[str, Any],
    ) -> None:
        super().add_fields(log_record, record, message_dict)
        if not log_record.get("timestamp"):
            log_record["timestamp"] = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
        if not log_record.get("name"):
            log_record["name"] = record.name
        log_record["level"] = record.levelname
        log_record["trace_id"] = trace_id_var.get()
        log_record["session_id"] = session_id_var.get()
        log_record["user_id"] = user_id_var.get()


def setup_logger(service_name: str) -> logging.Logger:
    """Create a service logger configured for structured JSON output."""

    logger = logging.getLogger(service_name)
    logger.setLevel(logging.INFO)
    logger.handlers.clear()

    handler = logging.StreamHandler()
    handler.setFormatter(ContextualJsonFormatter())
    logger.addHandler(handler)
    logger.propagate = False
    return logger
