import psycopg2
from datetime import datetime
import pytz

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    ApplicationBuilder, CommandHandler, CallbackQueryHandler,
    MessageHandler, ContextTypes, filters
)

# ===== CONFIG =====
TOKEN = "8192711687:AAFYKMnTNFrnYJooUZ6LPRFZ7A1RhElRJ5U"
DB_URL = "postgresql://postgres:CpSzcVpAJcFclBYIiwnMudwResayRISd@postgres.railway.internal:5432/railway"

ADMIN_ID = 5869414542

CANALES = [
    -1001939817105,
    -1002496825506,
    -1001972632210,
    -1002846744606,
    -1002707167875,
    -1002276974978,
]

TIMEZONE = pytz.timezone("America/Bogota")

# ===== DB =====
conn = psycopg2.connect(DB_URL)
cursor = conn.cursor()

cursor.execute("""
CREATE TABLE IF NOT EXISTS mensajes (
    id SERIAL PRIMARY KEY,
    texto TEXT,
    chat_id BIGINT,
    fecha TEXT
)
""")
conn.commit()

# ===== FUNCIONES =====
def guardar(texto, chat_id, fecha):
    cursor.execute(
        "INSERT INTO mensajes (texto, chat_id, fecha) VALUES (%s,%s,%s)",
        (texto, chat_id, fecha)
    )
    conn.commit()

def obtener():
    cursor.execute("SELECT * FROM mensajes")
    return cursor.fetchall()

def eliminar(id):
    cursor.execute("DELETE FROM mensajes WHERE id=%s", (id,))
    conn.commit()

# ===== MENU =====
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    kb = [
        [InlineKeyboardButton("📅 Programar", callback_data="prog")],
        [InlineKeyboardButton("📋 Ver", callback_data="ver")]
    ]
    await update.message.reply_text("Panel", reply_markup=InlineKeyboardMarkup(kb))

# ===== BOTONES =====
async def botones(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()

    if q.data == "ver":
        datos = obtener()

        for m in datos:
            id, texto, chat_id, fecha = m

            kb = [[
                InlineKeyboardButton("❌", callback_data=f"del_{id}")
            ]]

            await q.message.reply_text(
                f"{id} | {texto} | {fecha}",
                reply_markup=InlineKeyboardMarkup(kb)
            )

# ===== ELIMINAR =====
async def eliminar_btn(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()

    id = int(q.data.split("_")[1])
    eliminar(id)

    await q.message.reply_text("Eliminado")

# ===== RECIBIR =====
async def recibir(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        texto, fecha = update.message.text.split("|")
        fecha_dt = TIMEZONE.localize(datetime.strptime(fecha.strip(), "%Y-%m-%d %H:%M"))

        for canal in CANALES:
            guardar(texto.strip(), canal, fecha.strip())

            context.job_queue.run_once(
                lambda ctx: ctx.bot.send_message(canal, texto.strip()),
                when=fecha_dt
            )

        await update.message.reply_text("Programado")

    except:
        await update.message.reply_text("Formato: texto | YYYY-MM-DD HH:MM")

# ===== MAIN =====
def main():
    app = ApplicationBuilder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(botones))
    app.add_handler(CallbackQueryHandler(eliminar_btn, pattern="del_"))
    app.add_handler(MessageHandler(filters.TEXT, recibir))

    print("BOT OK 🔥")
    app.run_polling()

if __name__ == "__main__":
    main()
