import re
import os
from telegram import Update
from telegram.ext import Application, MessageHandler, filters, ContextTypes
from telegram.error import TelegramError
AUTHORIZED_CHAT_IDS = [-1001299487305]
# --- Funzioni di Utilità ---

def has_forbidden_chars(name: str) -> bool:
    """
    Verifica se il nome fornito contiene caratteri ebraici, arabi o cinesi.

    Args:
        name: Il nome da controllare.

    Returns:
        True se il nome contiene caratteri proibiti, False altrimenti.
    """
    # Intervalli Unicode:
    # Ebraico: U+0590 a U+05FF
    # Arabo: U+0600 a U+06FF
    # Cinese: U+4E00 a U+9FFF
    pattern = r'[\u0590-\u05FF\u0600-\u06FF\u4E00-\u9FFF]'
    return bool(re.search(pattern, name))

# --- Gestore dei Messaggi (Funzione Asincrona) ---

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Gestisce i messaggi in arrivo. Se il nome dell'utente contiene caratteri proibiti,
    elimina il messaggio e banna l'utente, se il bot ha i permessi necessari.
    """
    # Ignora i messaggi che non provengono da un utente (es. messaggi di canale o di servizio)
    if not update.message or not update.message.from_user:
        return

    user = update.message.from_user
    chat_id = update.message.chat_id
    message_id = update.message.message_id

    # Ignora i messaggi di utenti senza un nome completo
    if not user.full_name:
        print(f"DEBUG: Messaggio da utente senza nome completo (ID: {user.id}). Saltato il controllo.")
        return

    print(f"DEBUG: Controllo il nome dell'utente '{user.full_name}' (ID: {user.id})")

    if has_forbidden_chars(user.full_name):
        print(f"ATTENZIONE: Trovati caratteri proibiti nel nome dell'utente '{user.full_name}' (ID: {user.id}) nella chat {chat_id}. Tentativo di azione.")
        try:
            # Elimina il messaggio
            await context.bot.delete_message(chat_id=chat_id, message_id=message_id)
            print(f"DEBUG: Messaggio {message_id} eliminato con successo nella chat {chat_id}.")

            # Banna l'utente
            # True significa che l'utente non potrà più rientrare nel gruppo a meno che non venga sbannato manualmente
            await context.bot.ban_chat_member(chat_id=chat_id, user_id=user.id)
            print(f"DEBUG: Utente {user.full_name} (ID: {user.id}) bannato con successo dalla chat {chat_id}.")

            # Invia un messaggio di notifica pubblico
            await context.bot.send_message(
                chat_id=chat_id,
                text=f"Damnatus est de blasphemia et brachio saeculari tradimus 🔥 {user.full_name}",
                parse_mode='Markdown'
            )
            print(f"DEBUG: Messaggio di notifica inviato nella chat {chat_id}.")

        except TelegramError as e:
            # Cattura errori specifici di Telegram
            print(f"ERRORE di Telegram durante la gestione di '{user.full_name}' (ID: {user.id}): {e}")
            if "not enough rights" in str(e).lower():
                print("ERRORE: Il bot non ha i permessi sufficienti (es. 'delete messages' o 'ban users').")
            elif "user not found" in str(e).lower():
                print("ERRORE: Utente non trovato o già rimosso.")
        except Exception as e:
            # Cattura altri tipi di errori generici
            print(f"ERRORE generico durante la gestione di '{user.full_name}' (ID: {user.id}): {e}")

# --- Funzione Principale ---

def main():
    """
    Funzione principale per avviare il bot Telegram.
    """
    # Recupera il token API del bot da una variabile d'ambiente per maggiore sicurezza.
    # Assicurati di impostare la variabile d'ambiente 'TELEGRAM_BOT_TOKEN'
    # Esempio: export TELEGRAM_BOT_TOKEN='IL_TUO_VERO_TOKEN_QUI'
    token = os.getenv("TELEGRAM_BOT_TOKEN")

    if not token:
        print("ERRORE: Variabile d'ambiente 'TELEGRAM_BOT_TOKEN' non trovata.")
        print("Assicurati di aver impostato il token del tuo bot.")
        print("Esempio: export TELEGRAM_BOT_TOKEN='IL_TUO_TOKEN_API_QUI'")
        return

    print("DEBUG: Avvio del bot...")

    # Crea l'istanza di Application, il nuovo modo per gestire il bot
    application = Application.builder().token(token).build()

    # Aggiungi il gestore per i messaggi di testo non-comando
    # Assicurati che handle_message sia una funzione asincrona (async def)
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    # Avvia il bot
    print("DEBUG: Bot avviato e in ascolto. Premi Ctrl+C per fermarlo.")
    # run_polling è il nuovo modo per avviare il bot e mantenere il polling attivo
    # allowed_updates è utile per specificare quali tipi di aggiornamenti il bot deve ricevere
    application.run_polling(allowed_updates=Update.ALL_TYPES)

    print("DEBUG: Bot fermato.")

# --- Esecuzione dello Script ---

if __name__ == '__main__':
    main()
