import re
import os
import datetime
import time
import threading
from zoneinfo import ZoneInfo
import asyncio
from collections import deque
import logging
import sys # Importa sys per sys.exit()

from telegram import Update
from telegram.ext import Application, MessageHandler, CommandHandler, filters, ContextTypes
from telegram.error import TelegramError, InvalidToken, NetworkError # Aggiunti InvalidToken e NetworkError
from flask import Flask, request # Manteniamo Flask per la compatibilità Replit/home route
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

# --- Rimuove la variabile TZ se presente (Replit) ---
# Necessario per Replit ma può causare problemi su altri host come Render se impostata
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
    # Su Render, questa route non sarà toccata da Telegram, ma serve per un check di base del servizio
    return "Bot Telegram in esecuzione!"

# --- Configurazione ---
AUTHORIZED_CHAT_IDS = [-1002254924397] # *** Ricorda di verificare e aggiornare questo Chat ID ***

FORBIDDEN_KEYWORDS_NAME = [
    'porn', 'sex', 'xxx', 'adult', 'nude', 'erotic', 'viagra', 'cialis',
    'onlyfans', 'ofans', 'private', 'channel', 'bot'
]
FORBIDDEN_KEYWORDS_MESSAGE = [] # Puoi aggiungere qui parole chiave da bannare nei messaggi

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
BLOCKED_CHANNEL_USERNAMES = [] # Esempio: ['usernamecanale1', 'usernamecanale2']
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
# Modifica il tipo di flood_timer da threading.Timer a asyncio.Task
flood_timer: asyncio.Task = None 

FLOOD_THRESHOLD = 10      # messaggi
FLOOD_WINDOW = 3          # secondi
FLOOD_DURATION = 180      # secondi (3 minuti)

# --- Variabili globali per il bot ---
_bot_app: Application = None

# --- Antiflood helper ---
async def _deactivate_flood(chat_id=None):
    global flood_active, flood_timer
    flood_active = False
    if flood_timer:
        flood_timer.cancel() # Cancella il task esistente se presente
    flood_timer = None
    if chat_id:
        await send_chat_status_message(_bot_app.bot, "  ⚔️ Modalità difensiva terminata ⚔️ \n\n☀️ La discussione può riprendere ☀️", chat_id)
    logging.debug(f"Antiflood disattivato in chat {chat_id}")

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

    # Nuovo log per tracciare ogni messaggio processato
    logging.debug(f"Processando messaggio da {update.effective_user.id} (@{update.effective_user.username}) in chat {update.effective_chat.id}. Tipo update: {update.update_id}")

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

    # Log cruciale per lo stato admin dell'utente
    logging.debug(f"Utente {user.id} in chat {chat_id}: is_admin={is_admin}")

    if not is_admin:
        now = time.time()
        flood_queue.append(now)
        while flood_queue and flood_queue[0] < now - FLOOD_WINDOW:
            flood_queue.popleft()

        if not flood_active and len(flood_queue) >= FLOOD_THRESHOLD:
            flood_active = True
            await context.bot.send_message(chat_id, "⚔️ Chat sotto attacco, modalità difensiva attivata! ⚔️ \n\n    ⏳ La discussione viene sospesa per 3 minuti ⏳ \n\n      🧹 Qualunque messaggio sarà cancellato 🧹")
            # Avvia il timer antiflood utilizzando asyncio.create_task per un'esecuzione asincrona
            flood_timer = asyncio.create_task(
                asyncio.sleep(FLOOD_DURATION)
            )
            # Aggiungi una callback per quando il task del timer è completo
            flood_timer.add_done_callback(
                lambda t: asyncio.create_task(_deactivate_flood(chat_id))
            )
            logging.debug(f"Antiflood attivato in chat {chat_id}, timer avviato")
            
        if flood_active:
            try:
                await context.bot.delete_message(chat_id, msg_id)
                logging.debug(f"Messaggio {msg_id} cancellato per antiflood in chat {chat_id}")
            except TelegramError as e:
                logging.warning(f"Impossibile cancellare messaggio {msg_id} per antiflood in chat {chat_id}: {e}")
            return # Ferma l'elaborazione del messaggio se l'antiflood è attivo

    # Solo i non-admin vengono controllati dalle regole successive
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

    # Controlli sul testo del messaggio (solo per non-admin)
    text = update.message.text or update.message.caption or ""
    if not is_admin and len(text) > MAX_MESSAGE_LENGTH:
        logging.debug(f"Messaggio {msg_id} troppo lungo ({len(text)} chars) in chat {chat_id}. Max: {MAX_MESSAGE_LENGTH}. Cancellazione.")
        await context.bot.send_message(chat_id, text=f"❌ {user.full_name}, il tuo messaggio è troppo lungo ({len(text)} caratteri). Il limite massimo è {MAX_MESSAGE_LENGTH} caratteri. Il messaggio è stato rimosso 📜🔥")
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

