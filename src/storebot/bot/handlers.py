import logging
import time
from collections import defaultdict
from datetime import time as dt_time
from pathlib import Path

from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes, MessageHandler, filters

from storebot.agent import Agent
from storebot.config import Settings, get_settings
from storebot.db import init_db
from storebot.logging_config import configure_logging
from storebot.tools.conversation import ConversationService
from storebot.tools.image import resize_for_analysis

logger = logging.getLogger(__name__)

TELEGRAM_MAX_MESSAGE_LENGTH = 4000

# Per-chat rate limiting: {chat_id: [timestamp, ...]}
_rate_limit_buckets: dict[int, list[float]] = defaultdict(list)


def _parse_allowed_chat_ids(raw: str) -> set[int]:
    """Parse comma-separated chat IDs into a set. Empty string = empty set (dev mode: all allowed)."""
    return {int(x) for x in raw.split(",") if x.strip()}


def _is_rate_limited(chat_id: int, settings: Settings) -> bool:
    """Return True if chat_id has exceeded the message rate limit."""
    now = time.monotonic()
    window = settings.rate_limit_window_seconds
    bucket = [t for t in _rate_limit_buckets[chat_id] if now - t < window]
    _rate_limit_buckets[chat_id] = bucket

    if len(bucket) >= settings.rate_limit_messages:
        return True
    bucket.append(now)
    return False


def _split_message(text: str) -> list[str]:
    """Split text into Telegram-safe chunks with (1/N) headers when needed."""
    if len(text) <= TELEGRAM_MAX_MESSAGE_LENGTH:
        return [text]

    def _do_split(chunk_size: int) -> list[str]:
        chunks: list[str] = []
        remaining = text
        while remaining:
            if len(remaining) <= chunk_size:
                chunks.append(remaining)
                break
            # Try to split at paragraph, then line, then word boundary
            split_at = remaining.rfind("\n\n", 0, chunk_size)
            if split_at < chunk_size // 2:
                split_at = remaining.rfind("\n", 0, chunk_size)
            if split_at < chunk_size // 2:
                split_at = remaining.rfind(" ", 0, chunk_size)
            if split_at < chunk_size // 2:
                split_at = chunk_size
            chunks.append(remaining[:split_at])
            remaining = remaining[split_at:].lstrip("\n")
        return chunks

    # Split, then verify header length matches actual chunk count (may shift at digit boundaries)
    header_len = len(f"({len(text) // TELEGRAM_MAX_MESSAGE_LENGTH + 1}/{len(text) // TELEGRAM_MAX_MESSAGE_LENGTH + 1})\n")
    chunks = _do_split(TELEGRAM_MAX_MESSAGE_LENGTH - header_len)
    actual_header_len = len(f"({len(chunks)}/{len(chunks)})\n")
    if actual_header_len > header_len:
        chunks = _do_split(TELEGRAM_MAX_MESSAGE_LENGTH - actual_header_len)

    total = len(chunks)
    return [f"({i + 1}/{total})\n{chunk}" for i, chunk in enumerate(chunks)]


async def _reply(update: Update, text: str) -> None:
    """Reply with text, splitting into multiple messages if needed."""
    for part in _split_message(text):
        await update.message.reply_text(part)


async def _send(context: ContextTypes.DEFAULT_TYPE, chat_id: int, text: str) -> None:
    """Send text to a chat, splitting into multiple messages if needed."""
    for part in _split_message(text):
        await context.bot.send_message(chat_id=chat_id, text=part)


async def _send_display_images(update: Update, display_images: list[dict]) -> None:
    """Send product images to the user via Telegram."""
    for img in display_images:
        try:
            with open(img["path"], "rb") as f:
                await update.message.reply_photo(photo=f, caption=img.get("caption", ""))
        except FileNotFoundError:
            logger.warning("Display image not found: %s", img["path"])
            await update.message.reply_text(f"Bildfilen saknas: {img['path']}")


