"""Structured logging configuration for storebot.

JSON format for production (machine-readable, journalctl friendly).
Human-readable format for local development.
"""

import json
import logging
from datetime import UTC, datetime

EXTRA_FIELDS = ("chat_id", "order_id", "listing_id", "tool_name", "job_name")


class JSONFormatter(logging.Formatter):
    """Formats log records as single-line JSON objects."""

    def format(self, record: logging.LogRecord) -> str:
        log_entry = {
            "timestamp": datetime.fromtimestamp(record.created, tz=UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }

        if record.exc_info and record.exc_info[0] is not None:
            log_entry["exception"] = self.formatException(record.exc_info)

        for field in EXTRA_FIELDS:
            value = getattr(record, field, None)
            if value is not None:
                log_entry[field] = value

        return json.dumps(log_entry, ensure_ascii=False)


def configure_logging(level: str = "INFO", json_format: bool = True) -> None:
    """Configure root logger with either JSON or human-readable format.

    Args:
        level: Log level name (DEBUG, INFO, WARNING, ERROR, CRITICAL).
        json_format: If True, use JSON format. If False, use human-readable format.
    """
    root = logging.getLogger()
    root.setLevel(getattr(logging, level.upper(), logging.INFO))

    # Remove existing handlers to avoid duplicates
    root.handlers.clear()

    handler = logging.StreamHandler()
    if json_format:
        handler.setFormatter(JSONFormatter())
    else:
        handler.setFormatter(
            logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")
        )
    root.addHandler(handler)
