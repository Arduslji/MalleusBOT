import re
import os
import datetime
import time
import threading
from zoneinfo import ZoneInfo
import asyncio
from collections import deque
import logging # <-- SCOMMENTATO E ORA USATO CORRETTAMENTE

from telegram import Update
from telegram.ext import Application, MessageHandler, CommandHandler, filters, ContextTypes
from telegram.error import TelegramError
from flask import Flask, request
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

# --- Rimuove la variabile TZ se presente (Replit) ---
if 'TZ' in os.environ:
    os.environ.pop('TZ')
time.tzset()

# --- Flask per mantenere vivo il bot su Replit E gestire webhook su Render ---
flask_app = Flask(__name__)

@flask_app.route('/')
def home():
    logging.debug("Richiesta GET alla root '/' ricevuta.")
    return "Bot Telegram in esecuzione!"

@flask_app.route('/webhook', methods=['POST'])
async def telegram_webhook_handler():
    logging.debug("Richiesta POST a '/webhook' ricevuta. Processando...")
    if not request.is_json:
        logging.error("Richiesta webhook non è JSON.")
        return "Bad Request: Not JSON", 400

    update_dict = request.get_json()
    if not update_dict:
        logging.error("Richiesta webhook JSON vuota.")
        return "Bad Request: Empty JSON", 400

    try:
        update = Update.de_json(update_dict, _bot_app.bot)
    except Exception as e:
        logging.error(f"Errore durante la creazione dell'Update dal JSON: {e}")
        return "Internal Server Error: Failed to parse update", 500

    try:
        asyncio.create_task(_bot_app.process_update(update))
    except Exception as e:
        logging.error(f"Errore durante l'elaborazione dell'update da parte dell'Application: {e}")
        return "Internal Server Error: Failed to process update", 500

    return "OK", 200

# --- Configurazione ---
AUTHORIZED_CHAT_IDS = [-1002254924397] # *** Ricorda di verificare e aggiornare questo Chat ID ***

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
flood_timer: threading.Timer = None

FLOOD_THRESHOLD = 10      # messaggi
FLOOD_WINDOW = 3          # secondi
FLOOD_DURATION = 180      # secondi (3 minuti)

# --- Variabili globali per il bot e l'event loop ---
_bot_app: Application = None
_bot_loop = None

# --- Antiflood helper ---
async def _deactivate_flood(chat_id=None):
    global flood_active, flood_timer
    flood_active = False
    if flood_timer:
        flood_timer.cancel()
    flood_timer = None
    if chat_id:
        await send_chat_status_message(_bot_app.bot, "  ⚔️ Modalità difensiva terminata ⚔️ \n\n☀️ La discussione può riprendere ☀️", chat_id)

