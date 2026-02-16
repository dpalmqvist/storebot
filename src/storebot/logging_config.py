"""Structured logging configuration for storebot.

JSON format for production (machine-readable, journalctl friendly).
Human-readable format for local development.
"""

import json
import logging
from datetime import UTC, datetime
from decimal import Decimal
from logging.handlers import RotatingFileHandler
from pathlib import Path

EXTRA_FIELDS = ("chat_id", "order_id", "listing_id", "tool_name", "job_name")


def _json_default(o: object) -> object:
    """JSON encoder fallback — converts Decimal (from zeep SOAP) to float."""
    if isinstance(o, Decimal):
        return float(o)
    raise TypeError(f"Object of type {type(o).__name__} is not JSON serializable")


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

        return json.dumps(log_entry, ensure_ascii=False, default=_json_default)


def configure_logging(level: str = "INFO", json_format: bool = True, log_file: str = "") -> None:
    """Configure root logger with either JSON or human-readable format.

    Args:
        level: Log level name (DEBUG, INFO, WARNING, ERROR, CRITICAL).
        json_format: If True, use JSON format. If False, use human-readable format.
        log_file: Optional file path. When set, adds a RotatingFileHandler
                  (10 MB max, 3 backups) alongside the stream handler.
    """
    root = logging.getLogger()
    root.setLevel(getattr(logging, level.upper(), logging.INFO))

    # Remove existing handlers to avoid duplicates
    root.handlers.clear()

    if json_format:
        formatter = JSONFormatter()
    else:
        formatter = logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")

    stream_handler = logging.StreamHandler()
    stream_handler.setFormatter(formatter)
    root.addHandler(stream_handler)

    if log_file:
        Path(log_file).parent.mkdir(parents=True, exist_ok=True)
        file_handler = RotatingFileHandler(log_file, maxBytes=10 * 1024 * 1024, backupCount=3)
        file_handler.setFormatter(formatter)
        root.addHandler(file_handler)
