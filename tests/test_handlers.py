import logging
from unittest.mock import AsyncMock, MagicMock

import pytest

from storebot.bot.handlers import (
    TELEGRAM_MAX_MESSAGE_LENGTH,
    _alert_admin,
    _send_display_images,
    _split_message,
    _validate_credentials,
)
from storebot.config import Settings


class TestSplitMessage:
    def test_short_message_returned_as_is(self):
        result = _split_message("Hello")
        assert result == ["Hello"]

    def test_exact_limit_not_split(self):
        text = "x" * TELEGRAM_MAX_MESSAGE_LENGTH
        result = _split_message(text)
        assert result == [text]

    def test_over_limit_splits_into_multiple(self):
        text = "x" * (TELEGRAM_MAX_MESSAGE_LENGTH + 1)
        result = _split_message(text)
        assert len(result) >= 2
        assert result[0].startswith("(1/")
        assert result[1].startswith("(2/")

    def test_splits_at_paragraph_boundary(self):
        half = TELEGRAM_MAX_MESSAGE_LENGTH // 2
        text = "a" * half + "\n\n" + "b" * half
        result = _split_message(text)
        assert len(result) == 2
        assert result[0].endswith("a" * half)
        assert "b" * half in result[1]

    def test_splits_at_line_boundary(self):
        half = TELEGRAM_MAX_MESSAGE_LENGTH // 2
        text = "a" * half + "\n" + "b" * half
        result = _split_message(text)
        assert len(result) == 2
        assert result[0].endswith("a" * half)

    def test_splits_at_word_boundary(self):
        # No newlines — should split at space
        word = "word "
        text = word * (TELEGRAM_MAX_MESSAGE_LENGTH // len(word) + 100)
        result = _split_message(text)
        assert len(result) >= 2
        # First chunk content (after header) should end at a word boundary
        content = result[0].split("\n", 1)[1]
        assert content.endswith("word")

    def test_dense_text_without_breaks(self):
        # No spaces, newlines, or paragraphs — must hard-cut
        text = "x" * (TELEGRAM_MAX_MESSAGE_LENGTH * 3)
        result = _split_message(text)
        assert len(result) >= 3
        for part in result:
            assert len(part) <= TELEGRAM_MAX_MESSAGE_LENGTH

    def test_headers_format(self):
        text = "x" * (TELEGRAM_MAX_MESSAGE_LENGTH * 2)
        result = _split_message(text)
        total = len(result)
        for i, part in enumerate(result):
            assert part.startswith(f"({i + 1}/{total})\n")

    def test_no_content_lost(self):
        text = "Hello world! " * 500
        result = _split_message(text)
        # Strip headers and rejoin
        content = " ".join(part.split("\n", 1)[1] for part in result)
        # All words from the original should appear in the reassembled content
        assert content.split() == text.split()

    def test_empty_string(self):
        assert _split_message("") == [""]


class TestValidateCredentials:
    def test_all_creds_present_no_warnings(self, caplog):
        settings = Settings(
            telegram_bot_token="tok",
            claude_api_key="key",
            tradera_app_id="tid",
            tradera_app_key="tkey",
            blocket_bearer_token="btoken",
            postnord_api_key="pkey",
        )
        with caplog.at_level(logging.DEBUG):
            _validate_credentials(settings)

        assert not any(r.levelno >= logging.WARNING for r in caplog.records)

    def test_missing_telegram_token_logs_error(self, caplog):
        settings = Settings(telegram_bot_token="", claude_api_key="key")
        with caplog.at_level(logging.DEBUG):
            _validate_credentials(settings)

        errors = [r for r in caplog.records if r.levelno == logging.ERROR]
        assert any("TELEGRAM_BOT_TOKEN" in r.message for r in errors)

    def test_missing_claude_key_logs_error(self, caplog):
        settings = Settings(telegram_bot_token="tok", claude_api_key="")
        with caplog.at_level(logging.DEBUG):
            _validate_credentials(settings)

        errors = [r for r in caplog.records if r.levelno == logging.ERROR]
        assert any("CLAUDE_API_KEY" in r.message for r in errors)

    def test_missing_tradera_logs_warning(self, caplog):
        settings = Settings(
            telegram_bot_token="tok",
            claude_api_key="key",
            tradera_app_id="",
            tradera_app_key="",
        )
        with caplog.at_level(logging.DEBUG):
            _validate_credentials(settings)

        warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
        assert any("Tradera" in r.message for r in warnings)

    def test_missing_blocket_logs_warning(self, caplog):
        settings = Settings(
            telegram_bot_token="tok",
            claude_api_key="key",
            blocket_bearer_token="",
        )
        with caplog.at_level(logging.DEBUG):
            _validate_credentials(settings)

        warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
        assert any("Blocket" in r.message for r in warnings)

    def test_missing_postnord_logs_warning(self, caplog):
        settings = Settings(
            telegram_bot_token="tok",
            claude_api_key="key",
            postnord_api_key="",
        )
        with caplog.at_level(logging.DEBUG):
            _validate_credentials(settings)

        warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
        assert any("PostNord" in r.message for r in warnings)


class TestSendDisplayImages:
    @pytest.mark.asyncio
    async def test_sends_photos(self, tmp_path):
        img = tmp_path / "test.jpg"
        img.write_bytes(b"fake-jpeg")

        update = MagicMock()
        update.message.reply_photo = AsyncMock()

        await _send_display_images(
            update, [{"path": str(img), "caption": "Bild 1 av 1 (huvudbild)"}]
        )

        update.message.reply_photo.assert_awaited_once()
        call_kwargs = update.message.reply_photo.call_args
        assert call_kwargs.kwargs["caption"] == "Bild 1 av 1 (huvudbild)"

    @pytest.mark.asyncio
    async def test_no_op_on_empty_list(self):
        update = MagicMock()
        update.message.reply_photo = AsyncMock()

        await _send_display_images(update, [])

        update.message.reply_photo.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_graceful_on_missing_file(self):
        update = MagicMock()
        update.message.reply_photo = AsyncMock()
        update.message.reply_text = AsyncMock()

        await _send_display_images(update, [{"path": "/nonexistent/photo.jpg", "caption": "Test"}])

        update.message.reply_photo.assert_not_awaited()
        update.message.reply_text.assert_awaited_once()
        assert "saknas" in update.message.reply_text.call_args[0][0]


class TestAlertAdmin:
    @pytest.mark.asyncio
    async def test_sends_message_when_chat_id_set(self):
        context = MagicMock()
        context.bot_data = {"owner_chat_id": 12345}
        context.bot.send_message = AsyncMock()

        await _alert_admin(context, "Test alert")

        context.bot.send_message.assert_awaited_once_with(chat_id=12345, text="Test alert")

    @pytest.mark.asyncio
    async def test_does_nothing_when_no_chat_id(self):
        context = MagicMock()
        context.bot_data = {}
        context.bot.send_message = AsyncMock()

        await _alert_admin(context, "Test alert")

        context.bot.send_message.assert_not_awaited()
