import re
import os
import datetime
from telegram import Update
from telegram.ext import Application, MessageHandler, filters, ContextTypes
from telegram.error import TelegramError

# --- Configurazione del Bot ---
AUTHORIZED_CHAT_IDS = [-1001299487305] # <<< Assicurati che qui ci sia l'ID corretto della tua chat autorizzata!

# LISTA DI PAROLE CHIAVE PROIBITE PER NOMI/BIO UTENTE
FORBIDDEN_KEYWORDS_NAME = [
    'porn', 'sex', 'xxx', 'adult', 'nude', 'erotic', 'viagra', 'cialis',
    'onlyfans', 'ofans', 'private', 'channel',
    'bot'
]

# LISTA DI PAROLE SCURRILI PER I MESSAGGI
FORBIDDEN_KEYWORDS_MESSAGE = [
   
    # Aggiungi qui altre parole o frasi che vuoi censurare
]

# --- NUOVE VARIABILI DI CONFIGURAZIONE ---

# --- NUOVA LISTA DI DOMINI WEB PROIBITI ---
# Inserisci qui i domini web (o parti di essi) che vuoi bloccare.
# I domini devono essere in minuscolo.
# Esempio: BLOCKED_WEB_DOMAINS = ['spam.com', 'phishing.net', 'scommesse.it', 'casinogratis.xyz']
BLOCKED_WEB_DOMAINS = [
    'byoblu.com',
    'phishing.net',
    'casinogratis.xyz',
    'scommesse.it',
    'linkdannoso.ru',
    'offertespeciali.info'
    # Aggiungi qui altri domini che vuoi bloccare
]

# Orario di chiusura della chat (formato 24 ore)
CLOSING_START_HOUR = 23
CLOSING_START_MINUTE = 0
CLOSING_END_HOUR = 9
CLOSING_END_MINUTE = 0

# Lunghezza massima consentita per i messaggi (in caratteri)
MAX_MESSAGE_LENGTH = 1200 # Puoi modificare questo valore a tuo piacimento

# --- NUOVA LISTA DI CANALI DA CUI BLOCCARE GLI INOLTRI ---
# Inserisci qui gli ID numerici (negativi) dei canali da cui vuoi bloccare gli inoltri.
# Esempio: BLOCKED_FORWARD_CHANNEL_IDS = [-1001234567890, -1009876543210]
BLOCKED_FORWARD_CHANNEL_IDS = [-1001249969478, -1001382991987, -1001185400784, -1001450908211, -1001458150284, -1001437761372, -1001281633465, -1001272270169, -1002002355451, -1001245777992] # <<< Inserisci QUI gli ID dei canali da bloccare!


# --- Funzioni di Utilità ---

def has_forbidden_chars(name: str) -> bool:
    """
    Verifica se il nome fornito contiene caratteri ebraici, arabi o cinesi.
    """
    pattern = r'[\u0590-\u05FF\u0600-\u06FF\u4E00-\u9FFF]'
    return bool(re.search(pattern, name))

def has_forbidden_keywords_name(name: str) -> bool:
    """
    Verifica se il nome fornito contiene parole chiave proibite dalla lista FORBIDDEN_KEYWORDS_NAME.
    """
    name_lower = name.lower()
    for keyword in FORBIDDEN_KEYWORDS_NAME:
        if keyword in name_lower:
            return True
    return False
    
# --- NUOVA FUNZIONE: Controlla se il messaggio contiene un link a un dominio proibito ---
def contains_blocked_web_domain(message_entities, message_text) -> bool:
    if not message_text or not message_entities:
        return False

    text_lower = message_text.lower()
    
    for entity in message_entities:
        if entity.type == 'url' or entity.type == 'text_link':
            # Estrai l'URL effettivo
            if entity.type == 'url':
                url = text_lower[entity.offset : entity.offset + entity.length]
            else: # entity.type == 'text_link'
                url = entity.url.lower()

            for domain in BLOCKED_WEB_DOMAINS:
                # Controlla se il dominio proibito è una sottostringa dell'URL
                # Esempio: 'spam.com' bloccherà 'http://www.spam.com', 'https://sub.spam.com/page'
                if domain in url:
                    return True
    return False


