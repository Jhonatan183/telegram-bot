import psycopg2
from datetime import datetime
import pytz

from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Updater, CommandHandler, CallbackQueryHandler, MessageHandler, Filters

TOKEN = "8192711687:AAFYKMnTNFrnYJooUZ6LPRFZ7A1RhElRJ5U"
DB_URL = "postgresql://postgres:sRkjAQLlMcBIsShoIMpCSsPTklMOsvoj@postgres.railway.internal:5432/railway"
ADMIN_ID = 5869414542

TIMEZONE = pytz.timezone("America/Bogota")

# ===== DB =====
conn = psycopg2.connect(DB_URL)
cursor = conn.cursor()

cursor.execute("""
CREATE TABLE IF NOT EXISTS mensajes (
    id SERIAL PRIMARY KEY,
    tipo TEXT,
    contenido TEXT,
    file_id TEXT,
    fecha TEXT
)
""")
conn.commit()

# ===== DB FUNCIONES =====
def guardar(tipo, contenido, file_id, fecha):
    cursor.execute(
        "INSERT INTO mensajes (tipo, contenido, file_id, fecha) VALUES (%s,%s,%s,%s)",
        (tipo, contenido, file_id, fecha)
    )
    conn.commit()

def obtener():
    cursor.execute("SELECT * FROM mensajes ORDER BY id DESC")
    return cursor.fetchall()

def eliminar(id):
    cursor.execute("DELETE FROM mensajes WHERE id=%s", (id,))
    conn.commit()

def actualizar(id, contenido, fecha):
    cursor.execute(
        "UPDATE mensajes SET contenido=%s, fecha=%s WHERE id=%s",
        (contenido, fecha, id)
    )
    conn.commit()

# ===== MENU =====
def start(update, context):
    kb = [
        [InlineKeyboardButton("📅 Programar", callback_data="prog")],
        [InlineKeyboardButton("📋 Panel", callback_data="panel")]
    ]
    update.message.reply_text("🔥 PANEL PRO", reply_markup=InlineKeyboardMarkup(kb))

# ===== PANEL BONITO =====
def panel(update, context):
    q = update.callback_query
    q.answer()

    datos = obtener()

    if not datos:
        q.message.reply_text("📭 No hay mensajes programados")
        return

    for m in datos[:10]:  # últimos 10
        id, tipo, contenido, file_id, fecha = m

        texto = contenido if contenido else "(sin texto)"

        msg = f"""
🆔 ID: {id}
📦 Tipo: {tipo}
📝 {texto[:50]}
⏰ {fecha}
"""

        kb = [[
            InlineKeyboardButton("✏️ Editar", callback_data=f"edit_{id}"),
            InlineKeyboardButton("❌ Eliminar", callback_data=f"del_{id}")
        ]]

        q.message.reply_text(msg, reply_markup=InlineKeyboardMarkup(kb))

# ===== BOTONES =====
def botones(update, context):
    q = update.callback_query
    q.answer()

    if q.data == "prog":
        q.message.reply_text("Envía texto, imagen o video")

    if q.data == "panel":
        panel(update, context)

    if q.data.startswith("del_"):
        id = int(q.data.split("_")[1])
        eliminar(id)
        q.message.reply_text("❌ Eliminado")

    if q.data.startswith("edit_"):
        id = int(q.data.split("_")[1])
        context.user_data["editando"] = id
        q.message.reply_text("✏️ Envía nuevo contenido")

# ===== PROGRAMAR =====
def enviar(context):
    data = context.job.context
    bot = context.bot

    if data["tipo"] == "texto":
        bot.send_message(data["chat"], data["contenido"])

    elif data["tipo"] == "foto":
        bot.send_photo(data["chat"], data["file_id"], caption=data["contenido"])

    elif data["tipo"] == "video":
        bot.send_video(data["chat"], data["file_id"], caption=data["contenido"])

# ===== RECIBIR =====
def recibir(update, context):

    if update.effective_user.id != ADMIN_ID:
        return

    msg = update.message

    # ===== EDITAR =====
    if "editando" in context.user_data:
        id = context.user_data["editando"]
        context.user_data["data_edit"] = msg.text
        context.user_data["esperando_fecha_edit"] = True
        update.message.reply_text("Ahora envía nueva fecha")
        return

    if context.user_data.get("esperando_fecha_edit"):
        try:
            fecha = msg.text
            actualizar(
                context.user_data["editando"],
                context.user_data["data_edit"],
                fecha
            )
            update.message.reply_text("✅ Editado")
            context.user_data.clear()
        except:
            update.message.reply_text("Error en formato")
        return

    # ===== ESPERANDO FECHA =====
    if context.user_data.get("esperando_fecha"):

        try:
            fecha = msg.text.strip()
            fecha_dt = TIMEZONE.localize(datetime.strptime(fecha, "%Y-%m-%d %H:%M"))

            data = context.user_data["data"]

            guardar(data["tipo"], data["contenido"], data["file_id"], fecha)

            context.job_queue.run_once(
                enviar,
                when=(fecha_dt - datetime.now()).total_seconds(),
                context=data
            )

            update.message.reply_text("✅ Programado")
            context.user_data.clear()

        except:
            update.message.reply_text("Formato: 2026-07-16 12:30")

        return

    # ===== TEXTO =====
    if msg.text:
        context.user_data["data"] = {
            "tipo": "texto",
            "contenido": msg.text,
            "file_id": None,
            "chat": msg.chat_id
        }
        context.user_data["esperando_fecha"] = True
        update.message.reply_text("Envía la fecha")

    # ===== FOTO =====
    elif msg.photo:
        file_id = msg.photo[-1].file_id

        context.user_data["data"] = {
            "tipo": "foto",
            "contenido": msg.caption or "",
            "file_id": file_id,
            "chat": msg.chat_id
        }
        context.user_data["esperando_fecha"] = True
        update.message.reply_text("Envía la fecha")

    # ===== VIDEO =====
    elif msg.video:
        file_id = msg.video.file_id

        context.user_data["data"] = {
            "tipo": "video",
            "contenido": msg.caption or "",
            "file_id": file_id,
            "chat": msg.chat_id
        }
        context.user_data["esperando_fecha"] = True
        update.message.reply_text("Envía la fecha")

# ===== MAIN =====
def main():
    updater = Updater(TOKEN, use_context=True)
    dp = updater.dispatcher

    dp.add_handler(CommandHandler("start", start))
    dp.add_handler(CallbackQueryHandler(botones))
    dp.add_handler(MessageHandler(Filters.all, recibir))

    print("🔥 BOT PRO TOTAL ACTIVO")
    updater.start_polling()
    updater.idle()

if __name__ == "__main__":
    main()
