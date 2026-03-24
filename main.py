import psycopg2
from datetime import datetime, timedelta
import pytz
import matplotlib.pyplot as plt

from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Updater, CommandHandler, CallbackQueryHandler, MessageHandler, Filters

# ===== CONFIG =====
TOKEN = "8192711687:AAFYKMnTNFrnYJooUZ6LPRFZ7A1RhElRJ5U"
DB_URL = "postgresql://postgres:sRkjAQLlMcBIsShoIMpCSsPTklMOsvoj@postgres.railway.internal:5432/railway"
ADMINS = [5869414542]

TIMEZONE = pytz.timezone("America/Bogota")

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

# ===== FUNCIONES DB =====
def guardar(tipo, contenido, file_id, fecha, canal):
    cursor.execute(
        "INSERT INTO mensajes (tipo, contenido, file_id, fecha, canal) VALUES (%s,%s,%s,%s,%s) RETURNING id",
        (tipo, contenido, file_id, fecha, canal)
    )
    id_msg = cursor.fetchone()[0]
    conn.commit()
    return id_msg

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

# ===== ESTADÍSTICAS =====
def estadisticas():
    cursor.execute("SELECT COUNT(*) FROM mensajes")
    total = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(*) FROM mensajes WHERE enviado=TRUE")
    enviados = cursor.fetchone()[0]

    return f"📊 Total: {total}\n✅ Enviados: {enviados}"

def grafico():
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

# ===== RECUPERAR =====
def recuperar(context):
    cursor.execute("SELECT * FROM mensajes WHERE enviado=FALSE")
    for m in cursor.fetchall():
        id, tipo, contenido, file_id, fecha, canal, enviado = m

        try:
            fecha_dt = TIMEZONE.localize(datetime.strptime(fecha, "%Y-%m-%d %H:%M"))
        except:
            continue

        delay = (fecha_dt - datetime.now(TIMEZONE)).total_seconds()

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

# ===== CALENDARIO =====
def calendario(update, context):
    hoy = datetime.now(TIMEZONE)
    botones = []

    for i in range(15):
        dia = hoy + timedelta(days=i)
        fecha_str = dia.strftime("%Y-%m-%d")

        botones.append([
            InlineKeyboardButton(dia.strftime("%d %b"), callback_data=f"fecha_{fecha_str}")
        ])

    update.message.reply_text("📅 Selecciona día", reply_markup=InlineKeyboardMarkup(botones))

def horas(update, context):
    q = update.callback_query
    q.answer()

    fecha = q.data.split("_")[1]
    context.user_data["fecha"] = fecha

    botones = []
    for h in range(24):
        botones.append([InlineKeyboardButton(f"{h:02d}:00", callback_data=f"hora_{h:02d}")])

    q.message.reply_text("⏰ Selecciona hora", reply_markup=InlineKeyboardMarkup(botones))

def minutos(update, context):
    q = update.callback_query
    q.answer()

    botones = []
    fila = []

    for i in range(0, 60, 5):
        fila.append(InlineKeyboardButton(f"{i:02d}", callback_data=f"min_{i}"))
        if len(fila) == 6:
            botones.append(fila)
            fila = []

    if fila:
        botones.append(fila)

    q.message.reply_text("⏱ Selecciona minutos", reply_markup=InlineKeyboardMarkup(botones))

# ===== MENU =====
def start(update, context):
    kb = [
        [InlineKeyboardButton("📅 Programar", callback_data="prog")],
        [InlineKeyboardButton("📋 Panel", callback_data="panel")],
        [InlineKeyboardButton("📊 Estadísticas", callback_data="stats")]
    ]
    update.message.reply_text("🔥 BOT PRO", reply_markup=InlineKeyboardMarkup(kb))

# ===== PANEL =====
def panel(update, context):
    q = update.callback_query
    q.answer()

    datos = obtener()

    for m in datos[:10]:
        id, tipo, contenido, file_id, fecha, canal, enviado = m
        estado = "✅" if enviado else "⏳"

        kb = [[
            InlineKeyboardButton("✏️", callback_data=f"edit_{id}"),
            InlineKeyboardButton("❌", callback_data=f"del_{id}")
        ]]

        q.message.reply_text(f"{id} | {canal} | {fecha} | {estado}", reply_markup=InlineKeyboardMarkup(kb))

# ===== BOTONES =====
def botones(update, context):
    q = update.callback_query
    q.answer()

    data = q.data

    if data == "prog":
        kb = [[InlineKeyboardButton(c, callback_data=f"canal_{c}")]
              for c in CANALES.keys()]
        kb.append([InlineKeyboardButton("🔥 TODOS", callback_data="canal_all")])
        q.message.reply_text("Selecciona canal", reply_markup=InlineKeyboardMarkup(kb))

    elif data.startswith("canal_"):
        context.user_data["canal"] = "ALL" if data == "canal_all" else data.split("_")[1]
        q.message.reply_text("Envía contenido")

    elif data.startswith("fecha_"):
        horas(update, context)

    elif data.startswith("hora_"):
        context.user_data["hora"] = data.split("_")[1]
        minutos(update, context)

    elif data.startswith("min_"):
        minuto = data.split("_")[1]

        fecha = context.user_data.get("fecha")
        hora = context.user_data.get("hora")
        canal = context.user_data.get("canal")
        data_msg = context.user_data.get("data")

        fecha_final = f"{fecha} {hora}:{minuto}"

        fecha_dt = TIMEZONE.localize(datetime.strptime(fecha_final, "%Y-%m-%d %H:%M"))

        id_msg = guardar(data_msg["tipo"], data_msg["contenido"], data_msg["file_id"], fecha_final, canal)

        delay = (fecha_dt - datetime.now(TIMEZONE)).total_seconds()

        context.job_queue.run_once(
            enviar,
            when=delay,
            context={**data_msg, "canal": canal, "id": id_msg}
        )

        context.user_data.clear()
        q.message.reply_text("✅ Programado")

    elif data == "panel":
        panel(update, context)

    elif data == "stats":
        q.message.reply_text(estadisticas())
        ruta = grafico()
        if ruta:
            q.message.reply_photo(open(ruta, "rb"))

    elif data.startswith("del_"):
        eliminar(int(data.split("_")[1]))
        q.message.reply_text("Eliminado")

# ===== ENVÍO =====
def enviar(context):
    data = context.job.context
    bot = context.bot

    if data["canal"] == "ALL":
        for canal_id in CANALES.values():
            enviar_tipo(bot, canal_id, data)
    else:
        enviar_tipo(bot, CANALES[data["canal"]], data)

    cursor.execute("UPDATE mensajes SET enviado=TRUE WHERE id=%s", (data["id"],))
    conn.commit()

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

    if msg.text:
        context.user_data["data"] = {"tipo": "texto", "contenido": msg.text, "file_id": None}
        calendario(update, context)

    elif msg.photo:
        context.user_data["data"] = {
            "tipo": "foto",
            "contenido": msg.caption or "",
            "file_id": msg.photo[-1].file_id
        }
        calendario(update, context)

    elif msg.video:
        context.user_data["data"] = {
            "tipo": "video",
            "contenido": msg.caption or "",
            "file_id": msg.video.file_id
        }
        calendario(update, context)

# ===== MAIN =====
def main():
    updater = Updater(TOKEN, use_context=True)
    dp = updater.dispatcher

    dp.add_handler(CommandHandler("start", start))
    dp.add_handler(CallbackQueryHandler(botones))
    dp.add_handler(MessageHandler(Filters.all, recibir))

    recuperar(updater)

    updater.start_polling()
    updater.idle()

if __name__ == "__main__":
    main()
