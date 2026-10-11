"""Configure stderr logging and attach the current request's identity."""

from __future__ import annotations

import json
import logging
from contextvars import ContextVar
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from logging import LogRecord
    from typing import TextIO

    _StreamHandler = logging.StreamHandler[TextIO]
else:
    # StreamHandler is generic in typeshed, but not subscriptable at runtime.
    _StreamHandler = logging.StreamHandler

request_id_var: ContextVar[str | None] = ContextVar("request_id", default=None)


class RequestIdFilter(logging.Filter):
    """Attach identity before a record propagates to other handlers."""

    def filter(self, record: LogRecord) -> bool:
        """Populate every application record, including child loggers."""
        record.request_id = request_id_var.get()
        return True


class JsonFormatter(logging.Formatter):
    """Write one object per line without arbitrary extra fields."""

    def format(self, record: LogRecord) -> str:
        """Include the agreed access fields and exception traceback."""
        data: dict[str, object] = {
            "timestamp": datetime.fromtimestamp(record.created, UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "request_id": getattr(record, "request_id", None),
        }
        for name in ("method", "path", "status", "duration_ms", "exception_type"):
            if hasattr(record, name):
                data[name] = getattr(record, name)
        if record.exc_info:
            data["exception"] = self.formatException(record.exc_info)
        return json.dumps(data, ensure_ascii=False)


class _AppHandler(_StreamHandler):
    """Identify only the handler this configuration owns."""


def configure_logging(level: str, fmt: Literal["text", "json"]) -> None:
    """Replace our stderr handler without taking ownership of other logging."""
    logger = logging.getLogger("my_app")
    for handler in tuple(logger.handlers):
        if isinstance(handler, _AppHandler):
            logger.removeHandler(handler)
            handler.close()
    handler = _AppHandler()
    handler.addFilter(RequestIdFilter())
    handler.setFormatter(
        JsonFormatter()
        if fmt == "json"
        else logging.Formatter(
            "%(asctime)s %(levelname)s %(name)s [%(request_id)s] %(message)s"
        )
    )
    # This handler always accepts the logger's enabled records. Enrich before
    # preserved handlers format them, while retaining those handlers' order.
    logger.handlers.insert(0, handler)
    logger.setLevel(level)
    logger.propagate = True
