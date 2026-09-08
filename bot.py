"""
Entrypoint. Long-polls Telegram for messages in the group.

Flow: reply to a message and tag the bot -> it reads the replied-to message,
extracts a meeting (date/time/topic/who/where) via extractor.py, and posts a
preview with a "Set" button. Tapping it inserts the event on the boss's
Google Calendar via calendar_client.py.
"""

import logging
import sys
import uuid

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import Application, CallbackQueryHandler, ContextTypes, MessageHandler, filters

from calendar_client import build_service, insert_event
from config import load_settings
from extractor import extract_event

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("calendar_bot")

# uuid -> extracted event dict, awaiting a tap on "Set". In-memory only: a
# pending preview is lost if the bot restarts before it's tapped.
PENDING_EVENTS = {}


def _bilingual(event, field, missing="Not specified / Не указано"):
    en, ru = event.get(f"{field}_en"), event.get(f"{field}_ru")
    if not en or not ru:
        return missing
    return f"{en} / {ru}"


def format_preview(event):
    lines = [
        "📅 *Event preview*",
        f"🗓 Date: {event['date']}",
        f"🕐 Time: {event['time']}  ({event['duration_minutes']} min)",
        f"📝 Topic: {_bilingual(event, 'topic')}",
        f"👤 With: {_bilingual(event, 'with_whom')}",
        f"📍 Location: {_bilingual(event, 'location')}",
    ]
    return "\n".join(lines)


async def handle_tag(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.message
    bot_username = context.bot_data["bot_username"]

    if not message or not message.text or f"@{bot_username}".lower() not in message.text.lower():
        return
    if not message.reply_to_message or not message.reply_to_message.text:
        await message.reply_text("Tag me on a reply to the message that has the meeting details.")
        return

    settings = context.bot_data["settings"]
    original_text = message.reply_to_message.text
    reference_dt = message.date.astimezone(settings.timezone)

    try:
        event = extract_event(
            original_text,
            reference_dt,
            settings.default_duration_minutes,
            settings.openrouter_api_key,
            settings.openrouter_model,
        )
    except Exception:
        logger.exception("Extraction failed")
        await message.reply_text("Sorry, I couldn't process that message -- something went wrong.")
        return

    if not event.get("found"):
        await message.reply_text("I couldn't find a clear meeting (date & time) in that message.")
        return

    event_id = uuid.uuid4().hex[:8]
    PENDING_EVENTS[event_id] = event

    keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("✅ Set", callback_data=f"set:{event_id}")]])
    await message.reply_text(format_preview(event), parse_mode="Markdown", reply_markup=keyboard)


async def handle_set(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    event_id = query.data.split(":", 1)[1]
    event = PENDING_EVENTS.pop(event_id, None)
    if event is None:
        await query.edit_message_text(
            query.message.text + "\n\n⚠️ This preview expired (bot restarted) -- tag me again.",
            parse_mode="Markdown",
        )
        return

    settings = context.bot_data["settings"]
    try:
        service = build_service(settings.google_token_path)
        link = insert_event(service, settings.boss_calendar_id, event, settings.timezone)
    except Exception:
        logger.exception("Calendar insert failed")
        await query.edit_message_text(
            query.message.text + "\n\n❌ Failed to add to calendar -- see bot logs.",
            parse_mode="Markdown",
        )
        return

    await query.edit_message_text(
        query.message.text + f"\n\n✅ Added to calendar: {link}",
        parse_mode="Markdown",
    )


async def post_init(application: Application):
    me = await application.bot.get_me()
    application.bot_data["bot_username"] = me.username
    logger.info("Logged in as @%s", me.username)


def main():
    settings = load_settings()
    application = Application.builder().token(settings.telegram_bot_token).post_init(post_init).build()
    application.bot_data["settings"] = settings

    application.add_handler(MessageHandler(filters.REPLY & filters.TEXT, handle_tag))
    application.add_handler(CallbackQueryHandler(handle_set, pattern=r"^set:"))

    logger.info("Starting long polling...")
    application.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
