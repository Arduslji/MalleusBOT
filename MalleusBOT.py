import re
import os
import datetime
from telegram import Update
from telegram.ext import Application, MessageHandler, filters, ContextTypes
from telegram.error import TelegramError

# --- Configurazione del Bot ---
# >>> Assicurati che qui ci sia l'ID corretto della tua chat autorizzata!
# Esempio: AUTHORIZED_CHAT_IDS = [-1234567890]
AUTHORIZED_CHAT_IDS = [-1001299487305] 

# LISTA DI PAROLE CHIAVE PROIBITE PER NOMI/BIO UTENTE (NON si applica agli Admin/Creatori)
FORBIDDEN_KEYWORDS_NAME = [
    'porn', 'sex', 'xxx', 'adult', 'nude', 'erotic', 'viagra', 'cialis',
    'onlyfans', 'ofans', 'private', 'channel',
    'bot' 
]

# LISTA DI PAROLE SCURRILI PER I MESSAGGI (NON si applica agli Admin/Creatori)
FORBIDDEN_KEYWORDS_MESSAGE = [
    # Aggiungi qui altre parole o frasi che vuoi censurare
]

# Orario di chiusura della chat (NON si applica agli Admin/Creatori)
CLOSING_START_HOUR = 23
CLOSING_START_MINUTE = 0
CLOSING_END_HOUR = 9
CLOSING_END_MINUTE = 0

# Lunghezza massima consentita per i messaggi (NON si applica agli Admin/Creatori)
MAX_MESSAGE_LENGTH = 1200 

# LISTA DI CANALI DA CUI BLOCCARE GLI INOLTRI (NON si applica agli Admin/Creatori)
# Inserisci qui gli ID numerici (negativi) dei canali da cui vuoi bloccare gli inoltri.
# Esempio: BLOCKED_FORWARD_CHANNEL_IDS = [-1001234567890, -1009876543210]
BLOCKED_FORWARD_CHANNEL_IDS = [-1001249969478, -1001382991987, -1001185400784, -1001450908211, -1001458150284, -1001437761372, -1001281633465, -1001272270169, -1002002355451, -1001245777992]

# LISTA DI NOMI UTENTE DI CANALI DA BLOCCARE (per link incollati, es. telegram.me/username) (NON si applica agli Admin/Creatori)
# Inserisci qui i nomi utente (senza @) di canali Telegram da cui vuoi bloccare i link incollati.
# Esempio: BLOCKED_CHANNEL_USERNAMES = ['canalespam1', 'offertelav']
BLOCKED_CHANNEL_USERNAMES = [] 

# LISTA DI DOMINI WEB PROIBITI (NON si applica agli Admin/Creatori)
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

# --- Funzioni di Utilità ---
# Queste funzioni sono richiamate solo dopo aver verificato che l'utente NON sia un admin/creatore.

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
    
def has_forbidden_keywords_message(text: str) -> bool:
    """
    Verifica se il testo fornito contiene parole scurrili dalla lista FORBIDDEN_KEYWORDS_MESSAGE.
    """
    text_lower = text.lower()
    for keyword in FORBIDDEN_KEYWORDS_MESSAGE:
        if keyword in text_lower:
            return True
    return False

