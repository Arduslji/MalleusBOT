import re
import os
import datetime
import logging
from telegram import Update, MessageOriginChannel
from telegram.ext import Application, MessageHandler, filters, ContextTypes
from telegram.error import TelegramError

# --- Configurazione del Bot ---
AUTHORIZED_CHAT_IDS = [-1001299487305]  # Metti qui il tuo ID (o lista di ID) numerici
FORBIDDEN_KEYWORDS_NAME = [
    'porn', 'sex', 'xxx', 'adult', 'nude', 'erotic', 'viagra', 'cialis',
    'onlyfans', 'ofans', 'private', 'channel', 'bot'
]
# Lista vuota se non hai parole scurrili da censurare
FORBIDDEN_KEYWORDS_MESSAGE = []

CLOSING_START_HOUR = 23
CLOSING_START_MINUTE = 0
CLOSING_END_HOUR = 9
CLOSING_END_MINUTE = 0

MAX_MESSAGE_LENGTH = 1200

# Lista degli ID dei canali da cui bloccare gli inoltri
BLOCKED_FORWARD_CHANNEL_IDS = []

# --- Logging di base ---
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)

def has_forbidden_chars(text: str) -> bool:
    """Controlla se ci sono caratteri ebraici, arabi o cinesi."""
    return bool(re.search(r'[\u0590-\u06FF\u4E00-\u9FFF]', text))

def contains_forbidden_keywords(text: str, keywords: list[str]) -> bool:
    """Controlla parole chiave proibite (case‑insensitive)."""
    text_lower = text.lower()
    return any(kw.lower() in text_lower for kw in keywords)

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.from_user:
        return

    chat_id = update.message.chat_id
    msg_id = update.message.message_id
    user = update.message.from_user
    text = update.message.text or ""

    # 1) Solo chat autorizzate
    if chat_id not in AUTHORIZED_CHAT_IDS:
        return

    full_name = user.full_name or "Utente Sconosciuto"
    username = user.username
    user_idf = f"{full_name} (@{username})" if username else full_name

    # 2) Se è admin/creator, esentato
    try:
        member = await context.bot.get_chat_member(chat_id, user.id)
        if member.status in ["administrator", "creator"]:
            return
    except TelegramError:
        return

    # 3) Controllo forward da canale
    origin = getattr(update.message, 'forward_origin', None)
    if isinstance(origin, MessageOriginChannel):
        fwd_id = origin.chat.id
        if fwd_id in BLOCKED_FORWARD_CHANNEL_IDS:
            try:
                await context.bot.delete_message(chat_id, msg_id)
                has_link = any(e.type in ['url', 'text_link'] for e in (update.message.entities or []))
                warning = (
                    f"**Attenzione {full_name}!** "
                    + ("Inoltri di link da questo canale non sono consentiti."
                       if has_link else
                       "I messaggi inoltrati da questo canale non sono consentiti.")
                )
                await context.bot.send_message(chat_id, warning, parse_mode='Markdown')
            except TelegramError as e:
                if "not enough rights" in str(e).lower():
                    context.application.logger.warning("Permessi mancanti per delete/send_message")
            return

    # 4) Orario di chiusura
    now = datetime.datetime.now().time()
    start = datetime.time(CLOSING_START_HOUR, CLOSING_START_MINUTE)
    end = datetime.time(CLOSING_END_HOUR, CLOSING_END_MINUTE)
    if (start < end and start <= now < end) or (start >= end and (now >= start or now < end)):
        try:
            await context.bot.delete_message(chat_id, msg_id)
            await context.bot.send_message(
                chat_id,
                "La chat è chiusa in questo momento. I messaggi sono disabilitati.",
                parse_mode='Markdown'
            )
        except TelegramError as e:
            if "not enough rights" in str(e).lower():
                context.application.logger.warning("Permessi mancanti per delete/send_message")
        return

    # 5) Lunghezza massima
    if len(text) > MAX_MESSAGE_LENGTH:
        try:
            await context.bot.delete_message(chat_id, msg_id)
            await context.bot.send_message(
                chat_id,
                f"{full_name}, il tuo messaggio è troppo lungo ({len(text)}/{MAX_MESSAGE_LENGTH}).",
                parse_mode='Markdown'
            )
        except TelegramError as e:
            if "not enough rights" in str(e).lower():
                context.application.logger.warning("Permessi mancanti per delete/send_message")
        return

    # 6) Parole scurrili nel messaggio
    if contains_forbidden_keywords(text, FORBIDDEN_KEYWORDS_MESSAGE):
        try:
            await context.bot.delete_message(chat_id, msg_id)
            await context.bot.send_message(
                chat_id,
                f"**Ammonizione per {full_name}!** Linguaggio non appropriato.",
                parse_mode='Markdown'
            )
        except TelegramError as e:
            if "not enough rights" in str(e).lower():
                context.application.logger.warning("Permessi mancanti per delete/send_message")
        return

    # 7) Parole proibite in nome/username
    if contains_forbidden_keywords(user_idf, FORBIDDEN_KEYWORDS_NAME):
        try:
            await context.bot.delete_message(chat_id, msg_id)
            await context.bot.ban_chat_member(chat_id, user.id)
            await context.bot.send_message(
                chat_id,
                f"L'utente {user_idf} è stato rimosso per termini non consentiti.",
                parse_mode='Markdown'
            )
        except TelegramError as e:
            if "not enough rights" in str(e).lower():
                context.application.logger.warning("Permessi mancanti per ban/send_message")
        return

    # 8) Caratteri ebraici/arabi/cinesi nel nome
    if has_forbidden_chars(full_name):
        try:
            await context.bot.delete_message(chat_id, msg_id)
            await context.bot.ban_chat_member(chat_id, user.id)
            await context.bot.send_message(
                chat_id,
                f"Damnatus est de blasphemia et brachio saeculari tradimus 🔥 {full_name}",
                parse_mode='Markdown'
            )
        except TelegramError as e:
            if "not enough rights" in str(e).lower():
                context.application.logger.warning("Permessi mancanti per ban/send_message")
        return

async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Gestore globale delle eccezioni."""
    # Usa il logger di Application (v21+)
    context.application.logger.error(
        "Exception while handling an update", exc_info=context.error
    )

def main():
    print("DEBUG: Entrato in main()")
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    if not token:
        print("ERRORE: TELEGRAM_BOT_TOKEN NON TROVATO")
        return

    print("DEBUG: Token trovato, avvio Application...")
    application = Application.builder().token(token).build()
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    application.add_error_handler(error_handler)

    print("DEBUG: Handler registrati, lancio run_polling()")
    application.run_polling()
    print("DEBUG: run_polling() è terminato")

if __name__ == '__main__':
    main()
