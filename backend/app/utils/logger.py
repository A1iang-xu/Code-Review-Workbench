"""
结构化日志

提供 StructuredFormatter 和 setup_logging() 函数。
日志以 JSON 格式输出到 stdout，便于 ELK/Loki 采集。
"""

import json
import logging
import sys
from datetime import datetime, timezone
from typing import Any

from app.config import get_settings

settings = get_settings()


# ----------------------------------------------------------------
# StructuredFormatter
# ----------------------------------------------------------------

class StructuredFormatter(logging.Formatter):
    """JSON-structured log formatter.

    Each log line is a JSON object with fields:
    - timestamp: ISO 8601 UTC
    - level: log level (INFO, WARNING, ERROR, DEBUG)
    - logger: logger name
    - message: log message
    - module: source module name
    - function: source function name
    - line: source line number

    Extra fields (passed via 'extra' dict) are merged into the JSON object:
    - task_id, agent_type, skill_name, duration_ms, tokens_used
    """

    def format(self, record: logging.LogRecord) -> str:
        log_entry: dict[str, Any] = {
            "timestamp": datetime.fromtimestamp(
                record.created, tz=timezone.utc
            ).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "module": record.module,
            "function": record.funcName,
            "line": record.lineno,
        }

        # Merge extra fields
        extra_fields = {
            "task_id": "task_id",
            "agent_type": "agent_type",
            "skill_name": "skill_name",
            "duration_ms": "duration_ms",
            "tokens_used": "tokens_used",
        }
        for json_key, attr_name in extra_fields.items():
            if hasattr(record, attr_name):
                log_entry[json_key] = getattr(record, attr_name)

        # Include exception info if present
        if record.exc_info and record.exc_info[0]:
            log_entry["exception"] = self.formatException(record.exc_info)

        return json.dumps(log_entry, ensure_ascii=False, default=str)


# ----------------------------------------------------------------
# Setup
# ----------------------------------------------------------------

def setup_logging(level: int | str | None = None) -> None:
    """Configure structured JSON logging.

    - Creates a StreamHandler (stdout) with StructuredFormatter
    - Sets third-party library log levels (httpx → WARNING, httpcore → WARNING)

    Args:
        level: Log level (default: INFO in production, DEBUG in development).
    """
    if level is None:
        level = logging.DEBUG if settings.APP_DEBUG else logging.INFO

    if isinstance(level, str):
        level = getattr(logging, level.upper(), logging.INFO)

    # Root logger
    root = logging.getLogger()
    root.setLevel(level)

    # Remove existing handlers
    root.handlers.clear()

    # Add structured handler
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(StructuredFormatter())
    handler.setLevel(level)
    root.addHandler(handler)

    # Quiet third-party loggers
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    logging.getLogger("asyncio").setLevel(logging.WARNING)
    logging.getLogger("opentelemetry").setLevel(logging.WARNING)

    # App logger
    logger = logging.getLogger("crw")
    logger.setLevel(level)

    logger.info("结构化日志已配置", extra={"level": logging.getLevelName(level)})


# ----------------------------------------------------------------
# Logger adapter for structured extra fields
# ----------------------------------------------------------------

class StructuredLogger(logging.LoggerAdapter):
    """Logger adapter that supports structured extra fields.

    Usage:
        logger = get_logger("orchestrator")
        logger.info("Review started", extra={"task_id": "abc123"})
    """

    def process(self, msg: str, kwargs: dict[str, Any]) -> tuple[str, dict[str, Any]]:
        extra = kwargs.pop("extra", {})
        if "extra" in kwargs:
            merged = kwargs.pop("extra", {})
            if isinstance(merged, dict):
                extra.update(merged)

        kwargs["extra"] = extra
        return msg, kwargs


def get_logger(name: str) -> StructuredLogger:
    """Get a structured logger for the given module.

    Args:
        name: Logger name (typically __name__).

    Returns:
        StructuredLogger instance.
    """
    logger = logging.getLogger(name)
    return StructuredLogger(logger, {})
