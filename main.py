import psycopg2
from datetime import datetime
import pytz

from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Updater, CommandHandler, CallbackQueryHandler, MessageHandler, Filters

# ===== CONFIG =====
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

# ===== FUNCIONES DB SEGURAS =====
def guardar(tipo, contenido, file_id, fecha):
    try:
        cursor.execute(
            "INSERT INTO mensajes (tipo, contenido, file_id, fecha) VALUES (%s,%s,%s,%s)",
            (tipo, contenido, file_id, fecha)
        )
        conn.commit()
    except Exception as e:
        print("ERROR GUARDAR:", e)
        conn.rollback()

def obtener():
    try:
        cursor.execute("SELECT * FROM mensajes ORDER BY id DESC")
        return cursor.fetchall()
    except Exception as e:
        print("ERROR OBTENER:", e)
        conn.rollback()
        return []

def eliminar(id):
    try:
        cursor.execute("DELETE FROM mensajes WHERE id=%s", (id,))
        conn.commit()
    except Exception as e:
        print("ERROR ELIMINAR:", e)
        conn.rollback()

def actualizar(id, contenido, fecha):
    try:
        cursor.execute(
            "UPDATE mensajes SET contenido=%s, fecha=%s WHERE id=%s",
            (contenido, fecha, id)
        )
        conn.commit()
    except Exception as e:
        print("ERROR ACTUALIZAR:", e)
        conn.rollback()

# ===== MENU =====
def start(update, context):
    kb = [
        [InlineKeyboardButton("📅 Programar", callback_data="prog")],
        [InlineKeyboardButton("📋 Panel", callback_data="panel")]
    ]
    update.message.reply_text("🔥 PANEL PRO", reply_markup=InlineKeyboardMarkup(kb))

# ===== PANEL =====
def mostrar_panel(update, context):
    datos = obtener()

    if not datos:
        return "📭 No hay mensajes programados"

    texto = "📋 MENSAJES PROGRAMADOS\n\n"

    for m in datos[:10]:
        id, tipo, contenido, file_id, fecha = m
        contenido = contenido if contenido else "(sin texto)"

        texto += f"""🆔 {id}
📦 {tipo}
📝 {contenido[:40]}
⏰ {fecha}

"""

    return texto

# ===== BOTONES =====
def botones(update, context):
    q = update.callback_query
    q.answer()

    if q.data == "prog":
        q.message.reply_text("Envía texto, imagen o video")

    elif q.data == "panel":
        datos = obtener()

        if not datos:
            q.message.reply_text("📭 No hay mensajes")
            return

        for m in datos[:10]:
            id, tipo, contenido, file_id, fecha = m
            contenido = contenido if contenido else "(sin texto)"

            msg = f"""🆔 ID: {id}
📦 {tipo}
📝 {contenido[:40]}
⏰ {fecha}"""

            kb = [[
                InlineKeyboardButton("✏️ Editar", callback_data=f"edit_{id}"),
                InlineKeyboardButton("❌ Eliminar", callback_data=f"del_{id}")
            ]]

            q.message.reply_text(msg, reply_markup=InlineKeyboardMarkup(kb))

    elif q.data.startswith("del_"):
        id = int(q.data.split("_")[1])
        eliminar(id)
        q.message.reply_text("❌ Eliminado")

    elif q.data.startswith("edit_"):
        id = int(q.data.split("_")[1])
        context.user_data["editando"] = id
        q.message.reply_text("✏️ Envía nuevo contenido")

# ===== ENVÍO =====
def enviar(context):
    data = context.job.context
    bot = context.bot

    try:
        if data["tipo"] == "texto":
            bot.send_message(data["chat"], data["contenido"])

        elif data["tipo"] == "foto":
            bot.send_photo(data["chat"], data["file_id"], caption=data["contenido"])

        elif data["tipo"] == "video":
            bot.send_video(data["chat"], data["file_id"], caption=data["contenido"])

    except Exception as e:
        print("ERROR ENVIO:", e)

# ===== RECIBIR =====
def recibir(update, context):

    if update.effective_user.id != ADMIN_ID:
        return

    msg = update.message

    # ===== EDITAR =====
    if "editando" in context.user_data:
        context.user_data["nuevo_texto"] = msg.text
        context.user_data["esperando_fecha_edit"] = True
        update.message.reply_text("Ahora envía nueva fecha (YYYY-MM-DD HH:MM)")
        return

    if context.user_data.get("esperando_fecha_edit"):
        try:
            fecha = msg.text
            actualizar(
                context.user_data["editando"],
                context.user_data["nuevo_texto"],
                fecha
            )
            update.message.reply_text("✅ Editado")
            context.user_data.clear()
        except:
            update.message.reply_text("Formato incorrecto")
        return

    # ===== PROGRAMAR =====
    if context.user_data.get("esperando_fecha"):

        try:
            fecha = msg.text.strip()
            fecha_dt = TIMEZONE.localize(datetime.strptime(fecha, "%Y-%m-%d %H:%M"))

            data = context.user_data["data"]

            guardar(data["tipo"], data["contenido"], data["file_id"], fecha)

            delay = (fecha_dt - datetime.now()).total_seconds()

            if delay < 0:
                update.message.reply_text("❌ Fecha pasada")
                context.user_data.clear()
                return

            context.job_queue.run_once(enviar, when=delay, context=data)

            update.message.reply_text("✅ Programado")
            context.user_data.clear()

        except Exception as e:
            print("ERROR FECHA:", e)
            update.message.reply_text("Formato correcto:\n2026-07-16 12:30")

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
        update.message.reply_text("📅 Envía la fecha (YYYY-MM-DD HH:MM)")

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
        update.message.reply_text("📅 Envía la fecha")

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
        update.message.reply_text("📅 Envía la fecha")

# ===== MAIN =====
def main():
    updater = Updater(TOKEN, use_context=True)
    dp = updater.dispatcher

    dp.add_handler(CommandHandler("start", start))
    dp.add_handler(CallbackQueryHandler(botones))
    dp.add_handler(MessageHandler(Filters.all, recibir))

    print("🔥 BOT PRO ACTIVO")
    updater.start_polling()
    updater.idle()

if __name__ == "__main__":
    main()