async def handle_stopantiflood(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global flood_active, flood_timer
    chat_id = update.effective_chat.id
    if chat_id not in AUTHORIZED_CHAT_IDS:
        logging.debug(f"Comando /stopantiflood da chat non autorizzata: {chat_id}")
        return
    member = await context.bot.get_chat_member(chat_id, update.effective_user.id)
    if member.status in ("administrator", "creator"):
        await _deactivate_flood(chat_id)
        logging.debug(f"/stopantiflood eseguito da admin in chat {chat_id}")
    else:
        logging.debug(f"/stopantiflood tentato da utente non admin in chat {chat_id}")

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global flood_active, flood_queue, flood_timer

    if not update.message:
        return

    chat_id = update.effective_chat.id
    msg_id = update.message.message_id
    user = update.message.from_user

    if chat_id not in AUTHORIZED_CHAT_IDS:
        logging.debug(f"Messaggio da chat non autorizzata: {chat_id}")
        return

    is_admin = False
    if update.message.sender_chat: # Messaggio da canale linkato (sempre admin in pratica)
        is_admin = True
    elif user:
        try:
            member = await context.bot.get_chat_member(chat_id, user.id)
            is_admin = member.status in ("administrator", "creator")
        except TelegramError as e:
            logging.warning(f"Impossibile ottenere stato membro per {user.id} in chat {chat_id}: {e}")
            pass

    if not is_admin:
        now = time.time()
        flood_queue.append(now)
        while flood_queue and flood_queue[0] < now - FLOOD_WINDOW:
            flood_queue.popleft()

        if not flood_active and len(flood_queue) >= FLOOD_THRESHOLD:
            flood_active = True
            await context.bot.send_message(chat_id, "⚔️ Chat sotto attacco, modalità difensiva attivata! ⚔️ \n\n    ⏳ La discussione viene sospesa per 3 minuti ⏳ \n\n      🧹 Qualunque messaggio sarà cancellato 🧹")
            current_loop = _bot_loop if _bot_loop else asyncio.get_event_loop()
            if current_loop.is_running():
                flood_timer = threading.Timer(FLOOD_DURATION, lambda: asyncio.run_coroutine_threadsafe(_deactivate_flood(chat_id), current_loop))
                flood_timer.start()
            else:
                logging.warning("Impossibile avviare il timer antiflood: l'event loop non è in esecuzione.")
            logging.debug(f"Antiflood attivato in chat {chat_id}, timer avviato")
        if flood_active:
            try:
                await context.bot.delete_message(chat_id, msg_id)
                logging.debug(f"Messaggio {msg_id} cancellato per antiflood in chat {chat_id}")
            except TelegramError as e:
                logging.warning(f"Impossibile cancellare messaggio {msg_id} per antiflood in chat {chat_id}: {e}")
            return

    if user and not is_admin:
        name = user.full_name
        uname = user.username
        identifier = f"{name} (@{uname})" if uname else name

        if has_forbidden_chars(name):
            logging.debug(f"Utente {identifier} con nome contenente caratteri non latini. Tentativo di blocco.")
            try:
                await context.bot.delete_message(chat_id, msg_id)
                await context.bot.ban_chat_member(chat_id, user.id)
                await context.bot.send_message(
                    chat_id,
                    text=f"🔥 𝔇𝔞𝔪𝔫𝔞𝔱𝔲𝔰 𝔢𝔰𝔱 𝔡𝔢 𝔟𝔩𝔞𝔰𝔭𝔥𝔢𝔪𝔦𝔞 𝔢𝔱 𝔟𝔯𝔞𝔠𝔥𝔦𝔬 𝔰𝔞𝔢𝔠𝔲𝔩𝔞𝔯𝔦 𝔱𝔯𝔞𝔡𝔦𝔪𝔲𝔰 🔥 **{name}**",
                    parse_mode='Markdown'
                )
                logging.debug(f"Utente {identifier} bannato e messaggio cancellato per caratteri non latini.")
            except TelegramError as e:
                logging.warning(f"Impossibile bannare {identifier} o cancellare messaggio per caratteri non latini in chat {chat_id}: {e}")
            return

        if identifier and has_forbidden_keywords_name(identifier):
            logging.debug(f"Utente {identifier} con nome contenente keyword proibite. Tentativo di blocco.")
            try:
                await context.bot.delete_message(chat_id, msg_id)
                await context.bot.ban_chat_member(chat_id, user.id)
                await context.bot.send_message(
                    chat_id,
                    text=f"🚫 Utente **{identifier}** rimosso per termini non consentiti nel nome.",
                    parse_mode='Markdown'
                )
                logging.debug(f"Utente {identifier} bannato e messaggio cancellato per keyword proibite nel nome.")
            except TelegramError as e:
                logging.warning(f"Impossibile bannare {identifier} o cancellare messaggio per keyword proibite nel nome in chat {chat_id}: {e}")
            return

    text = update.message.text or update.message.caption or ""
    if not is_admin and len(text) > MAX_MESSAGE_LENGTH:
        await context.bot.send_message(chat_id, text=f"❌ {user.full_name}, il tuo messaggio è troppo lungo ({len(text)} caratteri). Il limite massimo è {MAX_MESSAGE_LENGTH} caratteri. Il messaggio è stato rimosso 📜🔥")
        logging.debug(f"Messaggio {msg_id} cancellato per lunghezza eccessiva in chat {chat_id}")
        try:
            await context.bot.delete_message(chat_id, msg_id)
        except TelegramError as e:
            logging.warning(f"Impossibile cancellare messaggio {msg_id} per lunghezza eccessiva in chat {chat_id}: {e}")
        return

    ents = update.message.entities or update.message.caption_entities
    if not is_admin and contains_blocked_web_domain(ents, text):
        logging.debug(f"Messaggio {msg_id} contiene dominio web bloccato. Tentativo di cancellazione.")
        await context.bot.send_message(chat_id, text=f"🚫 {user.full_name}, sei pregato di non portare nella nostra chat la spazzatura della falsa controinformazione. Il contenuto è stato rimosso 🚽")
        try:
            await context.bot.delete_message(chat_id, msg_id)
            logging.debug(f"Messaggio {msg_id} cancellato per dominio web bloccato in chat {chat_id}")
        except TelegramError as e:
            logging.warning(f"Impossibile cancellare messaggio {msg_id} per dominio web bloccato in chat {chat_id}: {e}")
        return

    if not is_admin and text and has_forbidden_keywords_message(text):
        logging.debug(f"Messaggio {msg_id} contiene parole chiave vietate. Tentativo di cancellazione.")
        try:
            await context.bot.delete_message(chat_id, msg_id)
            logging.debug(f"Messaggio {msg_id} cancellato per parole chiave vietate in chat {chat_id}")
        except TelegramError as e:
            logging.warning(f"Impossibile cancellare messaggio {msg_id} per parole chiave vietate in chat {chat_id}: {e}")
        return

async def send_chat_status_message(bot, message: str, chat_id=None):
    if chat_id:
        try:
            await bot.send_message(chat_id, text=message)
        except TelegramError as e:
            logging.warning(f"Impossibile inviare messaggio a chat {chat_id}: {e}")
            pass
    else:
        for cid in AUTHORIZED_CHAT_IDS:
            try:
                await bot.send_message(cid, text=message)
            except TelegramError as e:
                logging.warning(f"Impossibile inviare messaggio a chat {cid}: {e}")
                pass

def schedule_announce(message: str):
    async def announce():
        await send_chat_status_message(_bot_app.bot, message)
    current_loop = _bot_loop if _bot_loop else asyncio.get_event_loop()
    if current_loop.is_running():
        current_loop.call_soon_threadsafe(lambda: asyncio.create_task(announce()))
    else:
        logging.warning("Event loop non avviato o non in esecuzione per schedule_announce. Ignorando l'annuncio.")

def run_flask_server():
    port = int(os.getenv("PORT", 8080))
    logging.debug(f"Avvio Flask server sulla porta {port} (per Replit keep-alive)")
    flask_app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False)
    logging.debug("Flask server avviato.")