def contains_blocked_web_domain(message_entities, message_text) -> bool:
    """
    Verifica se il messaggio contiene un URL che corrisponde a un dominio nella lista BLOCKED_WEB_DOMAINS
    o a un canale Telegram specificato in BLOCKED_CHANNEL_USERNAMES.
    Cerca sia in URL espliciti che in link testuali, e menzioni di canali.
    """
    if not message_text and not message_entities:
        return False

    text_lower = message_text.lower() if message_text else ""
    
    for entity in message_entities if message_entities else []:
        if entity.type == 'url' or entity.type == 'text_link':
            url = text_lower[entity.offset : entity.offset + entity.length] if entity.type == 'url' else entity.url.lower()
            for domain in BLOCKED_WEB_DOMAINS:
                if domain in url:
                    return True
        elif (entity.type == 'tg_url' or entity.type == 'mention') and BLOCKED_CHANNEL_USERNAMES:
            # Gestisce link a canali Telegram (es. t.me/username o tg://resolve?domain=username) e menzioni @username
            target_username = ""
            if entity.type == 'tg_url' and entity.url:
                # Estrai il nome utente dall'URL tg://resolve?domain=USERNAME o https://t.me/USERNAME
                match = re.search(r'(?:domain=|t.me/)([^/&\?]+)', entity.url, re.IGNORECASE)
                if match:
                    target_username = match.group(1).lower()
            elif entity.type == 'mention':
                # Estrai il nome utente dalla menzione @USERNAME
                target_username = text_lower[entity.offset : entity.offset + entity.length].lstrip('@')
            
            if target_username and target_username in [u.lower() for u in BLOCKED_CHANNEL_USERNAMES]:
                return True
    return False


