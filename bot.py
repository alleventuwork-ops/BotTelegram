import sqlite3
import os
from datetime import datetime, timedelta
from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    MessageHandler,
    CommandHandler,
    ContextTypes,
    filters
)
from apscheduler.schedulers.background import BackgroundScheduler

TOKEN = os.environ["TOKEN"] 
CHAT_ID = None  # verrà impostato alla prima interazione


# ---------- DATABASE ----------
def init_db():
    conn = sqlite3.connect("finanze.db")
    c = conn.cursor()

    c.execute("""
    CREATE TABLE IF NOT EXISTS movimenti (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        data TEXT,
        tipo TEXT,
        importo REAL
    )
    """)

    c.execute("""
    CREATE TABLE IF NOT EXISTS saldi_mensili (
        mese TEXT PRIMARY KEY,
        saldo_iniziale REAL
    )
    """)

    conn.commit()
    conn.close()


# ---------- UTILS ----------
def get_saldo_iniziale(mese):
    conn = sqlite3.connect("finanze.db")
    c = conn.cursor()
    c.execute("SELECT saldo_iniziale FROM saldi_mensili WHERE mese = ?",
              (mese, ))
    row = c.fetchone()
    conn.close()
    return row[0] if row else 0.0


def salva_saldo(mese, saldo):
    conn = sqlite3.connect("finanze.db")
    c = conn.cursor()
    c.execute(
        "INSERT OR REPLACE INTO saldi_mensili (mese, saldo_iniziale) VALUES (?, ?)",
        (mese, saldo))
    conn.commit()
    conn.close()


# ---------- HANDLER ----------
async def salva_movimento(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global CHAT_ID
    CHAT_ID = update.message.chat_id

    testo = update.message.text.strip()
    try:
        if testo.startswith("+"):
            tipo = "entrata"
            importo = float(testo[1:])
        elif testo.startswith("-"):
            tipo = "uscita"
            importo = float(testo[1:])
        else:
            raise ValueError
    except ValueError:
        await update.message.reply_text("Formato non valido. Usa +50 o -20.5")
        return

    data = datetime.now().strftime("%Y-%m-%d")
    conn = sqlite3.connect("finanze.db")
    c = conn.cursor()
    c.execute("INSERT INTO movimenti (data, tipo, importo) VALUES (?, ?, ?)",
              (data, tipo, importo))
    conn.commit()
    conn.close()

    await update.message.reply_text(
        f"{tipo.capitalize()} di {importo:.2f} € registrata ✅")


# ---------- RIEPILOGO ----------
def riepilogo_mensile(app):
    global CHAT_ID
    if CHAT_ID is None:
        return

    oggi = datetime.now()
    primo = oggi.replace(day=1)
    mese_prec = (primo - timedelta(days=1)).strftime("%Y-%m")
    mese_corr = oggi.strftime("%Y-%m")

    saldo_iniziale = get_saldo_iniziale(mese_prec)

    conn = sqlite3.connect("finanze.db")
    c = conn.cursor()
    c.execute(
        """
        SELECT tipo, SUM(importo)
        FROM movimenti
        WHERE data LIKE ?
        GROUP BY tipo
    """, (f"{mese_prec}%", ))
    dati = dict(c.fetchall())
    conn.close()

    entrate = dati.get("entrata", 0)
    uscite = dati.get("uscita", 0)
    saldo_finale = saldo_iniziale + entrate - uscite

    salva_saldo(mese_corr, saldo_finale)

    app.bot.send_message(chat_id=CHAT_ID,
                         text=(f"📊 Riepilogo {mese_prec}\n\n"
                               f"Saldo iniziale: {saldo_iniziale:.2f} €\n"
                               f"Entrate: {entrate:.2f} €\n"
                               f"Uscite: {uscite:.2f} €\n"
                               f"------------------------\n"
                               f"Saldo finale: {saldo_finale:.2f} €"))



# ---------- COMANDO /SALDO ----------
async def saldo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global CHAT_ID
    CHAT_ID = update.message.chat_id

    oggi = datetime.now()
    mese_corr = oggi.strftime("%Y-%m")

    saldo_iniziale = get_saldo_iniziale(mese_corr)

    conn = sqlite3.connect("finanze.db")
    c = conn.cursor()
    c.execute("""
        SELECT tipo, SUM(importo)
        FROM movimenti
        WHERE data LIKE ?
        GROUP BY tipo
    """, (f"{mese_corr}%",))
    dati = dict(c.fetchall())
    conn.close()

    entrate = dati.get("entrata", 0)
    uscite = dati.get("uscita", 0)
    saldo_finale = saldo_iniziale + entrate - uscite

    await update.message.reply_text(
        f"📊 Saldo corrente {mese_corr}:\n\n"
        f"Saldo iniziale: {saldo_iniziale:.2f} €\n"
        f"Entrate: {entrate:.2f} €\n"
        f"Uscite: {uscite:.2f} €\n"
        f"------------------------\n"
        f"Saldo attuale: {saldo_finale:.2f} €"
    )

# ---------- MAIN ----------
if __name__ == "__main__":
    init_db()
    app = ApplicationBuilder().token(TOKEN).build()
    app.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, salva_movimento))
    app.add_handler(CommandHandler("saldo", saldo))

    # Scheduler background
    scheduler = BackgroundScheduler()
    scheduler.add_job(riepilogo_mensile,
                      "cron",
                      day=1,
                      hour=8,
                      minute=0,
                      args=[app])
    scheduler.start()

    print("Bot avviato con riepilogo mensile attivo...")
    app.run_polling()
