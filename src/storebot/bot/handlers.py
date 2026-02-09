import logging

from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters

from storebot.agent import Agent
from storebot.config import get_settings
from storebot.db import init_db

logger = logging.getLogger(__name__)


async def start(update: Update, context) -> None:
    await update.message.reply_text(
        "Hej! Jag är din butiksassistent. Skicka mig foton på produkter eller skriv "
        "vad du behöver hjälp med.\n\n"
        "Kommandon:\n"
        "/help — Visa hjälp\n"
    )


async def help_command(update: Update, context) -> None:
    await update.message.reply_text(
        "Jag kan hjälpa dig med:\n"
        "- Söka efter liknande produkter på Tradera och Blocket\n"
        "- Skapa annonser\n"
        "- Hantera ordrar\n"
        "- Bokföring via Fortnox\n\n"
        "Skicka foton på en produkt eller beskriv vad du vill göra."
    )


async def handle_photo(update: Update, context) -> None:
    photo = update.message.photo[-1]  # Highest resolution
    file = await photo.get_file()

    # TODO: Download photo to data/photos/{file.file_id}.jpg, pass to agent with vision
    logger.info("Received photo: %s", file.file_id)
    await update.message.reply_text("Foto mottaget! Bearbetning kommer snart.")


async def handle_text(update: Update, context) -> None:
    agent: Agent = context.bot_data["agent"]
    user_message = update.message.text

    logger.info("Received message: %s", user_message[:100])

    try:
        response = agent.handle_message(user_message)
        await update.message.reply_text(response)
    except Exception:
        logger.exception("Error handling message")
        await update.message.reply_text("Något gick fel. Försök igen.")


def main() -> None:
    settings = get_settings()

    logging.basicConfig(
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        level=getattr(logging, settings.log_level),
    )

    init_db()

    app = Application.builder().token(settings.telegram_bot_token).build()

    app.bot_data["agent"] = Agent(settings)

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))

    logger.info("Starting bot...")
    app.run_polling()


if __name__ == "__main__":
    main()
