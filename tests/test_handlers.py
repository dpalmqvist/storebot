import logging
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import telegram.error

from storebot import __version__
from storebot.bot.handlers import (
    _alert_admin,
    _check_access,
    _format_delta,
    _format_listing_dashboard,
    _handle_with_conversation,
    _init_owner,
    _is_rate_limited,
    _parse_allowed_chat_ids,
    _rate_limit_buckets,
    _reply,
    _send,
    _send_display_images,
    _validate_credentials,
    daily_listing_report_job,
    handle_photo,
    handle_text,
    help_command,
    main,
    marketing_command,
    marketing_refresh_job,
    new_conversation,
    orders_command,
    poll_orders_job,
    rapport_command,
    scout_command,
    scout_digest_job,
    start,
    weekly_comparison_job,
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

        await _reply(update, "<b>Hello</b>")

        assert update.message.reply_text.await_count == 2
        # Second call should strip HTML tags and have no parse_mode
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

        await _send(context, 12345, "<b>Hello</b>")

        assert context.bot.send_message.await_count == 2
        # Second call should strip HTML tags and have no parse_mode
        second_call = context.bot.send_message.call_args_list[1]
        assert second_call == ((), {"chat_id": 12345, "text": "Hello"})


# ---------------------------------------------------------------------------
# _parse_allowed_chat_ids
# ---------------------------------------------------------------------------


class TestParseAllowedChatIds:
    def test_empty_string(self):
        assert _parse_allowed_chat_ids("") == set()

    def test_single_id(self):
        assert _parse_allowed_chat_ids("12345") == {12345}

    def test_multiple_ids(self):
        assert _parse_allowed_chat_ids("111,222,333") == {111, 222, 333}

    def test_whitespace_handled(self):
        assert _parse_allowed_chat_ids("111, 222 , 333") == {111, 222, 333}


# ---------------------------------------------------------------------------
# _is_rate_limited
# ---------------------------------------------------------------------------


class TestIsRateLimited:
    def test_within_limit(self):
        settings = Settings(telegram_bot_token="x", claude_api_key="x")
        chat_id = 99990001
        _rate_limit_buckets.pop(chat_id, None)
        assert _is_rate_limited(chat_id, settings) is False

    def test_exceeds_limit(self):
        settings = Settings(
            telegram_bot_token="x",
            claude_api_key="x",
            rate_limit_messages=2,
            rate_limit_window_seconds=60,
        )
        chat_id = 99990002
        _rate_limit_buckets[chat_id] = [time.monotonic(), time.monotonic()]
        assert _is_rate_limited(chat_id, settings) is True
        _rate_limit_buckets.pop(chat_id, None)


# ---------------------------------------------------------------------------
# _format_delta
# ---------------------------------------------------------------------------


class TestFormatDelta:
    def test_negative_value(self):
        assert _format_delta(-5) == " (-5)"


# ---------------------------------------------------------------------------
# _check_access — rate limiting branch
# ---------------------------------------------------------------------------


class TestCheckAccessRateLimited:
    @pytest.mark.asyncio
    async def test_rate_limited_returns_false(self):
        update = MagicMock()
        update.effective_chat.id = 99990003
        update.message.reply_text = AsyncMock()

        settings = Settings(
            telegram_bot_token="x",
            claude_api_key="x",
            rate_limit_messages=0,
            rate_limit_window_seconds=60,
        )
        context = MagicMock()
        context.bot_data = {"settings": settings, "allowed_chat_ids": set()}

        result = await _check_access(update, context)
        assert result is False
        assert "För många meddelanden" in update.message.reply_text.call_args[0][0]
        _rate_limit_buckets.pop(99990003, None)


# ---------------------------------------------------------------------------
# _handle_with_conversation
# ---------------------------------------------------------------------------


class TestHandleWithConversation:
    def _make_mocks(self):
        update = MagicMock()
        update.effective_chat.id = 12345
        update.message.reply_text = AsyncMock()
        update.message.reply_photo = AsyncMock()

        agent_response = MagicMock()
        agent_response.text = "Agent reply"
        agent_response.messages = [
            {"role": "user", "content": "hi"},
            {"role": "assistant", "content": "Agent reply"},
        ]
        agent_response.display_images = []

        agent = MagicMock()
        agent.settings.compact_threshold = 100
        agent.handle_message = MagicMock(return_value=agent_response)

        conversation = MagicMock()
        conversation.load_history = MagicMock(return_value=[])

        context = MagicMock()
        context.bot_data = {"agent": agent, "conversation": conversation}

        return update, context, agent, conversation, agent_response

    @pytest.mark.asyncio
    async def test_happy_path(self):
        update, context, agent, conversation, _ = self._make_mocks()
        await _handle_with_conversation(update, context, "hi")
        agent.handle_message.assert_called_once()
        conversation.save_messages.assert_called_once()
        update.message.reply_text.assert_awaited()

    @pytest.mark.asyncio
    async def test_with_display_images(self, tmp_path):
        update, context, agent, conversation, agent_response = self._make_mocks()
        img = tmp_path / "test.jpg"
        img.write_bytes(b"fake")
        agent_response.display_images = [{"path": str(img)}]
        await _handle_with_conversation(update, context, "hi")
        update.message.reply_photo.assert_awaited()

    @pytest.mark.asyncio
    async def test_compaction_triggered(self):
        update, context, agent, conversation, _ = self._make_mocks()
        agent.settings.compact_threshold = 2
        old_history = [{"role": "user", "content": "old"}] * 5
        conversation.load_history = MagicMock(return_value=old_history)
        new_history = [{"role": "user", "content": "compacted"}]
        agent.compact_history = MagicMock(return_value=new_history)
        await _handle_with_conversation(update, context, "hi")
        agent.compact_history.assert_called_once()
        conversation.replace_history.assert_called_once()

    @pytest.mark.asyncio
    async def test_error_handled(self):
        update, context, agent, conversation, _ = self._make_mocks()
        agent.handle_message = MagicMock(side_effect=RuntimeError("boom"))
        await _handle_with_conversation(update, context, "hi")
        # Should reply with error text
        calls = update.message.reply_text.call_args_list
        assert any("Något gick fel" in str(c) for c in calls)

    @pytest.mark.asyncio
    async def test_with_image_paths(self):
        update, context, agent, conversation, _ = self._make_mocks()
        await _handle_with_conversation(update, context, "caption", image_paths=["/img/1.jpg"])
        call_kwargs = agent.handle_message.call_args
        assert call_kwargs.kwargs.get("image_paths") == ["/img/1.jpg"]


# ---------------------------------------------------------------------------
# Command handlers
# ---------------------------------------------------------------------------


class TestStartCommand:
    @pytest.mark.asyncio
    async def test_start_happy_path(self):
        update = MagicMock()
        update.effective_chat.id = 12345
        update.message.reply_text = AsyncMock()
        context = MagicMock()
        context.bot_data = {
            "settings": Settings(telegram_bot_token="x", claude_api_key="x"),
            "allowed_chat_ids": set(),
        }
        await start(update, context)
        text = update.message.reply_text.call_args[0][0]
        assert "butiksassistent" in text
        assert "/help" in text


class TestHelpCommand:
    @pytest.mark.asyncio
    async def test_help_happy_path(self):
        update = MagicMock()
        update.effective_chat.id = 12345
        update.message.reply_text = AsyncMock()
        context = MagicMock()
        context.bot_data = {
            "settings": Settings(telegram_bot_token="x", claude_api_key="x"),
            "allowed_chat_ids": set(),
        }
        await help_command(update, context)
        text = update.message.reply_text.call_args[0][0]
        assert "Tradera" in text
        assert "/orders" in text


class TestOrdersCommand:
    @pytest.mark.asyncio
    async def test_orders_happy_path(self):
        update = MagicMock()
        update.effective_chat.id = 12345
        update.message.reply_text = AsyncMock()
        agent_response = MagicMock()
        agent_response.text = "Inga nya ordrar"
        agent = MagicMock()
        agent.handle_message = MagicMock(return_value=agent_response)
        context = MagicMock()
        context.bot_data = {
            "settings": Settings(telegram_bot_token="x", claude_api_key="x"),
            "allowed_chat_ids": set(),
            "agent": agent,
        }
        await orders_command(update, context)
        update.message.reply_text.assert_awaited()

    @pytest.mark.asyncio
    async def test_orders_error(self):
        update = MagicMock()
        update.effective_chat.id = 12345
        update.message.reply_text = AsyncMock()
        agent = MagicMock()
        agent.handle_message = MagicMock(side_effect=RuntimeError("boom"))
        context = MagicMock()
        context.bot_data = {
            "settings": Settings(telegram_bot_token="x", claude_api_key="x"),
            "allowed_chat_ids": set(),
            "agent": agent,
        }
        await orders_command(update, context)
        assert "Något gick fel" in update.message.reply_text.call_args[0][0]


class TestHandlePhoto:
    @pytest.mark.asyncio
    async def test_photo_happy_path(self, tmp_path):
        update = MagicMock()
        update.effective_chat.id = 12345
        update.message.reply_text = AsyncMock()
        update.message.reply_photo = AsyncMock()
        update.message.caption = "Test caption"

        photo = MagicMock()
        photo.file_unique_id = "abc123"
        file_mock = AsyncMock()
        file_mock.download_to_drive = AsyncMock()
        photo.get_file = AsyncMock(return_value=file_mock)
        update.message.photo = [photo]

        settings = Settings(
            telegram_bot_token="x",
            claude_api_key="x",
            product_image_dir=str(tmp_path / "photos"),
        )
        agent_response = MagicMock()
        agent_response.text = "I see an image"
        agent_response.messages = [
            {"role": "user", "content": "img"},
            {"role": "assistant", "content": "response"},
        ]
        agent_response.display_images = []
        agent = MagicMock()
        agent.settings.compact_threshold = 100
        agent.handle_message = MagicMock(return_value=agent_response)
        conversation = MagicMock()
        conversation.load_history = MagicMock(return_value=[])

        context = MagicMock()
        context.bot_data = {
            "settings": settings,
            "allowed_chat_ids": set(),
            "agent": agent,
            "conversation": conversation,
        }

        with patch("storebot.bot.handlers.resize_for_analysis", return_value="/tmp/resized.jpg"):
            await handle_photo(update, context)
        file_mock.download_to_drive.assert_awaited_once()


class TestHandleText:
    @pytest.mark.asyncio
    async def test_text_happy_path(self):
        update = MagicMock()
        update.effective_chat.id = 12345
        update.message.text = "Sök efter stolar"
        update.message.reply_text = AsyncMock()

        agent_response = MagicMock()
        agent_response.text = "Found chairs"
        agent_response.messages = [
            {"role": "user", "content": "q"},
            {"role": "assistant", "content": "a"},
        ]
        agent_response.display_images = []
        agent = MagicMock()
        agent.settings.compact_threshold = 100
        agent.handle_message = MagicMock(return_value=agent_response)
        conversation = MagicMock()
        conversation.load_history = MagicMock(return_value=[])

        context = MagicMock()
        context.bot_data = {
            "settings": Settings(telegram_bot_token="x", claude_api_key="x"),
            "allowed_chat_ids": set(),
            "agent": agent,
            "conversation": conversation,
        }
        await handle_text(update, context)
        agent.handle_message.assert_called_once()


class TestScoutCommand:
    @pytest.mark.asyncio
    async def test_scout_happy_path(self):
        update = MagicMock()
        update.effective_chat.id = 12345
        update.message.reply_text = AsyncMock()
        scout = MagicMock()
        scout.run_all_searches = MagicMock(return_value={"digest": "Found items", "total_new": 2})
        agent = MagicMock()
        agent.scout = scout
        context = MagicMock()
        context.bot_data = {
            "settings": Settings(telegram_bot_token="x", claude_api_key="x"),
            "allowed_chat_ids": set(),
            "agent": agent,
        }
        await scout_command(update, context)
        update.message.reply_text.assert_awaited()

    @pytest.mark.asyncio
    async def test_scout_no_service(self):
        update = MagicMock()
        update.effective_chat.id = 12345
        update.message.reply_text = AsyncMock()
        agent = MagicMock()
        agent.scout = None
        context = MagicMock()
        context.bot_data = {
            "settings": Settings(telegram_bot_token="x", claude_api_key="x"),
            "allowed_chat_ids": set(),
            "agent": agent,
        }
        await scout_command(update, context)
        assert "inte tillgänglig" in update.message.reply_text.call_args[0][0]

    @pytest.mark.asyncio
    async def test_scout_error(self):
        update = MagicMock()
        update.effective_chat.id = 12345
        update.message.reply_text = AsyncMock()
        scout = MagicMock()
        scout.run_all_searches = MagicMock(side_effect=RuntimeError("fail"))
        agent = MagicMock()
        agent.scout = scout
        context = MagicMock()
        context.bot_data = {
            "settings": Settings(telegram_bot_token="x", claude_api_key="x"),
            "allowed_chat_ids": set(),
            "agent": agent,
        }
        await scout_command(update, context)
        assert "Något gick fel" in update.message.reply_text.call_args[0][0]


# ---------------------------------------------------------------------------
# Scheduled jobs
# ---------------------------------------------------------------------------


class TestScoutDigestJob:
    @pytest.mark.asyncio
    async def test_sends_digest(self):
        scout = MagicMock()
        scout.run_all_searches = MagicMock(return_value={"total_new": 3, "digest": "3 nya fynd"})
        agent = MagicMock()
        agent.scout = scout
        context = MagicMock()
        context.bot_data = {"agent": agent, "owner_chat_id": 12345}
        context.bot.send_message = AsyncMock()
        await scout_digest_job(context)
        context.bot.send_message.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_no_new_items_skips(self):
        scout = MagicMock()
        scout.run_all_searches = MagicMock(return_value={"total_new": 0})
        agent = MagicMock()
        agent.scout = scout
        context = MagicMock()
        context.bot_data = {"agent": agent, "owner_chat_id": 12345}
        context.bot.send_message = AsyncMock()
        await scout_digest_job(context)
        context.bot.send_message.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_no_agent_returns(self):
        context = MagicMock()
        context.bot_data = {}
        context.bot.send_message = AsyncMock()
        await scout_digest_job(context)
        context.bot.send_message.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_no_owner_chat_id(self):
        scout = MagicMock()
        scout.run_all_searches = MagicMock(return_value={"total_new": 1, "digest": "fynd"})
        agent = MagicMock()
        agent.scout = scout
        context = MagicMock()
        context.bot_data = {"agent": agent}
        context.bot.send_message = AsyncMock()
        await scout_digest_job(context)
        context.bot.send_message.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_error_alerts_admin(self):
        scout = MagicMock()
        scout.run_all_searches = MagicMock(side_effect=RuntimeError("fail"))
        agent = MagicMock()
        agent.scout = scout
        context = MagicMock()
        context.bot_data = {"agent": agent, "owner_chat_id": 12345}
        context.bot.send_message = AsyncMock()
        await scout_digest_job(context)
        # Should have sent alert
        context.bot.send_message.assert_awaited()


class TestRapportCommand:
    @pytest.mark.asyncio
    async def test_rapport_happy_path(self):
        update = MagicMock()
        update.effective_chat.id = 12345
        update.message.reply_text = AsyncMock()
        analytics = MagicMock()
        analytics.business_summary = MagicMock(return_value={})
        analytics.profitability_report = MagicMock(return_value={})
        analytics.inventory_report = MagicMock(return_value={})
        analytics._format_full_report = MagicMock(return_value="Report text")
        agent = MagicMock()
        agent.analytics = analytics
        context = MagicMock()
        context.bot_data = {
            "settings": Settings(telegram_bot_token="x", claude_api_key="x"),
            "allowed_chat_ids": set(),
            "agent": agent,
        }
        await rapport_command(update, context)
        update.message.reply_text.assert_awaited()

    @pytest.mark.asyncio
    async def test_rapport_no_analytics(self):
        update = MagicMock()
        update.effective_chat.id = 12345
        update.message.reply_text = AsyncMock()
        agent = MagicMock()
        agent.analytics = None
        context = MagicMock()
        context.bot_data = {
            "settings": Settings(telegram_bot_token="x", claude_api_key="x"),
            "allowed_chat_ids": set(),
            "agent": agent,
        }
        await rapport_command(update, context)
        assert "inte tillgänglig" in update.message.reply_text.call_args[0][0]

    @pytest.mark.asyncio
    async def test_rapport_error(self):
        update = MagicMock()
        update.effective_chat.id = 12345
        update.message.reply_text = AsyncMock()
        analytics = MagicMock()
        analytics.business_summary = MagicMock(side_effect=RuntimeError("fail"))
        agent = MagicMock()
        agent.analytics = analytics
        context = MagicMock()
        context.bot_data = {
            "settings": Settings(telegram_bot_token="x", claude_api_key="x"),
            "allowed_chat_ids": set(),
            "agent": agent,
        }
        await rapport_command(update, context)
        assert "Något gick fel" in update.message.reply_text.call_args[0][0]


class TestWeeklyComparisonJob:
    @pytest.mark.asyncio
    async def test_sends_comparison(self):
        analytics = MagicMock()
        analytics.period_comparison = MagicMock(return_value={})
        analytics._format_comparison = MagicMock(return_value="Weekly text")
        agent = MagicMock()
        agent.analytics = analytics
        context = MagicMock()
        context.bot_data = {"agent": agent, "owner_chat_id": 12345}
        context.bot.send_message = AsyncMock()
        await weekly_comparison_job(context)
        context.bot.send_message.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_no_agent(self):
        context = MagicMock()
        context.bot_data = {}
        context.bot.send_message = AsyncMock()
        await weekly_comparison_job(context)
        context.bot.send_message.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_no_owner_chat_id(self):
        analytics = MagicMock()
        analytics.period_comparison = MagicMock(return_value={})
        analytics._format_comparison = MagicMock(return_value="text")
        agent = MagicMock()
        agent.analytics = analytics
        context = MagicMock()
        context.bot_data = {"agent": agent}
        context.bot.send_message = AsyncMock()
        await weekly_comparison_job(context)
        context.bot.send_message.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_error_alerts_admin(self):
        analytics = MagicMock()
        analytics.period_comparison = MagicMock(side_effect=RuntimeError("fail"))
        agent = MagicMock()
        agent.analytics = analytics
        context = MagicMock()
        context.bot_data = {"agent": agent, "owner_chat_id": 12345}
        context.bot.send_message = AsyncMock()
        await weekly_comparison_job(context)
        context.bot.send_message.assert_awaited()


class TestMarketingCommand:
    @pytest.mark.asyncio
    async def test_marketing_happy_path(self):
        update = MagicMock()
        update.effective_chat.id = 12345
        update.message.reply_text = AsyncMock()
        marketing = MagicMock()
        marketing.get_performance_report = MagicMock(return_value={})
        marketing._format_report = MagicMock(return_value="Report")
        agent = MagicMock()
        agent.marketing = marketing
        context = MagicMock()
        context.bot_data = {
            "settings": Settings(telegram_bot_token="x", claude_api_key="x"),
            "allowed_chat_ids": set(),
            "agent": agent,
        }
        await marketing_command(update, context)
        update.message.reply_text.assert_awaited()

    @pytest.mark.asyncio
    async def test_marketing_no_service(self):
        update = MagicMock()
        update.effective_chat.id = 12345
        update.message.reply_text = AsyncMock()
        agent = MagicMock()
        agent.marketing = None
        context = MagicMock()
        context.bot_data = {
            "settings": Settings(telegram_bot_token="x", claude_api_key="x"),
            "allowed_chat_ids": set(),
            "agent": agent,
        }
        await marketing_command(update, context)
        assert "inte tillgänglig" in update.message.reply_text.call_args[0][0]

    @pytest.mark.asyncio
    async def test_marketing_error(self):
        update = MagicMock()
        update.effective_chat.id = 12345
        update.message.reply_text = AsyncMock()
        marketing = MagicMock()
        marketing.get_performance_report = MagicMock(side_effect=RuntimeError("fail"))
        agent = MagicMock()
        agent.marketing = marketing
        context = MagicMock()
        context.bot_data = {
            "settings": Settings(telegram_bot_token="x", claude_api_key="x"),
            "allowed_chat_ids": set(),
            "agent": agent,
        }
        await marketing_command(update, context)
        assert "Något gick fel" in update.message.reply_text.call_args[0][0]


class TestMarketingRefreshJob:
    @pytest.mark.asyncio
    async def test_sends_high_priority(self):
        marketing = MagicMock()
        marketing.refresh_listing_stats = MagicMock()
        marketing.get_recommendations = MagicMock(
            return_value={
                "recommendations": [
                    {
                        "priority": "high",
                        "listing_id": 1,
                        "suggestion": "Sänk pris",
                        "reason": "Inga bud",
                    },
                ]
            }
        )
        agent = MagicMock()
        agent.marketing = marketing
        context = MagicMock()
        context.bot_data = {"agent": agent, "owner_chat_id": 12345}
        context.bot.send_message = AsyncMock()
        await marketing_refresh_job(context)
        context.bot.send_message.assert_awaited_once()
        text = context.bot.send_message.call_args.kwargs["text"]
        assert "Sänk pris" in text

    @pytest.mark.asyncio
    async def test_no_high_priority_skips(self):
        marketing = MagicMock()
        marketing.refresh_listing_stats = MagicMock()
        marketing.get_recommendations = MagicMock(
            return_value={
                "recommendations": [
                    {"priority": "low", "listing_id": 1, "suggestion": "X", "reason": "Y"},
                ]
            }
        )
        agent = MagicMock()
        agent.marketing = marketing
        context = MagicMock()
        context.bot_data = {"agent": agent, "owner_chat_id": 12345}
        context.bot.send_message = AsyncMock()
        await marketing_refresh_job(context)
        context.bot.send_message.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_no_agent(self):
        context = MagicMock()
        context.bot_data = {}
        context.bot.send_message = AsyncMock()
        await marketing_refresh_job(context)
        context.bot.send_message.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_no_owner_chat_id(self):
        marketing = MagicMock()
        marketing.refresh_listing_stats = MagicMock()
        marketing.get_recommendations = MagicMock(
            return_value={
                "recommendations": [
                    {"priority": "high", "listing_id": 1, "suggestion": "X", "reason": "Y"},
                ]
            }
        )
        agent = MagicMock()
        agent.marketing = marketing
        context = MagicMock()
        context.bot_data = {"agent": agent}
        context.bot.send_message = AsyncMock()
        await marketing_refresh_job(context)
        context.bot.send_message.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_error_alerts_admin(self):
        marketing = MagicMock()
        marketing.refresh_listing_stats = MagicMock(side_effect=RuntimeError("fail"))
        agent = MagicMock()
        agent.marketing = marketing
        context = MagicMock()
        context.bot_data = {"agent": agent, "owner_chat_id": 12345}
        context.bot.send_message = AsyncMock()
        await marketing_refresh_job(context)
        context.bot.send_message.assert_awaited()


class TestDailyListingReportJobEdgeCases:
    @pytest.mark.asyncio
    async def test_no_owner_chat_id(self):
        marketing = MagicMock()
        marketing.refresh_listing_stats = MagicMock()
        marketing.get_listing_dashboard = MagicMock(
            return_value={
                "listings": [{"listing_id": 1}],
            }
        )
        agent = MagicMock()
        agent.marketing = marketing
        context = MagicMock()
        context.bot_data = {"agent": agent}
        context.bot.send_message = AsyncMock()
        await daily_listing_report_job(context)
        context.bot.send_message.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_error_alerts_admin(self):
        marketing = MagicMock()
        marketing.refresh_listing_stats = MagicMock(side_effect=RuntimeError("fail"))
        agent = MagicMock()
        agent.marketing = marketing
        context = MagicMock()
        context.bot_data = {"agent": agent, "owner_chat_id": 12345}
        context.bot.send_message = AsyncMock()
        await daily_listing_report_job(context)
        context.bot.send_message.assert_awaited()


class TestPollOrdersJob:
    @pytest.mark.asyncio
    async def test_sends_new_orders(self):
        order = MagicMock()
        order.check_new_orders = MagicMock(
            return_value={
                "new_orders": [
                    {"order_id": 42, "product_id": 1, "sale_price": 500},
                ]
            }
        )
        agent = MagicMock()
        agent.order = order
        context = MagicMock()
        context.bot_data = {"agent": agent, "owner_chat_id": 12345}
        context.bot.send_message = AsyncMock()
        await poll_orders_job(context)
        context.bot.send_message.assert_awaited_once()
        text = context.bot.send_message.call_args.kwargs["text"]
        assert "Ny order" in text

    @pytest.mark.asyncio
    async def test_no_new_orders_skips(self):
        order = MagicMock()
        order.check_new_orders = MagicMock(return_value={"new_orders": []})
        agent = MagicMock()
        agent.order = order
        context = MagicMock()
        context.bot_data = {"agent": agent, "owner_chat_id": 12345}
        context.bot.send_message = AsyncMock()
        await poll_orders_job(context)
        context.bot.send_message.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_no_agent(self):
        context = MagicMock()
        context.bot_data = {}
        context.bot.send_message = AsyncMock()
        await poll_orders_job(context)
        context.bot.send_message.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_no_owner_chat_id(self):
        order = MagicMock()
        order.check_new_orders = MagicMock(
            return_value={"new_orders": [{"order_id": 1, "product_id": 1, "sale_price": 100}]}
        )
        agent = MagicMock()
        agent.order = order
        context = MagicMock()
        context.bot_data = {"agent": agent}
        context.bot.send_message = AsyncMock()
        await poll_orders_job(context)
        context.bot.send_message.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_error_alerts_admin(self):
        order = MagicMock()
        order.check_new_orders = MagicMock(side_effect=RuntimeError("fail"))
        agent = MagicMock()
        agent.order = order
        context = MagicMock()
        context.bot_data = {"agent": agent, "owner_chat_id": 12345}
        context.bot.send_message = AsyncMock()
        await poll_orders_job(context)
        context.bot.send_message.assert_awaited()


# ---------------------------------------------------------------------------
# main()
# ---------------------------------------------------------------------------


class TestMain:
    def test_main_setup(self):
        """Cover main() setup (lines 540-617). app.run_polling is mocked."""
        mock_settings = MagicMock(spec=Settings)
        mock_settings.telegram_bot_token = "test-token"
        mock_settings.claude_api_key = "test-key"
        mock_settings.tradera_app_id = ""
        mock_settings.tradera_app_key = ""
        mock_settings.postnord_api_key = ""
        mock_settings.allowed_chat_ids = ""
        mock_settings.log_level = "INFO"
        mock_settings.log_json = False
        mock_settings.log_file = ""
        mock_settings.max_history_messages = 50
        mock_settings.conversation_timeout_minutes = 60
        mock_settings.order_poll_interval_minutes = 30
        mock_settings.scout_digest_hour = 7
        mock_settings.marketing_refresh_hour = 8
        mock_settings.listing_report_hour = 7

        mock_app = MagicMock()
        mock_app.bot_data = {}
        mock_job_queue = MagicMock()
        mock_app.job_queue = mock_job_queue

        with (
            patch("storebot.bot.handlers.get_settings", return_value=mock_settings),
            patch("storebot.bot.handlers.init_db", return_value=MagicMock()),
            patch("storebot.bot.handlers.configure_logging"),
            patch("storebot.bot.handlers.Agent", return_value=MagicMock()),
            patch("storebot.bot.handlers.ConversationService", return_value=MagicMock()),
            patch("storebot.bot.handlers.Application") as MockApplication,
        ):
            mock_builder = MagicMock()
            mock_builder.token.return_value.build.return_value = mock_app
            MockApplication.builder.return_value = mock_builder

            main()

            mock_app.run_polling.assert_called_once()
            mock_app.add_handler.assert_called()
            mock_job_queue.run_repeating.assert_called_once()
            assert mock_job_queue.run_daily.call_count == 4  # 4 daily jobs


# ---------------------------------------------------------------------------
# _check_access denial path for each command handler
# ---------------------------------------------------------------------------


def _denied_update_context():
    """Create update/context where _check_access returns False (unauthorized)."""
    update = MagicMock()
    update.effective_chat.id = 99999
    update.message.reply_text = AsyncMock()
    context = MagicMock()
    context.bot_data = {
        "settings": Settings(telegram_bot_token="x", claude_api_key="x"),
        "allowed_chat_ids": {12345},  # 99999 is NOT in the set
    }
    return update, context


class TestAccessDeniedPaths:
    """Cover the 'return' lines after _check_access fails for each handler."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "handler",
        [
            start,
            help_command,
            new_conversation,
            orders_command,
            handle_photo,
            handle_text,
            scout_command,
            rapport_command,
            marketing_command,
        ],
        ids=lambda h: h.__name__,
    )
    async def test_denied(self, handler):
        update, ctx = _denied_update_context()
        await handler(update, ctx)
        assert "nekad" in update.message.reply_text.call_args[0][0]
