import logging
from unittest.mock import AsyncMock, MagicMock

import pytest
import telegram.error

from storebot import __version__
from storebot.bot.handlers import (
    _alert_admin,
    _check_access,
    _format_listing_dashboard,
    _init_owner,
    _reply,
    _send,
    _send_display_images,
    _validate_credentials,
    daily_listing_report_job,
    new_conversation,
)
from storebot.config import Settings


class TestValidateCredentials:
    def test_all_creds_present_no_warnings(self, caplog):
        settings = Settings(
            telegram_bot_token="tok",
            claude_api_key="key",
            tradera_app_id="tid",
            tradera_app_key="tkey",
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

        context.bot.send_message.assert_awaited_once()
        call_kwargs = context.bot.send_message.call_args.kwargs
        assert call_kwargs["chat_id"] == 12345
        assert call_kwargs["text"] == "Test alert"
        assert call_kwargs["parse_mode"] == "HTML"

    @pytest.mark.asyncio
    async def test_does_nothing_when_no_chat_id(self):
        context = MagicMock()
        context.bot_data = {}
        context.bot.send_message = AsyncMock()

        await _alert_admin(context, "Test alert")

        context.bot.send_message.assert_not_awaited()


class TestFormatListingDashboard:
    def test_empty_dashboard(self):
        dashboard = {"date": "2025-06-15", "listings": [], "totals": {"active_count": 0}}

        text = _format_listing_dashboard(dashboard)

        assert text == "Inga aktiva annonser just nu."

    def test_with_listings_and_deltas(self):
        dashboard = {
            "date": "2025-06-15",
            "listings": [
                {
                    "listing_id": 1,
                    "title": "Ekfåtölj 1950-tal",
                    "views": 45,
                    "views_delta": 12,
                    "bids": 3,
                    "bids_delta": 1,
                    "watchers": 8,
                    "watchers_delta": 2,
                    "current_price": 1200.0,
                    "days_remaining": 4,
                    "watcher_rate": 17.8,
                    "bid_rate": 6.7,
                    "trend": "improving",
                },
            ],
            "totals": {
                "active_count": 1,
                "total_views": 45,
                "total_bids": 3,
                "total_watchers": 8,
            },
        }

        text = _format_listing_dashboard(dashboard)

        assert "Daglig annonsrapport (2025-06-15)" in text
        assert "Ekfåtölj 1950-tal" in text
        assert "Visningar: 45 (+12)" in text
        assert "Bud: 3 (+1)" in text
        assert "Bevakare: 8 (+2)" in text
        assert "1 200 kr" in text
        assert "Kvar: 4 dagar" in text
        assert "Trend: Uppåt" in text
        assert "Bevakningsgrad: 17.8%" in text
        assert "Budfrekvens: 6.7%" in text
        assert "1 aktiva annonser" in text
        assert "45 visningar" in text
        assert "3 bud" in text

    def test_none_deltas_first_day(self):
        dashboard = {
            "date": "2025-06-15",
            "listings": [
                {
                    "listing_id": 1,
                    "title": "Stol",
                    "views": 10,
                    "views_delta": None,
                    "bids": 0,
                    "bids_delta": None,
                    "watchers": 1,
                    "watchers_delta": None,
                    "current_price": 500.0,
                    "days_remaining": 7,
                    "watcher_rate": 10.0,
                    "bid_rate": 0.0,
                    "trend": "insufficient_data",
                },
            ],
            "totals": {
                "active_count": 1,
                "total_views": 10,
                "total_bids": 0,
                "total_watchers": 1,
            },
        }

        text = _format_listing_dashboard(dashboard)

        assert "Visningar: 10 |" in text
        assert "(+" not in text
        assert "(-" not in text
        assert "Trend: \u2014" in text

    def test_zero_delta(self):
        dashboard = {
            "date": "2025-06-15",
            "listings": [
                {
                    "listing_id": 1,
                    "title": "Bord",
                    "views": 20,
                    "views_delta": 0,
                    "bids": 1,
                    "bids_delta": 0,
                    "watchers": 3,
                    "watchers_delta": 0,
                    "current_price": 800.0,
                    "days_remaining": 2,
                    "watcher_rate": 15.0,
                    "bid_rate": 5.0,
                    "trend": "stable",
                },
            ],
            "totals": {
                "active_count": 1,
                "total_views": 20,
                "total_bids": 1,
                "total_watchers": 3,
            },
        }

        text = _format_listing_dashboard(dashboard)

        assert "(\u00b10)" in text
        assert "Trend: Stabil" in text


class TestDailyListingReportJob:
    @pytest.mark.asyncio
    async def test_sends_report(self):
        marketing = MagicMock()
        marketing.refresh_listing_stats.return_value = {"refreshed": 1}
        marketing.get_listing_dashboard.return_value = {
            "date": "2025-06-15",
            "listings": [
                {
                    "listing_id": 1,
                    "title": "Test",
                    "views": 10,
                    "views_delta": 5,
                    "bids": 0,
                    "bids_delta": 0,
                    "watchers": 1,
                    "watchers_delta": 1,
                    "current_price": 100.0,
                    "days_remaining": 3,
                    "watcher_rate": 10.0,
                    "bid_rate": 0.0,
                    "trend": "stable",
                },
            ],
            "totals": {
                "active_count": 1,
                "total_views": 10,
                "total_bids": 0,
                "total_watchers": 1,
            },
        }

        agent = MagicMock()
        agent.marketing = marketing

        context = MagicMock()
        context.bot_data = {"agent": agent, "owner_chat_id": 12345}
        context.bot.send_message = AsyncMock()

        await daily_listing_report_job(context)

        marketing.refresh_listing_stats.assert_called_once()
        marketing.get_listing_dashboard.assert_called_once()
        context.bot.send_message.assert_awaited_once()
        call_kwargs = context.bot.send_message.call_args.kwargs
        assert "Daglig annonsrapport" in call_kwargs["text"]
        assert call_kwargs["parse_mode"] == "HTML"

    @pytest.mark.asyncio
    async def test_skips_when_no_listings(self):
        marketing = MagicMock()
        marketing.refresh_listing_stats.return_value = {"refreshed": 0}
        marketing.get_listing_dashboard.return_value = {
            "date": "2025-06-15",
            "listings": [],
            "totals": {"active_count": 0},
        }

        agent = MagicMock()
        agent.marketing = marketing

        context = MagicMock()
        context.bot_data = {"agent": agent, "owner_chat_id": 12345}
        context.bot.send_message = AsyncMock()

        await daily_listing_report_job(context)

        context.bot.send_message.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_skips_when_no_marketing(self):
        agent = MagicMock()
        agent.marketing = None

        context = MagicMock()
        context.bot_data = {"agent": agent}
        context.bot.send_message = AsyncMock()

        await daily_listing_report_job(context)

        context.bot.send_message.assert_not_awaited()


class TestOwnerChatId:
    @pytest.mark.asyncio
    async def test_check_access_sets_owner_when_unset(self):
        """Open access (empty allowed_chat_ids) — first user becomes owner."""
        update = MagicMock()
        update.effective_chat.id = 99999
        update.message.reply_text = AsyncMock()

        settings = Settings(telegram_bot_token="x", claude_api_key="x")
        context = MagicMock()
        context.bot_data = {"settings": settings, "allowed_chat_ids": set()}

        result = await _check_access(update, context)
        assert result is True
        assert context.bot_data["owner_chat_id"] == 99999

    @pytest.mark.asyncio
    async def test_check_access_does_not_overwrite_existing_owner(self):
        """Second authorized user must not hijack owner_chat_id."""
        update = MagicMock()
        update.effective_chat.id = 22222
        update.message.reply_text = AsyncMock()

        settings = Settings(telegram_bot_token="x", claude_api_key="x")
        context = MagicMock()
        context.bot_data = {
            "settings": settings,
            "allowed_chat_ids": set(),
            "owner_chat_id": 11111,
        }

        result = await _check_access(update, context)
        assert result is True
        assert context.bot_data["owner_chat_id"] == 11111

    @pytest.mark.asyncio
    async def test_check_access_does_not_set_owner_on_denied(self):
        """Unauthorized user must not become owner."""
        update = MagicMock()
        update.effective_chat.id = 99999
        update.message.reply_text = AsyncMock()

        settings = Settings(telegram_bot_token="x", claude_api_key="x")
        context = MagicMock()
        context.bot_data = {"settings": settings, "allowed_chat_ids": {11111}}

        result = await _check_access(update, context)
        assert result is False
        assert "owner_chat_id" not in context.bot_data

    def test_init_owner_single_allowed_user(self):
        """Single-user deployment: owner_chat_id set eagerly at startup."""
        bot_data = {"allowed_chat_ids": {12345}}
        _init_owner(bot_data)
        assert bot_data["owner_chat_id"] == 12345
        assert bot_data["allowed_chat_ids"] == {12345}

    def test_init_owner_skips_multiple_users(self):
        """Multi-user: owner_chat_id deferred to first authorized interaction."""
        bot_data = {"allowed_chat_ids": {111, 222}}
        _init_owner(bot_data)
        assert "owner_chat_id" not in bot_data
        assert bot_data["allowed_chat_ids"] == {111, 222}

    def test_init_owner_empty_allowed_ids(self):
        """Dev mode (no restriction): owner deferred to first interaction."""
        bot_data = {"allowed_chat_ids": set()}
        _init_owner(bot_data)
        assert "owner_chat_id" not in bot_data
        assert bot_data["allowed_chat_ids"] == set()


class TestNewConversation:
    @pytest.mark.asyncio
    async def test_shows_version(self):
        update = MagicMock()
        update.effective_chat.id = 12345
        update.message.reply_text = AsyncMock()
        conversation = MagicMock()
        context = MagicMock()
        context.bot_data = {
            "settings": Settings(telegram_bot_token="x", claude_api_key="x"),
            "allowed_chat_ids": set(),
            "conversation": conversation,
        }
        await new_conversation(update, context)
        reply = update.message.reply_text.call_args[0][0]
        assert "Konversationen är nollställd" in reply
        assert f"Storebot v{__version__}" in reply


class TestReplyAndSend:
    @pytest.mark.asyncio
    async def test_reply_sends_with_html_parse_mode(self):
        update = MagicMock()
        update.message.reply_text = AsyncMock()

        await _reply(update, "Hello")

        update.message.reply_text.assert_awaited_once_with("Hello", parse_mode="HTML")

    @pytest.mark.asyncio
    async def test_reply_falls_back_on_bad_request(self):
        update = MagicMock()
        update.message.reply_text = AsyncMock(
            side_effect=[telegram.error.BadRequest("parse error"), None]
        )

        await _reply(update, "Hello")

        assert update.message.reply_text.await_count == 2
        # Second call should have no parse_mode
        second_call = update.message.reply_text.call_args_list[1]
        assert second_call == (("Hello",),)

    @pytest.mark.asyncio
    async def test_send_sends_with_html_parse_mode(self):
        context = MagicMock()
        context.bot.send_message = AsyncMock()

        await _send(context, 12345, "Hello")

        context.bot.send_message.assert_awaited_once_with(
            chat_id=12345, text="Hello", parse_mode="HTML"
        )

    @pytest.mark.asyncio
    async def test_send_falls_back_on_bad_request(self):
        context = MagicMock()
        context.bot.send_message = AsyncMock(
            side_effect=[telegram.error.BadRequest("parse error"), None]
        )

        await _send(context, 12345, "Hello")

        assert context.bot.send_message.await_count == 2
        # Second call should have no parse_mode
        second_call = context.bot.send_message.call_args_list[1]
        assert second_call == ((), {"chat_id": 12345, "text": "Hello"})
