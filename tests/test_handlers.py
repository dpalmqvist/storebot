import logging
from unittest.mock import AsyncMock, MagicMock

import pytest

from storebot.bot.handlers import (
    TELEGRAM_MAX_MESSAGE_LENGTH,
    _alert_admin,
    _check_access,
    _format_listing_dashboard,
    _send_display_images,
    _split_message,
    _validate_credentials,
    daily_listing_report_job,
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
        sent_text = context.bot.send_message.call_args.kwargs["text"]
        assert "Daglig annonsrapport" in sent_text

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
        update = MagicMock()
        update.effective_chat.id = 99999
        update.message.reply_text = AsyncMock()

        settings = Settings(telegram_bot_token="x", claude_api_key="x")
        context = MagicMock()
        context.bot_data = {"settings": settings, "allowed_chat_ids": {11111}}

        result = await _check_access(update, context)
        assert result is False
        assert "owner_chat_id" not in context.bot_data

    def test_startup_auto_init_single_allowed_user(self):
        """Simulates the main() startup path for single-user deployment."""
        from storebot.bot.handlers import _parse_allowed_chat_ids

        allowed = _parse_allowed_chat_ids("12345")
        bot_data = {}
        bot_data["allowed_chat_ids"] = allowed
        if len(allowed) == 1:
            bot_data["owner_chat_id"] = next(iter(allowed))

        assert bot_data["owner_chat_id"] == 12345

    def test_startup_no_auto_init_multiple_users(self):
        from storebot.bot.handlers import _parse_allowed_chat_ids

        allowed = _parse_allowed_chat_ids("111,222")
        bot_data = {}
        bot_data["allowed_chat_ids"] = allowed
        if len(allowed) == 1:
            bot_data["owner_chat_id"] = next(iter(allowed))

        assert "owner_chat_id" not in bot_data
