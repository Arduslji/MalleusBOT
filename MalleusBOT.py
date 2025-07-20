import re
import os
import datetime
import time
import threading
from zoneinfo import ZoneInfo
import asyncio
from collections import deque
import logging
import sys  # Importa sys per sys.exit()

from telegram import Update
from telegram.ext import Application, MessageHandler, CommandHandler, filters, ContextTypes
from telegram.error import TelegramError, InvalidToken, NetworkError  # Aggiunti InvalidToken e NetworkError
from flask import Flask, request  # Manteniamo Flask per la compatibilità Replit/home route
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

# --- Rimuove la variabile TZ se presente (Replit) ---
if 'TZ' in os.environ:
    os.environ.pop('TZ')

# --- Configurazione base del logging (IMPORTANTE: deve essere all'inizio del file o in main) ---
logging.basicConfig(level=logging.DEBUG,
                    format='%(asctime)s - %(levelname)s - %(message)s',
                    handlers=[logging.StreamHandler()])

# --- Flask per mantenere vivo il bot su Replit (NON per webhook su Render) ---
flask_app = Flask(__name__)

@flask_app.route('/')
def home():
    logging.debug("Richiesta GET alla root '/' ricevuta.")
    return "Bot Telegram in esecuzione!"

# --- Configurazione ---
AUTHORIZED_CHAT_IDS = [-1002254924397]
FORBIDDEN_KEYWORDS_NAME = [
    'porn', 'sex', 'xxx', 'adult', 'nude', 'erotic', 'viagra', 'cialis',
    'onlyfans', 'ofans', 'private', 'channel', 'bot'
]
FORBIDDEN_KEYWORDS_MESSAGE = []
CLOSING_START_HOUR = 23
CLOSING_START_MINUTE = 0
CLOSING_END_HOUR = 9
CLOSING_END_MINUTE = 0
OPENING_MESSAGE = "🌞 ℭ𝔦𝔯𝔠𝔲𝔩𝔲𝔰 𝔡𝔦𝔰𝔭𝔲𝔱𝔞𝔱𝔦𝔬𝔫𝔦𝔰 𝔫𝔲𝔫𝔠 𝔞𝔭𝔢𝔯𝔱𝔲𝔰 𝔢𝔰𝔱! 🌞"
CLOSING_MESSAGE = "⌛️ 𝔇𝔦𝔰𝔭𝔲𝔱𝔞𝔱𝔦𝔬 𝔫𝔲𝔫𝔠 𝔣𝔦𝔫𝔦𝔱𝔞 𝔢𝔰𝔱. 𝔑𝔬𝔠𝔱𝔢𝔪 𝔮𝔲𝔦𝔢𝔱𝔞𝔪 𝔞𝔤𝔦𝔱𝔢 🌙"
MAX_MESSAGE_LENGTH = 1200
BLOCKED_FORWARD_CHANNEL_IDS = [
    -1001249969478, -1001382991987, -1001185400784, -1001450908211,
    -1001458150284, -1001437761372, -1001281633465, -1001272270169,
    -1002002355451, -1001245777992
]
BLOCKED_CHANNEL_USERNAMES = []
BLOCKED_WEB_DOMAINS = [
    'byoblu.com', 'phishing.net', 'casinogratis.xyz',
    'scommesse.it', 'linkdannoso.ru', 'offertespeciali.info'
]
# Scheduler in background
scheduler = BackgroundScheduler(timezone=ZoneInfo("Europe/Rome"))

# --- Funzioni di controllo ---
def has_forbidden_chars(name: str) -> bool:
    return bool(re.search(r'[\u0590-\u05FF\u0600-\u06FF\u4E00-\u9FFF]', name))

def has_forbidden_keywords_name(name: str) -> bool:
    return any(k in name.lower() for k in FORBIDDEN_KEYWORDS_NAME)

def has_forbidden_keywords_message(text: str) -> bool:
    return any(k in text.lower() for k in FORBIDDEN_KEYWORDS_MESSAGE)

def contains_blocked_web_domain(entities, text) -> bool:
    t = (text or "").lower()
    for e in entities or []:
        if e.type in ('url', 'text_link'):
            u = (t[e.offset:e.offset + e.length] if e.type == 'url' else e.url).lower()
            if any(d in u for d in BLOCKED_WEB_DOMAINS):
                return True
        elif e.type in ('tg_url', 'mention') and BLOCKED_CHANNEL_USERNAMES:
            uname = ""
            if e.type == 'tg_url' and e.url:
                m = re.search(r'(?:domain=|t\.me/)([^/&?]+)', e.url, re.I)
                if m: uname = m.group(1).lower()
            elif e.type == 'mention':
                uname = t[e.offset:e.offset + e.length].lstrip('@')
            if uname in [x.lower() for x in BLOCKED_CHANNEL_USERNAMES]:
                return True
    return False