async def _handle_with_conversation(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    user_message: str,
    image_paths: list[str] | None = None,
    error_text: str = "Något gick fel. Försök igen.",
) -> None:
    """Shared logic for handle_text and handle_photo: load history, call agent, save, reply."""
    agent: Agent = context.bot_data["agent"]
    conversation: ConversationService = context.bot_data["conversation"]
    chat_id = str(update.effective_chat.id)

    history = conversation.load_history(chat_id)

    try:
        result = agent.handle_message(
            user_message,
            image_paths=image_paths,
            conversation_history=history,
        )
        new_messages = result.messages[len(history) :]
        conversation.save_messages(chat_id, new_messages)
        if result.display_images:
            await _send_display_images(update, result.display_images)
        await _reply(update, result.text)
    except Exception:
        logger.exception("Error in conversation handler", extra={"chat_id": chat_id})
        await update.message.reply_text(error_text)


def _validate_credentials(settings: Settings) -> None:
    """Log warnings for missing credentials at startup. Does not crash."""
    if not settings.telegram_bot_token:
        logger.error("TELEGRAM_BOT_TOKEN is not set — bot cannot start")
    if not settings.claude_api_key:
        logger.error("CLAUDE_API_KEY is not set — agent will not work")

    if not settings.tradera_app_id or not settings.tradera_app_key:
        logger.warning("Tradera credentials missing — Tradera features disabled")
    if not settings.blocket_bearer_token:
        logger.warning("Blocket bearer token missing — Blocket search disabled")
    if not settings.postnord_api_key:
        logger.warning("PostNord API key missing — shipping labels disabled")


async def _alert_admin(context: ContextTypes.DEFAULT_TYPE, message: str) -> None:
    """Send an alert message to the bot owner, if chat_id is known."""
    chat_id = context.bot_data.get("owner_chat_id")
    if chat_id:
        await context.bot.send_message(chat_id=chat_id, text=message)