def main():
    global _bot_app, _bot_loop

    # --- AGGIUNTO: Configurazione base del logging ---
    logging.basicConfig(level=logging.DEBUG,
                        format='%(asctime)s - %(levelname)s - %(message)s',
                        handlers=[logging.StreamHandler()])
    # -----------------------------------------------

    token = os.getenv("TELEGRAM_BOT_TOKEN")
    if not token:
        logging.error("Errore: token TELEGRAM_BOT_TOKEN non trovato. Assicurati che sia nelle variabili d'ambiente di Replit Secrets o Render.")
        os._exit(1)

    application = Application.builder().token(token).build()
    _bot_app = application
    
    try:
        _bot_loop = asyncio.get_event_loop()
    except RuntimeError:
        _bot_loop = asyncio.new_event_loop()
        asyncio.set_event_loop(_bot_loop)
    logging.debug(f"Event loop (_bot_loop) impostato: {_bot_loop}")
    
    # --- RIGHE PER INIZIALIZZAZIONE PTB (MANTENUTE QUI) ---
    logging.debug("Inizializzazione dell'Application PTB...")
    _bot_loop.run_until_complete(application.initialize())
    logging.debug("Application PTB inizializzata.")
    # ---------------------------------------------------

    application.add_handler(CommandHandler("stopantiflood", handle_stopantiflood))
    application.add_handler(MessageHandler(filters.ALL & ~filters.COMMAND, handle_message))

    # Scheduler di apertura/chiusura
    scheduler.add_job(
        lambda: schedule_announce(OPENING_MESSAGE),
        CronTrigger(hour=CLOSING_END_HOUR, minute=CLOSING_END_MINUTE, timezone=ZoneInfo("Europe/Rome")),
        name="Chat Opening Announcement"
    )
    scheduler.add_job(
        lambda: schedule_announce(CLOSING_MESSAGE),
        CronTrigger(hour=CLOSING_START_HOUR, minute=CLOSING_START_MINUTE, timezone=ZoneInfo("Europe/Rome")),
        name="Chat Closing Announcement"
    )
    scheduler.start()
    logging.debug("BackgroundScheduler avviato")

    # --- INIZIO BLOCCO DI AVVIO CONDIZIONALE PER REPLIT / RENDER ---
    if os.getenv("RENDER"):
        WEBHOOK_URL = os.getenv("RENDER_EXTERNAL_HOSTNAME")
        if WEBHOOK_URL:
            WEBHOOK_URL = f"https://{WEBHOOK_URL}/webhook"
        else:
            logging.error("Errore: Variabile d'ambiente RENDER_EXTERNAL_HOSTNAME non trovata su Render.")
            os._exit(1)

        PORT = int(os.getenv("PORT", 8080))

        logging.debug(f"Ambiente Render rilevato. Avvio bot in modalità webhook.")
        logging.debug(f"Webhook URL: {WEBHOOK_URL}, Porta di ascolto: {PORT}")

        try:
            logging.debug("Tentativo di avviare application.run_webhook con app=flask_app...")
            application.run_webhook(
                listen="0.0.0.0",
                port=PORT,
                url_path="/webhook",
                webhook_url=WEBHOOK_URL,
                app=flask_app,
                drop_pending_updates=True
            )
            logging.debug("Application in webhook avviata su Render con Flask integrato.")

        except TypeError as e:
            logging.warning(f"application.run_webhook() non supporta 'app': {e}. Utilizzo del fallback.")
            
            logging.debug("Tentativo di impostare il webhook su Telegram (async) via PTB...")
            _bot_loop.run_until_complete(application.bot.set_webhook(url=WEBHOOK_URL, allowed_updates=Update.ALL_TYPES))
            logging.debug("Webhook impostato (manualmente/fallback) per PTB.")

            logging.debug("Avvio del server Flask nel thread principale per gestire i webhook.")
            flask_app.run(host="0.0.0.0", port=PORT, debug=False, use_reloader=False)
            logging.debug("Flask server avviato e in ascolto.")

    else:
        logging.debug("Ambiente Replit rilevato, avvio bot in modalità polling...")
        threading.Thread(target=run_flask_server, daemon=True).start()
        application.run_polling(allowed_updates=Update.ALL_TYPES, drop_pending_updates=True)
        logging.debug("Application in polling avviata su Replit.")

    logging.debug("L'applicazione Telegram Bot è in esecuzione (o in attesa di richieste).")


if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        logging.info("Bot interrotto manualmente.")
    except Exception as e:
        logging.critical(f"Errore critico nell'esecuzione del bot: {e}", exc_info=True)
