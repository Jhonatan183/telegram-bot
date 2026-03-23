import psycopg2
from datetime import datetime
import pytz
import matplotlib.pyplot as plt

from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Updater, CommandHandler, CallbackQueryHandler, MessageHandler, Filters

# ===== CONFIG =====
TOKEN = "8192711687:AAFYKMnTNFrnYJooUZ6LPRFZ7A1RhElRJ5U"
DB_URL = "postgresql://postgres:sRkjAQLlMcBIsShoIMpCSsPTklMOsvoj@postgres.railway.internal:5432/railway"

ADMINS = [5869414542]

TIMEZONE = pytz.timezone("America/Bogota")

# 🔥 TUS CANALES COMPLETOS
CANALES = {
    "Canal 1": -1001939817105,
    "Canal 2": -1002496825506,
    "Canal 3": -1001972632210,
    "Canal 4": -1002846744606,
    "Canal 5": -1002707167875,
    "Canal 6": -1002276974978
}

# ===== DB =====
conn = psycopg2.connect(DB_URL)
cursor = conn.cursor()

cursor.execute("""
CREATE TABLE IF NOT EXISTS mensajes (
    id SERIAL PRIMARY KEY,
    tipo TEXT,
    contenido TEXT,
    file_id TEXT,
    fecha TEXT,
    canal TEXT,
    enviado BOOLEAN DEFAULT FALSE
)
""")
conn.commit()

# ===== DB SEGURA =====
def guardar(tipo, contenido, file_id, fecha, canal):
    try:
        cursor.execute(
            "INSERT INTO mensajes (tipo, contenido, file_id, fecha, canal) VALUES (%s,%s,%s,%s,%s) RETURNING id",
            (tipo, contenido, file_id, fecha, canal)
        )
        id_msg = cursor.fetchone()[0]
        conn.commit()
        return id_msg
    except:
        conn.rollback()
        return None

def obtener():
    try:
        cursor.execute("SELECT * FROM mensajes ORDER BY id DESC")
        return cursor.fetchall()
    except:
        conn.rollback()
        return []

def eliminar(id):
    try:
        cursor.execute("DELETE FROM mensajes WHERE id=%s", (id,))
        conn.commit()
    except:
        conn.rollback()

def actualizar(id, contenido, fecha):
    try:
        cursor.execute(
            "UPDATE mensajes SET contenido=%s, fecha=%s WHERE id=%s",
            (contenido, fecha, id)
        )
        conn.commit()
    except:
        conn.rollback()

# ===== ESTADÍSTICAS =====
def estadisticas():
    try:
        cursor.execute("SELECT COUNT(*) FROM mensajes")
        total = cursor.fetchone()[0]

        cursor.execute("SELECT COUNT(*) FROM mensajes WHERE enviado=TRUE")
        enviados = cursor.fetchone()[0]

        cursor.execute("SELECT canal, COUNT(*) FROM mensajes GROUP BY canal")
        canales = cursor.fetchall()

        texto = f"📊 ESTADÍSTICAS\n\n📨 Total: {total}\n✅ Enviados: {enviados}\n\n"

        for c in canales:
            texto += f"📡 {c[0]}: {c[1]}\n"

        return texto
    except:
        conn.rollback()
        return "Error"

def grafico_estadisticas():
    try:
        cursor.execute("SELECT canal, COUNT(*) FROM mensajes GROUP BY canal")
        datos = cursor.fetchall()

        if not datos:
            return None

        canales = [d[0] for d in datos]
        cantidades = [d[1] for d in datos]

        plt.figure()
        plt.bar(canales, cantidades)
        plt.title("Mensajes por canal")

        ruta = "grafico.png"
        plt.savefig(ruta)
        plt.close()

        return ruta
    except:
        conn.rollback()
        return None

# ===== RECUPERACIÓN =====
def recuperar_mensajes(context):
    try:
        cursor.execute("SELECT * FROM mensajes WHERE enviado=FALSE")
        datos = cursor.fetchall()

        for m in datos:
            id, tipo, contenido, file_id, fecha, canal, enviado = m

            fecha_dt = TIMEZONE.localize(datetime.strptime(fecha, "%Y-%m-%d %H:%M"))
            delay = (fecha_dt - datetime.now()).total_seconds()

            if delay <= 0:
                continue

            context.job_queue.run_once(
                enviar,
                when=delay,
                context={
                    "id": id,
                    "tipo": tipo,
                    "contenido": contenido,
                    "file_id": file_id,
                    "canal": canal
                }
            )

        print("Mensajes recuperados:", len(datos))

    except:
        conn.rollback()

# ===== MENU =====
def start(update, context):
    texto = """🔥 BOT PRO MAX

📅 Programar contenido
📋 Ver panel
📊 Ver estadísticas
"""

    kb = [
        [InlineKeyboardButton("📅 Programar", callback_data="prog")],
        [InlineKeyboardButton("📋 Panel", callback_data="panel")],
        [InlineKeyboardButton("📊 Estadísticas", callback_data="stats")]
    ]

    update.message.reply_text(texto, reply_markup=InlineKeyboardMarkup(kb))

