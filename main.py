import psycopg2
from datetime import datetime
import pytz
from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Updater, CommandHandler, CallbackQueryHandler, MessageHandler, Filters

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

def start(update, context):
    kb = [
        [InlineKeyboardButton("📅 Programar", callback_data="prog")],
        [InlineKeyboardButton("📋 Ver", callback_data="ver")]
    ]
    update.message.reply_text("Panel", reply_markup=InlineKeyboardMarkup(kb))

def botones(update, context):
    query = update.callback_query
    query.answer()

    if query.data == "ver":
        datos = obtener()

        for m in datos:
            id, texto, chat_id, fecha = m

            kb = [[
                InlineKeyboardButton("❌", callback_data=f"del_{id}")
            ]]

            query.message.reply_text(
                f"{id} | {texto} | {fecha}",
                reply_markup=InlineKeyboardMarkup(kb)
            )

def eliminar_btn(update, context):
    query = update.callback_query
    query.answer()

    id = int(query.data.split("_")[1])
    eliminar(id)

    query.message.reply_text("Eliminado")

def recibir(update, context):
    try:
        texto, fecha = update.message.text.split("|")
        fecha_dt = datetime.strptime(fecha.strip(), "%Y-%m-%d %H:%M")

        for canal in CANALES:
            guardar(texto.strip(), canal, fecha.strip())

            context.job_queue.run_once(
                lambda ctx: ctx.bot.send_message(canal, texto.strip()),
                when=(fecha_dt - datetime.now()).total_seconds()
            )

        update.message.reply_text("Programado")

    except:
        update.message.reply_text("Formato: texto | YYYY-MM-DD HH:MM")

def main():
    updater = Updater(TOKEN, use_context=True)
    dp = updater.dispatcher

    dp.add_handler(CommandHandler("start", start))
    dp.add_handler(CallbackQueryHandler(botones))
    dp.add_handler(CallbackQueryHandler(eliminar_btn, pattern="del_"))
    dp.add_handler(MessageHandler(Filters.text, recibir))

    print("BOT FUNCIONANDO 🔥")
    updater.start_polling()
    updater.idle()

if __name__ == "__main__":
    main()
