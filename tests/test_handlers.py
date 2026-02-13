import logging
from unittest.mock import AsyncMock, MagicMock

import pytest

from storebot.bot.handlers import _alert_admin, _send_display_images, _validate_credentials
from storebot.config import Settings


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