# --- Gestore dei Messaggi (Funzione Asincrona) ---

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Ignora messaggi non validi o senza mittente
    if not update.message or not update.message.from_user:
        return

    chat_id = update.message.chat_id
    message_id = update.message.message_id
    user = update.message.from_user
    
    # 1. Controllo Autorizzazione Chat (DEVE ESSERE SEMPRE IL PRIMO)
    if chat_id not in AUTHORIZED_CHAT_IDS:
        print(f"DEBUG: Messaggio nella chat NON AUTORIZZATA {chat_id}. Ignorato.")
        return

    # --- INIZIO ESENZIONE TOTALE PER AMMINISTRATORI E CREATORE ---
    # Questo è il blocco cruciale. Se l'utente è un admin o il creatore,
    # il bot non farà ASSOLUTAMENTE NULLA sul suo messaggio.

    user_member = await context.bot.get_chat_member(chat_id=chat_id, user_id=user.id)
    user_status = user_member.status
    
    # Se l'utente è un amministratore o il creatore della chat, ignoriamo completamente il suo messaggio.
    # Questo include il proprietario del gruppo (status 'creator') e qualsiasi admin che scriva in anonimato (GroupAnonymousBot).
    if user_status == "administrator" or user_status == "creator":
        # Estraggo il nome per il log, ma non verrà usato per i filtri successivi.
        full_name = user.full_name 
        print(f"DEBUG: Messaggio da '{full_name}' (ID: {user.id}) con status '{user_status}'. È un amministratore/creatore. Messaggio completamente esentato.")
        return # Termina la funzione qui, nessun altro controllo verrà eseguito.

    # --- FINE ESENZIONE TOTALE ---

    # --- Se il codice arriva qui, l'utente NON è un amministratore o il creatore ---
    # Procediamo con l'applicazione di tutti i filtri per gli utenti standard.

    message_text = update.message.text
    message_entities = update.message.entities or update.message.caption_entities 
    full_name = user.full_name # Lo riprendo qui per gli utenti non admin
    username = user.username
    user_identifier = f"{full_name} {username}" if username else full_name

    # 2. Controllo Inoltro da Canale Proibito
    if hasattr(update.message, 'forward_from_chat') and update.message.forward_from_chat:
        forwarded_channel_id = update.message.forward_from_chat.id
        if forwarded_channel_id in BLOCKED_FORWARD_CHANNEL_IDS:
            print(f"ATTENZIONE: Messaggio da '{full_name}' (ID: {user.id}) inoltrato da canale proibito '{forwarded_channel_id}'. Eliminazione messaggio {message_id}.")
            try:
                await context.bot.delete_message(chat_id=chat_id, message_id=message_id)
                warning_text = f"**Attenzione {full_name}!** L'inoltro di contenuti da questo canale non è consentito e il tuo messaggio è stato eliminato."
                await context.bot.send_message(
                    chat_id=chat_id, text=warning_text, parse_mode='Markdown'
                )
                print(f"DEBUG: Messaggio di notifica inoltro proibito inviato nella chat {chat_id}.")
            except TelegramError as e:
                print(f"ERRORE di Telegram durante l'eliminazione messaggio da canale proibito: {e}")
                if "not enough rights" in str(e).lower():
                    print("ERRORE: Il bot non ha i permessi per eliminare messaggi o inviare messaggi.")
            return

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
        print(f"DEBUG: Messaggio inviato da '{full_name}' (ID: {user.id}) durante l'orario di chiusura ({now}). Eliminazione messaggio {message_id}.")
        try:
            await context.bot.delete_message(chat_id=chat_id, message_id=message_id)
            await context.bot.send_message(
                chat_id=chat_id, text="La chat è chiusa in questo momento. I messaggi sono disabilitati.", parse_mode='Markdown'
            )
            print(f"DEBUG: Messaggio di notifica orario di chiusura inviato nella chat {chat_id}.")
        except TelegramError as e:
            print(f"ERRORE di Telegram durante l'eliminazione messaggio orario di chiusura: {e}")
            if "not enough rights" in str(e).lower():
                print("ERRORE: Il bot non ha i permessi per eliminare messaggi.")
        return

    # 4. Controllo Lunghezza Messaggio
    if message_text and len(message_text) > MAX_MESSAGE_LENGTH:
        print(f"DEBUG: Messaggio di '{full_name}' (ID: {user.id}) troppo lungo ({len(message_text)} caratteri). Eliminazione messaggio {message_id}.")
        try:
            await context.bot.delete_message(chat_id=chat_id, message_id=message_id)
            await context.bot.send_message(
                chat_id=chat_id, text=f"**Attenzione {full_name}!** Il tuo messaggio è troppo lungo ({len(message_text)}/{MAX_MESSAGE_LENGTH} caratteri). Per favore, sii più conciso.", parse_mode='Markdown'
            )
            print(f"DEBUG: Messaggio di notifica lunghezza inviato nella chat {chat_id}.")
        except TelegramError as e:
            print(f"ERRORE di Telegram durante l'eliminazione messaggio troppo lungo: {e}")
            if "not enough rights" in str(e).lower():
                print("ERRORE: Il bot non ha i permessi per eliminare messaggi.")
        return

    # 5. Controllo Link a Domini Web Proibiti
    if contains_blocked_web_domain(message_entities, message_text):
        print(f"ATTENZIONE: Messaggio di '{full_name}' (ID: {user.id}) contiene un link a un dominio/canale proibito. Eliminazione messaggio 🚽 {message_id}.")
        try:
            await context.bot.delete_message(chat_id=chat_id, message_id=message_id)
            await context.bot.send_message(
                chat_id=chat_id, text=f"**Attenzione {full_name}!** L'inserimento di link a siti web/canali proibiti non è consentito. Il tuo messaggio è stato eliminato 🚽", parse_mode='Markdown'
            )
            print(f"DEBUG: Messaggio di avviso dominio proibito inviato nella chat {chat_id}.")
        except TelegramError as e:
            print(f"ERRORE di Telegram durante l'eliminazione/avviso dominio proibito: {e}")
            if "not enough rights" in str(e).lower():
                print("ERRORE: Il bot non ha i permessi per eliminare messaggi o inviare messaggi.")
        return

    # 6. Controllo: Parole scurrili nel messaggio
    if message_text and has_forbidden_keywords_message(message_text):
        print(f"ATTENZIONE: Trovate parole scurrili nel messaggio di '{full_name}' (ID: {user.id}). Eliminazione messaggio {message_id} e ammonizione.")
        try:
            await context.bot.delete_message(chat_id=chat_id, message_id=message_id)
            await context.bot.send_message(
                chat_id=chat_id, text=f"**Ammonizione per {full_name}!** Il tuo messaggio conteneva termini non appropriati ed è stato eliminato. Per favore, mantieni un linguaggio rispettoso.", parse_mode='Markdown'
            )
            print(f"DEBUG: Messaggio di ammonizione inviato nella chat {chat_id}.")
        except TelegramError as e:
            print(f"ERRORE di Telegram durante l'eliminazione/ammonizione per parole scurrili: {e}")
            if "not enough rights" in str(e).lower():
                print("ERRORE: Il bot non ha i permessi per eliminare messaggi o inviare messaggi.")
        return

    # --- Controlli su Utente (Nome/Bio) ---
    # Questi controlli sono applicati solo agli utenti che NON sono admin/creator.
    
    if not user_identifier:
        print(f"DEBUG: Messaggio da utente senza nome/username. Saltato il controllo sul nome/bio.")
        return # Se non c'è un identificativo, non ha senso controllare parole proibite nel nome

    print(f"DEBUG: Controllo l'identificativo utente '{user_identifier}' (ID: {user.id}) nella chat {chat_id}")

    # 7. Controllo: Parole chiave proibite nel nome/username
    if has_forbidden_keywords_name(user_identifier):
        print(f"ATTENZIONE: Trovate parole chiave proibite nell'identificativo utente '{user_identifier}' (ID: {user.id}) nella chat {chat_id}. Tentativo di azione.")
        try:
            await context.bot.delete_message(chat_id=chat_id, message_id=message_id)
            await context.bot.ban_chat_member(chat_id=chat_id, user_id=user.id)
            await context.bot.send_message(
                chat_id=chat_id, text=f"L'utente **{user_identifier}** è stato rimosso per aver utilizzato termini non consentiti nel proprio identificativo.", parse_mode='Markdown'
            )
        except TelegramError as e:
            print(f"ERRORE di Telegram (parole chiave proibite) durante la gestione di '{user_identifier}' (ID: {user.id}): {e}")
            if "not enough rights" in str(e).lower():
                print("ERRORE: Il bot non ha i permessi sufficienti.")
        except Exception as e:
            print(f"ERRORE generico (parole chiave proibite) durante la gestione di '{user_identifier}' (ID: {user.id}): {e}")
        return

    # 8. Controllo: Caratteri ebraici, arabi o cinesi
    if has_forbidden_chars(full_name):
        print(f"ATTENZIONE: Trovati caratteri proibiti nel nome dell'utente '{full_name}' (ID: {user.id}) nella chat {chat_id}. Tentativo di azione.")
        try:
            await context.bot.delete_message(chat_id=chat_id, message_id=message_id)
            await context.bot.ban_chat_member(chat_id=chat_id, user_id=user.id)
            await context.bot.send_message(
                chat_id=chat_id, text=f"Damnatus est de blasphemia et brachio saeculari tradimus 🔥 **{full_name}**", parse_mode='Markdown'
            )
        except TelegramError as e:
            print(f"ERRORE di Telegram (caratteri proibiti) durante la gestione di '{full_name}' (ID: {user.id}): {e}")
            if "not enough rights" in str(e).lower():
                print("ERRORE: Il bot non ha i permessi sufficienti.")
        except Exception as e:
            print(f"ERRORE generico (caratteri proibiti) durante la gestione di '{full_name}' (ID: {user.id}): {e}")


# --- Funzione Principale ---
def main():
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    if not token:
        print("ERRORE: Variabile d'ambiente 'TELEGRAM_BOT_TOKEN' non trovata.")
        print("Assicurati di aver impostato la variabile TELEGRAM_BOT_TOKEN nel tuo ambiente.")
        return
    
    print("DEBUG: Avvio del bot...")
    application = Application.builder().token(token).build()
    
    # Registra un handler per TUTTI i tipi di messaggi e aggiornamenti.
    # filters.ALL cattura testi, foto, video, documenti, sticker, ecc.
    # ~filters.COMMAND assicura che il bot non interferisca con i comandi tipo /start, /help, ecc.
    application.add_handler(MessageHandler(filters.ALL & ~filters.COMMAND, handle_message))

    print("DEBUG: Bot avviato e in ascolto. Premi Ctrl+C per fermarlo.")
    application.run_polling(allowed_updates=Update.ALL_TYPES)
    print("DEBUG: Bot fermato.")

if __name__ == '__main__':
    main()