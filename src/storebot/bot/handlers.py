import logging
from datetime import time as dt_time
from pathlib import Path

from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes, MessageHandler, filters

from storebot.agent import Agent
from storebot.config import get_settings
from storebot.db import init_db
from storebot.tools.conversation import ConversationService
from storebot.tools.image import resize_for_analysis

logger = logging.getLogger(__name__)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    context.bot_data["owner_chat_id"] = update.effective_chat.id
    await update.message.reply_text(
        "Hej! Jag är din butiksassistent. Skicka mig foton på produkter eller skriv "
        "vad du behöver hjälp med.\n\n"
        "Kommandon:\n"
        "/help — Visa hjälp\n"
        "/orders — Kolla efter nya ordrar\n"
        "/scout — Kör alla sparade sökningar nu\n"
        "/new — Starta en ny konversation\n"
    )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "Jag kan hjälpa dig med:\n"
        "- Söka efter liknande produkter på Tradera och Blocket\n"
        "- Skapa annonser\n"
        "- Hantera ordrar och leveranser\n"
        "- Bokföring (verifikationer som PDF)\n"
        "- Sparade sökningar (scout) — hitta nya fynd automatiskt\n\n"
        "Kommandon:\n"
        "/orders — Kolla efter nya ordrar\n"
        "/scout — Kör alla sparade sökningar nu\n"
        "/new — Starta en ny konversation\n\n"
        "Skicka foton på en produkt eller beskriv vad du vill göra."
    )


async def new_conversation(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    conversation: ConversationService = context.bot_data["conversation"]
    chat_id = str(update.effective_chat.id)
    conversation.clear_history(chat_id)
    await update.message.reply_text("Konversationen är nollställd. Vad kan jag hjälpa dig med?")


async def orders_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
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
    agent: Agent = context.bot_data["agent"]
    conversation: ConversationService = context.bot_data["conversation"]
    chat_id = str(update.effective_chat.id)

    photo = update.message.photo[-1]  # Highest resolution
    file = await photo.get_file()

    photos_dir = Path("data/photos")
    photos_dir.mkdir(parents=True, exist_ok=True)

    file_path = photos_dir / f"{file.file_unique_id}.jpg"
    await file.download_to_drive(str(file_path))
    logger.info("Downloaded photo: %s", file_path)

    analysis_path = resize_for_analysis(str(file_path))
    caption = update.message.caption or ""

    history = conversation.load_history(chat_id)

    try:
        result = agent.handle_message(
            caption,
            image_paths=[analysis_path],
            conversation_history=history,
        )
        new_messages = result.messages[len(history) :]
        conversation.save_messages(chat_id, new_messages)
        await update.message.reply_text(result.text)
    except Exception:
        logger.exception("Error handling photo")
        await update.message.reply_text("Något gick fel vid bildanalysen. Försök igen.")


async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    agent: Agent = context.bot_data["agent"]
    conversation: ConversationService = context.bot_data["conversation"]
    chat_id = str(update.effective_chat.id)
    user_message = update.message.text

    logger.info("Received message: %s", user_message[:100])

    history = conversation.load_history(chat_id)

    try:
        result = agent.handle_message(
            user_message,
            conversation_history=history,
        )
        new_messages = result.messages[len(history) :]
        conversation.save_messages(chat_id, new_messages)
        await update.message.reply_text(result.text)
    except Exception:
        logger.exception("Error handling message")
        await update.message.reply_text("Något gick fel. Försök igen.")


async def scout_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    agent: Agent = context.bot_data["agent"]
    if not agent.scout:
        await update.message.reply_text("Scout-tjänsten är inte tillgänglig.")
        return

    try:
        result = agent.scout.run_all_searches()
        digest = result.get("digest", "Inga nya fynd.")
        if len(digest) > 4000:
            digest = digest[:4000] + "\n\n...avkortat"
        await update.message.reply_text(digest)
    except Exception:
        logger.exception("Error running scout command")
        await update.message.reply_text("Något gick fel vid scout-sökningen. Försök igen.")


async def scout_digest_job(context: ContextTypes.DEFAULT_TYPE) -> None:
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
        if len(digest) > 4000:
            digest = digest[:4000] + "\n\n...avkortat"
        await context.bot.send_message(chat_id=chat_id, text=digest)
    except Exception:
        logger.exception("Error in scout digest job")


async def poll_orders_job(context: ContextTypes.DEFAULT_TYPE) -> None:
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
                f"Köpare: {order.get('buyer_name', 'Okänd')}\n"
                f"Produkt: #{order['product_id']}\n"
                f"Belopp: {order.get('sale_price', 0)} kr"
            )
            await context.bot.send_message(chat_id=chat_id, text=msg)

    except Exception:
        logger.exception("Error in order polling job")


def main() -> None:
    settings = get_settings()

    logging.basicConfig(
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        level=getattr(logging, settings.log_level),
    )

    engine = init_db()

    app = Application.builder().token(settings.telegram_bot_token).build()

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

    logger.info("Starting bot...")
    app.run_polling()


if __name__ == "__main__":
    main()