def has_forbidden_keywords_message(text: str) -> bool:
    """
    Verifica se il testo fornito contiene parole scurrili dalla lista FORBIDDEN_KEYWORDS_MESSAGE.
    """
    text_lower = text.lower()
    for keyword in FORBIDDEN_KEYWORDS_MESSAGE:
        if keyword in text_lower:
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
    message_entities = update.message.entities or update.message.caption_entities # Gestisce anche i link nelle didascalie
    
    # 1. Controllo Autorizzazione Chat (DEVE ESSERE SEMPRE IL PRIMO)
    if chat_id not in AUTHORIZED_CHAT_IDS:
        print(f"DEBUG: Messaggio nella chat NON AUTORIZZATA {chat_id}. Ignorato.")
        return

    # 2. Ottieni lo status dell'utente nella chat
    user_member = await context.bot.get_chat_member(chat_id=chat_id, user_id=user.id)
    user_status = user_member.status
    
    # Estrai full_name, username e user_identifier subito, prima dei controlli che li usano
    full_name = user.full_name
    username = user.username
    user_identifier = f"{full_name} {username}" if username else full_name

    # Se l'utente è un amministratore o il creatore della chat, non applicare le restrizioni.
    if user_status == "administrator" or user_status == "creator":
        print(f"DEBUG: Utente {full_name} (ID: {user.id}) è un amministratore/creatore. Esentato dalle restrizioni.")
        return # Gli admin possono fare quello che vogliono, non processiamo oltre per loro

    # --- Inizio Controlli per Utenti NON Admin ---

    # 3. Controllo Inoltro da Canale Proibito
    if update.message.forward_from_chat:
        forwarded_channel_id = update.message.forward_from_chat.id
        if forwarded_channel_id in BLOCKED_FORWARD_CHANNEL_IDS:
            print(f"ATTENZIONE: è fatto divieto assoluto di scaricare in chat l'immondizia della falsa controinformazione 🚽 '{forwarded_channel_id}'. Eliminazione messaggio {message_id} nella chat {chat_id}.")
            try:
                await context.bot.delete_message(chat_id=chat_id, message_id=message_id)
                
                # *** MODIFICA QUI: MESSAGGIO DI AVVISO SPECIFICO PER I LINK ***
                # Controlla se il messaggio originale conteneva un link esplicito
                # Puoi espandere questo controllo se vuoi essere più specifico sui tipi di link
                message_has_link = False
                if update.message.entities:
                    for entity in update.message.entities:
                        if entity.type == 'url' or entity.type == 'text_link':
                            message_has_link = True
                            break
                
                # Scegli il messaggio di avviso in base alla presenza del link
                if message_has_link:
                    warning_text = f"**Attenzione {full_name}!** L'inoltro di link da questo canale non è consentito e il tuo messaggio è stato eliminato."
                else:
                    warning_text = f"**Attenzione {full_name}!** I messaggi inoltrati da questo canale non sono consentiti e sono stati eliminati."

                await context.bot.send_message(
                    chat_id=chat_id,
                    text=warning_text, # Usa il testo determinato sopra
                    parse_mode='Markdown'
                )
                print(f"DEBUG: Messaggio di notifica inoltro proibito inviato nella chat {chat_id}.")
            except TelegramError as e:
                print(f"ERRORE di Telegram durante l'eliminazione messaggio da canale proibito: {e}")
                if "not enough rights" in str(e).lower():
                    print("ERRORE: Il bot non ha i permessi per eliminare messaggi o inviare messaggi.")
            return # Termina la funzione dopo aver agito


    # 4. Controllo Orario di Chiusura della Chat
    now = datetime.datetime.now().time()
    start_time = datetime.time(CLOSING_START_HOUR, CLOSING_START_MINUTE)
    end_time = datetime.time(CLOSING_END_HOUR, CLOSING_END_MINUTE)

    is_during_closing_hours = False
    if start_time < end_time:
        if start_time <= now < end_time:
            is_during_closing_hours = True
    else: # Orario di chiusura a cavallo della mezzanotte (es. 23:00 - 09:00)
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

    # 5. Controllo Lunghezza Messaggio
    if message_text and len(message_text) > MAX_MESSAGE_LENGTH:
        print(f"DEBUG: Messaggio troppo lungo ({len(message_text)} caratteri). Eliminazione messaggio {message_id} nella chat {chat_id}.")
        try:
            await context.bot.delete_message(chat_id=chat_id, message_id=message_id)
            await context.bot.send_message(
                chat_id=chat_id,
                text=f"{full_name}, il tuo messaggio è troppo lungo ({len(message_text)}/{MAX_MESSAGE_LENGTH} caratteri). Per favore, sii più conciso.",
                parse_mode='Markdown'
            )
            print(f"DEBUG: Messaggio di notifica lunghezza inviato nella chat {chat_id}.")
        except TelegramError as e:
            print(f"ERRORE di Telegram durante l'eliminazione messaggio troppo lungo: {e}")
            if "not enough rights" in str(e).lower():
                print("ERRORE: Il bot non ha i permessi per eliminare messaggi.")
        return

    # 6. Controllo: Parole scurrili nel messaggio
    if message_text and has_forbidden_keywords_message(message_text):
        print(f"ATTENZIONE: Trovate parole scurrili nel messaggio di '{full_name}' (ID: {user.id}). Eliminazione messaggio {message_id} e ammonizione.")
        try:
            await context.bot.delete_message(chat_id=chat_id, message_id=message_id)
            await context.bot.send_message(
                chat_id=chat_id,
                text=f"**Ammonizione per {full_name}!** Il tuo messaggio conteneva termini non appropriati ed è stato eliminato. Per favore, mantieni un linguaggio rispettoso.",
                parse_mode='Markdown'
            )
            print(f"DEBUG: Messaggio di ammonizione inviato nella chat {chat_id}.")
        except TelegramError as e:
            print(f"ERRORE di Telegram durante l'eliminazione/ammonizione per parole scurrili: {e}")
            if "not enough rights" in str(e).lower():
                print("ERRORE: Il bot non ha i permessi per eliminare messaggi o inviare messaggi.")
        return
    # 7. Controllo Link a Domini Web Proibiti (NUOVO)
    if contains_blocked_web_domain(message_entities, message_text):
        print(f"ATTENZIONE: Messaggio di '{full_name}' (ID: {user.id}) contiene un link a un dominio web della falsa controinformazione. Eliminazione messaggio 🚽 {message_id}.")
        try:
            await context.bot.delete_message(chat_id=chat_id, message_id=message_id)
            await context.bot.send_message(
                chat_id=chat_id,
                text=f"**Attenzione {full_name}!** L'inserimento di link a siti web della falsa controinformazione non è consentito. Il tuo messaggio è stato eliminato 🚽",
                parse_mode='Markdown'
            )
            print(f"DEBUG: Messaggio di avviso dominio proibito inviato nella chat {chat_id}.")
        except TelegramError as e:
            print(f"ERRORE di Telegram durante l'eliminazione/avviso dominio proibito: {e}")
            if "not enough rights" in str(e).lower():
                print("ERRORE: Il bot non ha i permessi per eliminare messaggi o inviare messaggi.")
        return # Termina la funzione dopo aver agito

    # --- Controlli Esistenti (dopo i nuovi filtri per utenti NON admin) ---

    if not user_identifier:
        print(f"DEBUG: Messaggio da utente senza nome/username. Saltato il controllo.")
        return

    print(f"DEBUG: Controllo l'identificativo utente '{user_identifier}' (ID: {user.id}) nella chat {chat_id}")

    # Controllo: Parole chiave proibite nel nome/username
    if has_forbidden_keywords_name(user_identifier):
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