# --- ANTIFLOOD STATE & CONFIG ---
flood_active = False
flood_queue = deque()
flood_timer: asyncio.Task = None  # Modificato in asyncio.Task
FLOOD_THRESHOLD = 10
FLOOD_WINDOW = 3
FLOOD_DURATION = 180

# --- Variabili globali per il bot ---
_bot_app: Application = None

# --- Antiflood helper e handle_message, send_chat_status_message, schedule_announce …
# (mantieni intatte tutte le funzioni e la logica come nel tuo codice originale)

async def run_flask_server():
    port = int(os.getenv("PORT", 8080))
    flask_app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False)

async def main():
    global _bot_app

    token = os.getenv("TELEGRAM_BOT_TOKEN")
    if not token:
        logging.critical("Errore: TELEGRAM_BOT_TOKEN non impostato.")
        sys.exit(1)

    application = Application.builder().token(token).build()
    _bot_app = application

    logging.debug("Inizializzazione dell'Application PTB...")
    await application.initialize()
    logging.debug("Application PTB inizializzata.")

    application.add_handler(CommandHandler("stopantiflood", handle_stopantiflood))
    application.add_handler(MessageHandler(filters.ALL & ~filters.COMMAND, handle_message))

    # Scheduler di apertura/chiusura
    scheduler.add_job(
        lambda: asyncio.create_task(schedule_announce(OPENING_MESSAGE)),
        CronTrigger(hour=CLOSING_END_HOUR, minute=CLOSING_END_MINUTE, timezone=ZoneInfo("Europe/Rome")),
        name="Chat Opening Announcement"
    )
    scheduler.add_job(
        lambda: asyncio.create_task(schedule_announce(CLOSING_MESSAGE)),
        CronTrigger(hour=CLOSING_START_HOUR, minute=CLOSING_START_MINUTE, timezone=ZoneInfo("Europe/Rome")),
        name="Chat Closing Announcement"
    )
    scheduler.start()
    logging.debug("BackgroundScheduler avviato")

    if os.getenv("RENDER"):
        WEBHOOK_URL = os.getenv("RENDER_EXTERNAL_HOSTNAME")
        if WEBHOOK_URL:
            WEBHOOK_URL = f"https://{WEBHOOK_URL}/webhook"
        else:
            logging.critical("Errore: RENDER_EXTERNAL_HOSTNAME non trovata.")
            sys.exit(1)

        PORT = int(os.getenv("PORT", 8080))
        webhook_secret_token = os.getenv("WEBHOOK_SECRET_TOKEN")
        if not webhook_secret_token:
            logging.critical("Errore: WEBHOOK_SECRET_TOKEN non impostato.")
            sys.exit(1)

        logging.debug(f"Webhook URL: {WEBHOOK_URL}, porta: {PORT}")

        # === CORREZIONE PTB v20+ ===
        await application.run_webhook(
            listen="0.0.0.0",
            port=PORT,
            path="webhook",
            webhook_url=WEBHOOK_URL,
            secret_token=webhook_secret_token,
            allowed_updates=Update.ALL_TYPES,
            drop_pending_updates=True
        )
        logging.debug("Application in webhook avviata su Render con PTB integrato.")

    else:
        logging.debug("Ambiente Replit/locale rilevato, avvio polling.")
        threading.Thread(target=run_flask_server, daemon=True).start()
        await application.run_polling(allowed_updates=Update.ALL_TYPES, drop_pending_updates=True)
        logging.debug("Application in polling avviata su Replit.")

if __name__ == '__main__':
    try:
        asyncio.run(main())
    except InvalidToken:
        logging.critical("Errore: TELEGRAM_BOT_TOKEN non valido.")
        sys.exit(1)
    except NetworkError as e:
        logging.critical(f"Errore di rete: {e}")
        sys.exit(1)
    except KeyboardInterrupt:
        logging.info("Bot interrotto manualmente.")
    except Exception as e:
        logging.critical(f"Errore critico inatteso: {e}", exc_info=True)
        sys.exit(1)
