import re
import os
import datetime
import time
import threading
from zoneinfo import ZoneInfo
import asyncio
from collections import deque

from telegram import Update
from telegram.ext import Application, MessageHandler, CommandHandler, filters, ContextTypes
from telegram.error import TelegramError
from flask import Flask
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

# --- Rimuove la variabile TZ se presente (Replit) ---
if 'TZ' in os.environ:
    os.environ.pop('TZ')
time.tzset()

# --- Flask per mantenere vivo il bot su Replit ---
flask_app = Flask(__name__)

@flask_app.route('/')
def home():
    return "Bot Telegram in esecuzione!"

@flask_app.route('/webhook', methods=['POST'])
def webhook():
    return "Webhook endpoint ready"

# --- Configurazione ---
AUTHORIZED_CHAT_IDS = [-1001299487305, -1002254924397] # *** Ricorda di verificare e aggiornare questo Chat ID ***

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
_bot_loop = None # Sarà impostato in main() dopo la creazione dell'Application

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
        return
    member = await context.bot.get_chat_member(chat_id, update.effective_user.id)
    if member.status in ("administrator", "creator"):
        await _deactivate_flood(chat_id)
        print(f"DEBUG: /stopantiflood eseguito da admin in chat {chat_id}")

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global flood_active, flood_queue, flood_timer

    if not update.message:
        return

    chat_id = update.effective_chat.id
    msg_id = update.message.message_id
    user = update.message.from_user

    if chat_id not in AUTHORIZED_CHAT_IDS:
        return

    is_admin = False
    if update.message.sender_chat:
        is_admin = True
    elif user:
        try:
            member = await context.bot.get_chat_member(chat_id, user.id)
            is_admin = member.status in ("administrator", "creator")
        except TelegramError as e:
            print(f"WARN: Impossibile ottenere stato membro per {user.id} in chat {chat_id}: {e}")
            pass

    if not is_admin:
        now = time.time()
        flood_queue.append(now)
        while flood_queue and flood_queue[0] < now - FLOOD_WINDOW:
            flood_queue.popleft()

        if not flood_active and len(flood_queue) >= FLOOD_THRESHOLD:
            flood_active = True
            await context.bot.send_message(chat_id, "⚔️ Chat sotto attacco, modalità difensiva attivata! ⚔️ \n\n   ⏳ La discussione viene sospesa per 3 minuti ⏳ \n\n      🧹 Qualunque messaggio sarà cancellato 🧹")
            # Assicurati che _bot_loop sia disponibile prima di tentare di usarlo
            current_loop = _bot_loop if _bot_loop else asyncio.get_event_loop()
            if current_loop.is_running(): # Verifica se l'event loop è effettivamente in esecuzione
                flood_timer = threading.Timer(FLOOD_DURATION, lambda: asyncio.run_coroutine_threadsafe(_deactivate_flood(chat_id), current_loop))
                flood_timer.start()
            else:
                print("WARN: Impossibile avviare il timer antiflood: l'event loop non è in esecuzione.")
            print(f"DEBUG: Antiflood attivato in chat {chat_id}, timer avviato")
        if flood_active:
            await context.bot.delete_message(chat_id, msg_id)
            print(f"DEBUG: Messaggio {msg_id} cancellato per antiflood in chat {chat_id}")
            return

    if user and not is_admin:
        name = user.full_name
        uname = user.username
        identifier = f"{name} (@{uname})" if uname else name

        if has_forbidden_chars(name):
            await context.bot.delete_message(chat_id, msg_id)
            await context.bot.ban_chat_member(chat_id, user.id)
            await context.bot.send_message(
                chat_id,
                text=f"🔥 𝔇𝔞𝔪𝔫𝔞𝔱𝔲𝔰 𝔢𝔰𝔱 𝔡𝔢 𝔟𝔩𝔞𝔰𝔭𝔥𝔢𝔪𝔦𝔞 𝔢𝔱 𝔟𝔯𝔞𝔠𝔥𝔦𝔬 𝔰𝔞𝔢𝔠𝔲𝔩𝔞𝔯𝔦 𝔱𝔯𝔞𝔡𝔦𝔪𝔲𝔰 🔥 **{name}**",
                parse_mode='Markdown'
            )
            return

        if identifier and has_forbidden_keywords_name(identifier):
            await context.bot.delete_message(chat_id, msg_id)
            await context.bot.ban_chat_member(chat_id, user.id)
            await context.bot.send_message(
                chat_id,
                text=f"🚫 Utente **{identifier}** rimosso per termini non consentiti nel nome.",
                parse_mode='Markdown'
            )
            return

    text = update.message.text or update.message.caption or ""
    if not is_admin and len(text) > MAX_MESSAGE_LENGTH:
        await context.bot.send_message(chat_id, text=f"❌ {user.full_name}, il tuo messaggio è troppo lungo ({len(text)} caratteri). Il limite massimo è {MAX_MESSAGE_LENGTH} caratteri. Il messaggio è stato rimosso 📜🔥")
        print(f"DEBUG: Messaggio {msg_id} cancellato per lunghezza eccessiva in chat {chat_id}")
        await context.bot.delete_message(chat_id, msg_id)
        return

    ents = update.message.entities or update.message.caption_entities
    if not is_admin and contains_blocked_web_domain(ents, text):
        
        await context.bot.send_message(chat_id, text=f"🚫 {user.full_name}, sei pregato di non portare nella nostra chat la spazzatura della falsa controinformazione. Il contenuto è stato rimosso 🚽")
        print(f"DEBUG: Messaggio {msg_id} cancellato per dominio web bloccato in chat {chat_id}")
        await context.bot.delete_message(chat_id, msg_id)
        return

    if not is_admin and text and has_forbidden_keywords_message(text):
        await context.bot.delete_message(chat_id, msg_id)
        print(f"DEBUG: Messaggio {msg_id} cancellato per parole chiave vietate in chat {chat_id}")
        return