async def schedule_announce(message: str):
    await send_chat_status_message(_bot_app.bot, message)
    logging.debug(f"Annuncio programmato: '{message}' inviato.")

def run_flask_server():
    # Questa funzione è solo per Replit (polling mode) e per mantenere la route '/' per un health check.
    # Non gestisce il webhook di Telegram su Render.
    port = int(os.getenv("PORT", 8080))
    logging.debug(f"Avvio Flask server sulla porta {port} (per Replit keep-alive/Render health check)")
    flask_app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False)
    logging.debug("Flask server avviato.")


# --- La funzione main deve essere asincrona ---
async def main():
    global _bot_app

    token = os.getenv("TELEGRAM_BOT_TOKEN")
    if not token:
        logging.error("Errore: token TELEGRAM_BOT_TOKEN non trovato. Assicurati che sia nelle variabili d'ambiente di Replit Secrets o Render.")
        os._exit(1)

    application = Application.builder().token(token).build()
    _bot_app = application
    
    # Inizializzazione dell'Application PTB
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

    # --- INIZIO BLOCCO DI AVVIO CONDIZIONALE PER RENDER ---
    if os.getenv("RENDER"):
        WEBHOOK_URL = os.getenv("RENDER_EXTERNAL_HOSTNAME")
        if WEBHOOK_URL:
            WEBHOOK_URL = f"https://{WEBHOOK_URL}/webhook"
        else:
            logging.error("Errore: Variabile d'ambiente RENDER_EXTERNAL_HOSTNAME non trovata su Render.")
            os._exit(1)

        PORT = int(os.getenv("PORT", 8080))
        ### <<< INSERISCI QUI >>> ###
        # SICUREZZA: Recupera il secret token del webhook
        # Questa riga è FONDAMENTALE e deve essere prima dell'uso di webhook_secret_token
        webhook_secret_token = os.getenv("WEBHOOK_SECRET_TOKEN")
        if not webhook_secret_token:
            logging.critical("Errore: WEBHOOK_SECRET_TOKEN non impostato nelle variabili d'ambiente di Render. Necessario per la modalità webhook.")
            sys.exit(1)
        ### <<< FINE INSERIMENTO >>> ###
        
        logging.debug(f"Ambiente Render rilevato. Avvio bot in modalità webhook.")
        logging.debug(f"Webhook URL: {WEBHOOK_URL}, Porta di ascolto: {PORT}")

        # **Questa è la modifica chiave per la Soluzione 1:**
        # Avvia il server webhook integrato di PTB.
        # PTB gestirà la ricezione del webhook e il passaggio degli update.
        await application.updater.start_webhook(
            listen="0.0.0.0",
            port=PORT,
            url_path="webhook", # Importante: SENZA lo slash iniziale qui per url_path di PTB
            webhook_url=WEBHOOK_URL,
            secret_token=webhook_secret_token,
            allowed_updates=Update.ALL_TYPES,
            drop_pending_updates=True
        )

        logging.debug("Application in webhook avviata su Render con PTB integrato.")

        # Mantiene il bot in esecuzione indefinitamente in attesa di aggiornamenti
        await application.updater.idle()

    # --- ELSE per Replit (o ambiente locale di sviluppo) ---
    else:
        logging.debug("Ambiente Replit/locale rilevato, avvio bot in modalità polling.")
        # Avvia il server Flask in un thread separato per il keep-alive su Replit
        threading.Thread(target=run_flask_server, daemon=True).start()
        # Avvia l'Application in modalità polling
        await application.run_polling(allowed_updates=Update.ALL_TYPES, drop_pending_updates=True)
        logging.debug("Application in polling avviata su Replit.")

    logging.debug("L'applicazione Telegram Bot è in esecuzione (o in attesa di richieste).")


if __name__ == '__main__':
    try:
        # Avvia la funzione main asincrona
        asyncio.run(main())
    except KeyboardInterrupt:
        logging.info("Bot interrotto manualmente.")
    except Exception as e:
        logging.critical(f"Errore critico nell'esecuzione del bot: {e}", exc_info=True)
