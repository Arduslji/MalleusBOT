import re
import os
import datetime
from telegram import Update
from telegram.ext import Application, MessageHandler, filters, ContextTypes
from telegram.error import TelegramError

# --- Configurazione del Bot ---
AUTHORIZED_CHAT_IDS = [-1001299487305] # <<< Assicurati che qui ci sia l'ID corretto della tua chat autorizzata!

# LISTA DI PAROLE CHIAVE PROIBITE PER NOMI/BIO UTENTE
FORBIDDEN_KEYWORDS = [
    'porn', 'sex', 'xxx', 'adult', 'nude', 'erotic', 'viagra', 'cialis',
    'onlyfans', 'ofans', 'private', 'channel',
    'bot'
]

# --- NUOVE VARIABILI DI CONFIGURAZIONE ---

# Orario di chiusura della chat (formato 24 ore)
CLOSING_START_HOUR = 23
CLOSING_START_MINUTE = 0
CLOSING_END_HOUR = 9
CLOSING_END_MINUTE = 0

# Lunghezza massima consentita per i messaggi (in caratteri)
MAX_MESSAGE_LENGTH = 1200 # Puoi modificare questo valore a tuo piacimento

# --- Funzioni di Utilità ---

def has_forbidden_chars(name: str) -> bool:
    pattern = r'[\u0590-\u05FF\u0600-\u06FF\u4E00-\u9FFF]'
    return bool(re.search(pattern, name))

def has_forbidden_keywords(name: str) -> bool:
    name_lower = name.lower()
    for keyword in FORBIDDEN_KEYWORDS:
        if keyword in name_lower:
            return True
    return False

