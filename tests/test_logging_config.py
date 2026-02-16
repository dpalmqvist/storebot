import json
import logging
from logging.handlers import RotatingFileHandler

from storebot.logging_config import JSONFormatter, configure_logging
from storebot.db import init_db


class TestJSONFormatter:
    def test_basic_format(self):
        formatter = JSONFormatter()
        record = logging.LogRecord(
            name="storebot.test",
            level=logging.INFO,
            pathname="test.py",
            lineno=1,
            msg="hello world",
            args=(),
            exc_info=None,
        )

        output = formatter.format(record)
        data = json.loads(output)

        assert data["level"] == "INFO"
        assert data["logger"] == "storebot.test"
        assert data["message"] == "hello world"
        assert "timestamp" in data

    def test_extra_fields_included(self):
        formatter = JSONFormatter()
        record = logging.LogRecord(
            name="storebot.test",
            level=logging.INFO,
            pathname="test.py",
            lineno=1,
            msg="processing",
            args=(),
            exc_info=None,
        )
        record.chat_id = "12345"
        record.order_id = 42

        output = formatter.format(record)
        data = json.loads(output)

        assert data["chat_id"] == "12345"
        assert data["order_id"] == 42

    def test_extra_fields_absent_when_not_set(self):
        formatter = JSONFormatter()
        record = logging.LogRecord(
            name="storebot.test",
            level=logging.INFO,
            pathname="test.py",
            lineno=1,
            msg="no extras",
            args=(),
            exc_info=None,
        )

        output = formatter.format(record)
        data = json.loads(output)

        assert "chat_id" not in data
        assert "order_id" not in data

    def test_exception_included(self):
        formatter = JSONFormatter()
        try:
            raise ValueError("boom")
        except ValueError:
            import sys

            record = logging.LogRecord(
                name="storebot.test",
                level=logging.ERROR,
                pathname="test.py",
                lineno=1,
                msg="error occurred",
                args=(),
                exc_info=sys.exc_info(),
            )

        output = formatter.format(record)
        data = json.loads(output)

        assert "exception" in data
        assert "ValueError" in data["exception"]
        assert "boom" in data["exception"]

    def test_unicode_message(self):
        formatter = JSONFormatter()
        record = logging.LogRecord(
            name="storebot.test",
            level=logging.INFO,
            pathname="test.py",
            lineno=1,
            msg="Köpare: Åsa Öberg",
            args=(),
            exc_info=None,
        )

        output = formatter.format(record)
        data = json.loads(output)

        assert data["message"] == "Köpare: Åsa Öberg"


class TestConfigureLogging:
    def test_json_format(self):
        configure_logging(level="DEBUG", json_format=True)
        root = logging.getLogger()

        assert root.level == logging.DEBUG
        assert len(root.handlers) == 1
        assert isinstance(root.handlers[0].formatter, JSONFormatter)

    def test_human_readable_format(self):
        configure_logging(level="WARNING", json_format=False)
        root = logging.getLogger()

        assert root.level == logging.WARNING
        assert len(root.handlers) == 1
        assert not isinstance(root.handlers[0].formatter, JSONFormatter)

    def test_clears_existing_handlers(self):
        root = logging.getLogger()
        root.addHandler(logging.StreamHandler())
        root.addHandler(logging.StreamHandler())
        assert len(root.handlers) >= 2

        configure_logging(level="INFO", json_format=True)

        assert len(root.handlers) == 1

    def test_file_handler_added(self, tmp_path):
        log_file = str(tmp_path / "test.log")
        configure_logging(level="INFO", json_format=True, log_file=log_file)
        root = logging.getLogger()

        assert len(root.handlers) == 2
        assert isinstance(root.handlers[0], logging.StreamHandler)
        assert isinstance(root.handlers[1], RotatingFileHandler)
        assert isinstance(root.handlers[1].formatter, JSONFormatter)

    def test_file_handler_writes(self, tmp_path):
        log_file = str(tmp_path / "test.log")
        configure_logging(level="INFO", json_format=True, log_file=log_file)

        test_logger = logging.getLogger("storebot.test_file")
        test_logger.info("file handler test")

        content = (tmp_path / "test.log").read_text()
        data = json.loads(content.strip())
        assert data["message"] == "file handler test"

    def test_file_handler_creates_parent_dirs(self, tmp_path):
        log_file = str(tmp_path / "subdir" / "nested" / "test.log")
        configure_logging(level="INFO", json_format=True, log_file=log_file)
        root = logging.getLogger()

        assert len(root.handlers) == 2
        assert (tmp_path / "subdir" / "nested").is_dir()

    def test_no_file_handler_when_empty(self):
        configure_logging(level="INFO", json_format=True, log_file="")
        root = logging.getLogger()

        assert len(root.handlers) == 1
        assert not isinstance(root.handlers[0], RotatingFileHandler)

    def test_storebot_loggers_not_disabled_after_init_db(self):
        """Alembic fileConfig must not disable existing storebot loggers."""
        # Ensure storebot loggers exist before init_db
        test_logger = logging.getLogger("storebot.test_check")
        test_logger.info("pre-init")

        init_db()
        configure_logging(level="INFO", json_format=True)

        assert not test_logger.disabled, (
            "storebot logger disabled by Alembic fileConfig — "
            "check disable_existing_loggers=False in alembic/env.py"
        )