async def _check_access(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """Check authorization and rate limiting. Returns True if request should proceed."""
    chat_id = update.effective_chat.id
    allowed = context.bot_data["allowed_chat_ids"]
    if allowed and chat_id not in allowed:
        logger.warning("Unauthorized access attempt", extra={"chat_id": str(chat_id)})
        await update.message.reply_text("Åtkomst nekad.")
        return False
    settings: Settings = context.bot_data["settings"]
    if _is_rate_limited(chat_id, settings):
        logger.warning("Rate limit exceeded", extra={"chat_id": str(chat_id)})
        await update.message.reply_text("För många meddelanden. Vänta en stund.")
        return False
    return True


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await _check_access(update, context):
        return
    context.bot_data["owner_chat_id"] = update.effective_chat.id
    await update.message.reply_text(
        "Hej! Jag är din butiksassistent. Skicka mig foton på produkter eller skriv "
        "vad du behöver hjälp med.\n\n"
        "Kommandon:\n"
        "/help — Visa hjälp\n"
        "/orders — Kolla efter nya ordrar\n"
        "/scout — Kör alla sparade sökningar nu\n"
        "/marketing — Visa marknadsföringsrapport\n"
        "/rapport — Affärsrapport (sammanfattning + lönsamhet + lager)\n"
        "/new — Starta en ny konversation\n"
    )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await _check_access(update, context):
        return
    await update.message.reply_text(
        "Jag kan hjälpa dig med:\n"
        "- Söka efter liknande produkter på Tradera och Blocket\n"
        "- Skapa annonser\n"
        "- Hantera ordrar och leveranser\n"
        "- Bokföring (verifikationer som PDF)\n"
        "- Sparade sökningar (scout) — hitta nya fynd automatiskt\n"
        "- Marknadsföring — prestanda, statistik och förbättringsförslag\n"
        "- Analys — affärssammanfattning, lönsamhet, lagerrapport, periodjämförelse\n\n"
        "Kommandon:\n"
        "/orders — Kolla efter nya ordrar\n"
        "/scout — Kör alla sparade sökningar nu\n"
        "/marketing — Visa marknadsföringsrapport\n"
        "/rapport — Affärsrapport (sammanfattning + lönsamhet + lager)\n"
        "/new — Starta en ny konversation\n\n"
        "Skicka foton på en produkt eller beskriv vad du vill göra."
    )


async def new_conversation(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await _check_access(update, context):
        return
    conversation: ConversationService = context.bot_data["conversation"]
    chat_id = str(update.effective_chat.id)
    conversation.clear_history(chat_id)
    await update.message.reply_text("Konversationen är nollställd. Vad kan jag hjälpa dig med?")


async def orders_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await _check_access(update, context):
        return
    agent: Agent = context.bot_data["agent"]
    try:
        result = agent.handle_message(
            "Kolla efter nya ordrar och visa en sammanfattning av alla väntande ordrar."
        )
        await update.message.reply_text(result.text)
    except Exception:
        logger.exception("Error handling orders command")
        await update.message.reply_text("Något gick fel vid orderkollen. Försök igen.")


async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await _check_access(update, context):
        return
    photo = update.message.photo[-1]  # Highest resolution
    file = await photo.get_file()

    photos_dir = Path("data/photos")
    photos_dir.mkdir(parents=True, exist_ok=True)

    file_path = photos_dir / f"{file.file_unique_id}.jpg"
    await file.download_to_drive(str(file_path))
    logger.info(
        "Downloaded photo: %s",
        file_path,
        extra={"chat_id": str(update.effective_chat.id)},
    )

    analysis_path = resize_for_analysis(str(file_path))
    caption = update.message.caption or ""

    await _handle_with_conversation(
        update,
        context,
        caption,
        image_paths=[analysis_path],
        error_text="Något gick fel vid bildanalysen. Försök igen.",
    )


async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await _check_access(update, context):
        return
    user_message = update.message.text
    chat_id = str(update.effective_chat.id)
    logger.info("Received text message (len=%d)", len(user_message), extra={"chat_id": chat_id})
    await _handle_with_conversation(update, context, user_message)


async def scout_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await _check_access(update, context):
        return
    agent: Agent = context.bot_data["agent"]
    if not agent.scout:
        await update.message.reply_text("Scout-tjänsten är inte tillgänglig.")
        return

    try:
        result = agent.scout.run_all_searches()
        digest = result.get("digest", "Inga nya fynd.")
        await _reply(update, digest)
    except Exception:
        logger.exception("Error running scout command")
        await update.message.reply_text("Något gick fel vid scout-sökningen. Försök igen.")


async def scout_digest_job(context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.info("Starting scheduled job: scout_digest", extra={"job_name": "scout_digest"})
    agent: Agent = context.bot_data.get("agent")
    if not agent or not agent.scout:
        return

    try:
        result = agent.scout.run_all_searches()
        if result.get("total_new", 0) == 0:
            return

        chat_id = context.bot_data.get("owner_chat_id")
        if not chat_id:
            logger.warning("No owner_chat_id set — cannot send scout digest")
            return

        digest = result.get("digest", "")
        await _send(context, chat_id, digest)
    except Exception:
        logger.exception("Error in scout digest job", extra={"job_name": "scout_digest"})
        await _alert_admin(context, "Fel i scout-jobbet. Kontrollera loggarna.")


async def rapport_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await _check_access(update, context):
        return
    agent: Agent = context.bot_data["agent"]
    if not agent.analytics:
        await update.message.reply_text("Analystjänsten är inte tillgänglig.")
        return

    try:
        summary = agent.analytics.business_summary()
        profitability = agent.analytics.profitability_report()
        inventory = agent.analytics.inventory_report()
        text = agent.analytics._format_full_report(summary, profitability, inventory)
        await _reply(update, text)
    except Exception:
        logger.exception("Error running rapport command")
        await update.message.reply_text("Något gick fel vid rapportgenereringen. Försök igen.")


async def weekly_comparison_job(context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.info(
        "Starting scheduled job: weekly_comparison", extra={"job_name": "weekly_comparison"}
    )
    agent: Agent = context.bot_data.get("agent")
    if not agent or not agent.analytics:
        return

    try:
        result = agent.analytics.period_comparison()
        text = agent.analytics._format_comparison(result)

        chat_id = context.bot_data.get("owner_chat_id")
        if not chat_id:
            logger.warning("No owner_chat_id set — cannot send weekly comparison")
            return

        await _send(context, chat_id, text)
    except Exception:
        logger.exception("Error in weekly comparison job", extra={"job_name": "weekly_comparison"})
        await _alert_admin(context, "Fel i veckorapport-jobbet. Kontrollera loggarna.")


async def marketing_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await _check_access(update, context):
        return
    agent: Agent = context.bot_data["agent"]
    if not agent.marketing:
        await update.message.reply_text("Marknadsföringstjänsten är inte tillgänglig.")
        return

    try:
        report = agent.marketing.get_performance_report()
        text = agent.marketing._format_report(report)
        await _reply(update, text)
    except Exception:
        logger.exception("Error running marketing command")
        await update.message.reply_text(
            "Något gick fel vid marknadsföringsrapporten. Försök igen."
        )


async def marketing_refresh_job(context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.info(
        "Starting scheduled job: marketing_refresh", extra={"job_name": "marketing_refresh"}
    )
    agent: Agent = context.bot_data.get("agent")
    if not agent or not agent.marketing:
        return

    try:
        agent.marketing.refresh_listing_stats()

        result = agent.marketing.get_recommendations()
        high_priority = [r for r in result.get("recommendations", []) if r["priority"] == "high"]
        if not high_priority:
            return

        chat_id = context.bot_data.get("owner_chat_id")
        if not chat_id:
            logger.warning("No owner_chat_id set — cannot send marketing recommendations")
            return

        lines = ["Viktiga marknadsföringsförslag:\n"]
        for rec in high_priority:
            lines.append(f"Annons #{rec['listing_id']}: {rec['suggestion']}")
            lines.append(f"  Anledning: {rec['reason']}\n")
        text = "\n".join(lines).strip()
        await _send(context, chat_id, text)
    except Exception:
        logger.exception("Error in marketing refresh job", extra={"job_name": "marketing_refresh"})
        await _alert_admin(context, "Fel i marknadsföringsjobbet. Kontrollera loggarna.")


async def poll_orders_job(context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.info("Starting scheduled job: poll_orders", extra={"job_name": "poll_orders"})
    agent: Agent = context.bot_data.get("agent")
    if not agent or not agent.order:
        return

    try:
        result = agent.order.check_new_orders()
        new_orders = result.get("new_orders", [])
        if not new_orders:
            return

        chat_id = context.bot_data.get("owner_chat_id")
        if not chat_id:
            logger.warning("No owner_chat_id set — cannot send order notifications")
            return

        for order in new_orders:
            msg = (
                f"Ny order! #{order['order_id']}\n"
                f"Produkt: #{order['product_id']}\n"
                f"Belopp: {order.get('sale_price', 0)} kr"
            )
            await context.bot.send_message(chat_id=chat_id, text=msg)

    except Exception:
        logger.exception("Error in order polling job", extra={"job_name": "poll_orders"})
        await _alert_admin(context, "Fel i orderpolling-jobbet. Kontrollera loggarna.")


def main() -> None:
    settings = get_settings()

    engine = init_db()

    configure_logging(
        level=settings.log_level, json_format=settings.log_json, log_file=settings.log_file
    )

    _validate_credentials(settings)

    app = Application.builder().token(settings.telegram_bot_token).build()

    app.bot_data["settings"] = settings
    app.bot_data["allowed_chat_ids"] = _parse_allowed_chat_ids(settings.allowed_chat_ids)
    app.bot_data["agent"] = Agent(settings, engine=engine)
    app.bot_data["conversation"] = ConversationService(
        engine=engine,
        max_messages=settings.max_history_messages,
        timeout_minutes=settings.conversation_timeout_minutes,
    )

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("new", new_conversation))
    app.add_handler(CommandHandler("orders", orders_command))
    app.add_handler(CommandHandler("scout", scout_command))
    app.add_handler(CommandHandler("marketing", marketing_command))
    app.add_handler(CommandHandler("rapport", rapport_command))
    app.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))

    # Scheduled order polling
    if app.job_queue:
        app.job_queue.run_repeating(
            poll_orders_job,
            interval=settings.order_poll_interval_minutes * 60,
            first=60,
        )
        logger.info(
            "Order polling scheduled every %d minutes",
            settings.order_poll_interval_minutes,
        )

        # Daily scout digest
        app.job_queue.run_daily(
            scout_digest_job,
            time=dt_time(hour=settings.scout_digest_hour),
        )
        logger.info(
            "Scout digest scheduled daily at %02d:00",
            settings.scout_digest_hour,
        )

        # Daily marketing stats refresh
        app.job_queue.run_daily(
            marketing_refresh_job,
            time=dt_time(hour=settings.marketing_refresh_hour),
        )
        logger.info(
            "Marketing refresh scheduled daily at %02d:00",
            settings.marketing_refresh_hour,
        )

        # Weekly business comparison (Sundays at 18:00)
        app.job_queue.run_daily(
            weekly_comparison_job,
            time=dt_time(hour=18),
            days=(6,),
        )
        logger.info("Weekly business comparison scheduled Sundays at 18:00")

    logger.info("Starting bot...")
    app.run_polling()


if __name__ == "__main__":
    main()