# ===== PANEL =====
def panel(update, context):
    q = update.callback_query
    q.answer()

    datos = obtener()

    if not datos:
        q.message.reply_text("Sin mensajes")
        return

    for m in datos[:10]:
        id, tipo, contenido, file_id, fecha, canal, enviado = m

        estado = "✅" if enviado else "⏳"

        kb = [[
            InlineKeyboardButton("✏️ Editar", callback_data=f"edit_{id}"),
            InlineKeyboardButton("❌ Eliminar", callback_data=f"del_{id}")
        ]]

        q.message.reply_text(
            f"🆔 {id}\n📡 {canal}\n📦 {tipo}\n⏰ {fecha}\n{estado}",
            reply_markup=InlineKeyboardMarkup(kb)
        )

# ===== BOTONES =====
def botones(update, context):
    q = update.callback_query
    q.answer()

    if q.data == "prog":
        kb = [[InlineKeyboardButton(c, callback_data=f"canal_{c}")]
              for c in CANALES.keys()]
        kb.append([InlineKeyboardButton("🔥 TODOS", callback_data="canal_all")])
        q.message.reply_text("Selecciona canal", reply_markup=InlineKeyboardMarkup(kb))

    elif q.data.startswith("canal_"):
        if q.data == "canal_all":
            context.user_data["canal"] = "ALL"
        else:
            context.user_data["canal"] = q.data.split("_")[1]

        q.message.reply_text("Envía contenido (texto, foto o video)")

    elif q.data == "panel":
        panel(update, context)

    elif q.data == "stats":
        q.message.reply_text(estadisticas())
        ruta = grafico_estadisticas()
        if ruta:
            q.message.reply_photo(photo=open(ruta, "rb"))

    elif q.data.startswith("del_"):
        eliminar(int(q.data.split("_")[1]))
        q.message.reply_text("Eliminado")

    elif q.data.startswith("edit_"):
        context.user_data["editando"] = int(q.data.split("_")[1])
        q.message.reply_text("Nuevo texto")

# ===== ENVÍO =====
def enviar(context):
    data = context.job.context
    bot = context.bot

    try:
        if data["canal"] == "ALL":
            for canal_id in CANALES.values():
                enviar_tipo(bot, canal_id, data)
        else:
            canal_id = CANALES[data["canal"]]
            enviar_tipo(bot, canal_id, data)

        cursor.execute("UPDATE mensajes SET enviado=TRUE WHERE id=%s", (data["id"],))
        conn.commit()

    except:
        conn.rollback()

def enviar_tipo(bot, canal_id, data):
    if data["tipo"] == "texto":
        bot.send_message(canal_id, data["contenido"])
    elif data["tipo"] == "foto":
        bot.send_photo(canal_id, data["file_id"], caption=data["contenido"])
    elif data["tipo"] == "video":
        bot.send_video(canal_id, data["file_id"], caption=data["contenido"])

# ===== RECIBIR =====
def recibir(update, context):

    if update.effective_user.id not in ADMINS:
        return

    msg = update.message

    if "editando" in context.user_data:
        context.user_data["nuevo"] = msg.text
        context.user_data["esperando_fecha_edit"] = True
        update.message.reply_text("Nueva fecha")
        return

    if context.user_data.get("esperando_fecha_edit"):
        actualizar(context.user_data["editando"], context.user_data["nuevo"], msg.text)
        context.user_data.clear()
        update.message.reply_text("Editado")
        return

    if context.user_data.get("esperando_fecha"):
        fecha = msg.text
        fecha_dt = TIMEZONE.localize(datetime.strptime(fecha, "%Y-%m-%d %H:%M"))

        data = context.user_data["data"]
        canal = context.user_data["canal"]

        id_msg = guardar(data["tipo"], data["contenido"], data["file_id"], fecha, canal)

        delay = (fecha_dt - datetime.now()).total_seconds()

        context.job_queue.run_once(
            enviar,
            when=delay,
            context={**data, "canal": canal, "id": id_msg}
        )

        context.user_data.clear()
        update.message.reply_text("Programado")
        return

    if msg.text:
        context.user_data["data"] = {"tipo": "texto", "contenido": msg.text, "file_id": None}
        context.user_data["esperando_fecha"] = True
        update.message.reply_text("Envía fecha")

    elif msg.photo:
        context.user_data["data"] = {
            "tipo": "foto",
            "contenido": msg.caption or "",
            "file_id": msg.photo[-1].file_id
        }
        context.user_data["esperando_fecha"] = True
        update.message.reply_text("Envía fecha")

    elif msg.video:
        context.user_data["data"] = {
            "tipo": "video",
            "contenido": msg.caption or "",
            "file_id": msg.video.file_id
        }
        context.user_data["esperando_fecha"] = True
        update.message.reply_text("Envía fecha")

# ===== MAIN =====
def main():
    updater = Updater(TOKEN, use_context=True)
    dp = updater.dispatcher

    dp.add_handler(CommandHandler("start", start))
    dp.add_handler(CallbackQueryHandler(botones))
    dp.add_handler(MessageHandler(Filters.all, recibir))

    print("🔥 BOT PRO FINAL ACTIVO")

    recuperar_mensajes(updater)

    updater.start_polling()
    updater.idle()

if __name__ == "__main__":
    main()