# --- Gestore dei Messaggi (Funzione Asincrona) ---

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.from_user:
        return

    chat_id = update.message.chat_id
    message_id = update.message.message_id
    user = update.message.from_user
    message_text = update.message.text

    # 1. Controllo Autorizzazione Chat (DEVE ESSERE SEMPRE IL PRIMO)
    if chat_id not in AUTHORIZED_CHAT_IDS:
        print(f"DEBUG: Messaggio nella chat NON AUTORIZZATA {chat_id}. Ignorato.")
        return

    # 2. Ottieni lo status dell'utente nella chat
    # Questo è un passo cruciale per esentare gli admin
    user_member = await context.bot.get_chat_member(chat_id=chat_id, user_id=user.id)
    user_status = user_member.status
    
    # Se l'utente è un amministratore o il creatore della chat, non applicare le restrizioni.
    if user_status == "administrator" or user_status == "creator":
        print(f"DEBUG: Utente {user.full_name} (ID: {user.id}) è un amministratore/creatore. Esentato dalle restrizioni di orario e lunghezza.")
        return # Gli admin possono fare quello che vogliono, non processiamo oltre per loro

    # --- Inizio Controlli per Utenti NON Admin ---

    # 3. Controllo Orario di Chiusura della Chat
    now = datetime.datetime.now().time()
    start_time = datetime.time(CLOSING_START_HOUR, CLOSING_START_MINUTE)
    end_time = datetime.time(CLOSING_END_HOUR, CLOSING_END_MINUTE)

    is_during_closing_hours = False
    if start_time < end_time:
        if start_time <= now < end_time:
            is_during_closing_hours = True
    else:
        if now >= start_time or now < end_time:
            is_during_closing_hours = True

    if is_during_closing_hours:
        print(f"DEBUG: Messaggio inviato durante l'orario di chiusura ({now}). Eliminazione messaggio {message_id} nella chat {chat_id}.")
        try:
            await context.bot.delete_message(chat_id=chat_id, message_id=message_id)
            await context.bot.send_message(
                chat_id=chat_id,
                text="La chat è chiusa in questo momento. I messaggi sono disabilitati.",
                parse_mode='Markdown'
            )
            print(f"DEBUG: Messaggio di notifica orario di chiusura inviato nella chat {chat_id}.")
        except TelegramError as e:
            print(f"ERRORE di Telegram durante l'eliminazione messaggio orario di chiusura: {e}")
            if "not enough rights" in str(e).lower():
                print("ERRORE: Il bot non ha i permessi per eliminare messaggi.")
        return

    # 4. Controllo Lunghezza Messaggio
    if message_text and len(message_text) > MAX_MESSAGE_LENGTH:
        print(f"DEBUG: Messaggio troppo lungo ({len(message_text)} caratteri). Eliminazione messaggio {message_id} nella chat {chat_id}.")
        try:
            await context.bot.delete_message(chat_id=chat_id, message_id=message_id)
            await context.bot.send_message(
                chat_id=chat_id,
                text=f"Il tuo messaggio è troppo lungo ({len(message_text)}/{MAX_MESSAGE_LENGTH} caratteri). Per favore, sii più conciso.",
                parse_mode='Markdown'
            )
            print(f"DEBUG: Messaggio di notifica lunghezza inviato nella chat {chat_id}.")
        except TelegramError as e:
            print(f"ERRORE di Telegram durante l'eliminazione messaggio troppo lungo: {e}")
            if "not enough rights" in str(e).lower():
                print("ERRORE: Il bot non ha i permessi per eliminare messaggi.")
        return

    # --- Controlli Esistenti (dopo i nuovi filtri per utenti NON admin) ---

    full_name = user.full_name
    username = user.username
    user_identifier = f"{full_name} {username}" if username else full_name

    if not user_identifier:
        print(f"DEBUG: Messaggio da utente senza nome/username. Saltato il controllo.")
        return

    print(f"DEBUG: Controllo l'identificativo utente '{user_identifier}' (ID: {user.id}) nella chat {chat_id}")

    # Controllo: Parole chiave proibite nel nome/username
    if has_forbidden_keywords(user_identifier):
        print(f"ATTENZIONE: Trovate parole chiave proibite nell'identificativo utente '{user_identifier}' (ID: {user.id}) nella chat {chat_id}. Tentativo di azione.")
        try:
            await context.bot.delete_message(chat_id=chat_id, message_id=message_id)
            await context.bot.ban_chat_member(chat_id=chat_id, user_id=user.id)
            await context.bot.send_message(
                chat_id=chat_id,
                text=f"L'utente {user_identifier} è stato rimosso per aver utilizzato termini non consentiti nel proprio identificativo.",
                parse_mode='Markdown'
            )
        except TelegramError as e:
            print(f"ERRORE di Telegram (parole chiave proibite) durante la gestione di '{user_identifier}' (ID: {user.id}): {e}")
            if "not enough rights" in str(e).lower():
                print("ERRORE: Il bot non ha i permessi sufficienti.")
        except Exception as e:
            print(f"ERRORE generico (parole chiave proibite) durante la gestione di '{user_identifier}' (ID: {user.id}): {e}")
        return

    # Controllo: Caratteri ebraici, arabi o cinesi
    if has_forbidden_chars(full_name):
        print(f"ATTENZIONE: Trovati caratteri proibiti nel nome dell'utente '{full_name}' (ID: {user.id}) nella chat {chat_id}. Tentativo di azione.")
        try:
            await context.bot.delete_message(chat_id=chat_id, message_id=message_id)
            await context.bot.ban_chat_member(chat_id=chat_id, user_id=user.id)
            await context.bot.send_message(
                chat_id=chat_id,
                text=f"Damnatus est de blasphemia et brachio saeculari tradimus 🔥 {full_name}",
                parse_mode='Markdown'
            )
        except TelegramError as e:
            print(f"ERRORE di Telegram (caratteri proibiti) durante la gestione di '{full_name}' (ID: {user.id}): {e}")
            if "not enough rights" in str(e).lower():
                print("ERRORE: Il bot non ha i permessi sufficienti.")
        except Exception as e:
            print(f"ERRORE generico (caratteri proibiti) durante la gestione di '{full_name}' (ID: {user.id}): {e}")


# --- Funzione Principale (Invariata) ---
def main():
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    if not token:
        print("ERRORE: Variabile d'ambiente 'TELEGRAM_BOT_TOKEN' non trovata.")
        return
    print("DEBUG: Avvio del bot...")
    application = Application.builder().token(token).build()
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    print("DEBUG: Bot avviato e in ascolto. Premi Ctrl+C per fermarlo.")
    application.run_polling(allowed_updates=Update.ALL_TYPES)
    print("DEBUG: Bot fermato.")

if __name__ == '__main__':
    main()