async def send_chat_status_message(bot, message: str, chat_id=None):
    if chat_id:
        try:
            await bot.send_message(chat_id, text=message)
        except TelegramError as e:
            print(f"WARN: Impossibile inviare messaggio a chat {chat_id}: {e}")
            pass
    else:
        for cid in AUTHORIZED_CHAT_IDS:
            try:
                await bot.send_message(cid, text=message)
            except TelegramError as e:
                print(f"WARN: Impossibile inviare messaggio a chat {cid}: {e}")
                pass

def schedule_announce(message: str):
    async def announce():
        await send_chat_status_message(_bot_app.bot, message)
    # Assicurati che _bot_loop sia disponibile prima di tentare di usarlo
    current_loop = _bot_loop if _bot_loop else asyncio.get_event_loop()
    if current_loop.is_running():
        current_loop.call_soon_threadsafe(lambda: asyncio.create_task(announce()))
    else:
        print("WARN: Event loop non avviato o non in esecuzione per schedule_announce. Ignorando l'annuncio.")

def run_flask_server():
    port = int(os.getenv("PORT", 8080))
    print(f"DEBUG: Avvio Flask server sulla porta {port} (per Replit keep-alive)")
    flask_app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False)
    print("DEBUG: Flask server avviato.")

def main():
    global _bot_app, _bot_loop

    token = os.getenv("TELEGRAM_BOT_TOKEN")
    if not token:
        print("Errore: token TELEGRAM_BOT_TOKEN non trovato. Assicurati che sia nelle variabili d'ambiente di Replit Secrets.")
        os._exit(1)

    application = Application.builder().token(token).build()
    _bot_app = application
    # Imposta l'event loop di riferimento NON usando application.loop,
    # ma prendendo l'event loop del thread corrente che sarà quello principale di asyncio.
    # Questo deve avvenire PRIMA di chiamare `run_polling` perché `run_polling` è bloccante.
    try:
        _bot_loop = asyncio.get_event_loop()
    except RuntimeError:
        # Questo può accadere se non c'è un event loop già impostato per il thread corrente.
        # In questo caso, ne creiamo uno (anche se run_polling ne creerà uno se necessario).
        # Questo è più un fallback per compatibilità con versioni molto vecchie di asyncio.
        _bot_loop = asyncio.new_event_loop()
        asyncio.set_event_loop(_bot_loop)
    print(f"DEBUG: Event loop (_bot_loop) impostato: {_bot_loop}")


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
    print("DEBUG: BackgroundScheduler avviato")


    # Avvia Flask su thread per mantenere Replit attivo SOLO se non siamo su Render
    if os.getenv("RENDER") is None:
        threading.Thread(target=run_flask_server, daemon=True).start()
        print("DEBUG: Flask server avviato in thread separato.")
    else:
        print("DEBUG: Ambiente Render rilevato, Flask server non avviato per keep-alive automatico.")
    
    # Avvia il bot in modalità polling con drop_pending_updates=True
    print("DEBUG: Avvio polling bot con drop_pending_updates=True...")
    application.run_polling(allowed_updates=Update.ALL_TYPES, drop_pending_updates=True)
    print("DEBUG: Application in polling avviata.")


if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        print("Bot interrotto manualmente.")
    except Exception as e:
        print(f"Errore critico nell'esecuzione del bot: {e}")
