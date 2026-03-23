import os
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
DB_URL = os.getenv("DATABASE_URL")

# ===== DB =====
import os

DB_URL = os.getenv("DATABASE_URL")

conn = psycopg2.connect(DB_URL)
cursor = conn.cursor()

cursor.execute("""
CREATE TABLE IF NOT EXISTS mensajes (
    id SERIAL PRIMARY KEY,
    tipo TEXT,
    texto TEXT,
    file_id TEXT,
    chat_id BIGINT,
    fecha TEXT
)
""")
conn.commit()

# ===== GUARDAR =====
def guardar(m):
    cursor.execute("""
    INSERT INTO mensajes (tipo, texto, file_id, chat_id, fecha)
    VALUES (%s, %s, %s, %s, %s)
    """, (m["tipo"], m["texto"], m["file_id"], m["chat_id"], m["fecha"]))
    conn.commit()

# ===== OBTENER =====
def obtener():
    cursor.execute("SELECT * FROM mensajes")
    return cursor.fetchall()

# ===== ELIMINAR =====
def eliminar(id):
    cursor.execute("DELETE FROM mensajes WHERE id=%s", (id,))
    conn.commit()

# ===== ACTUALIZAR =====
def actualizar(id, texto, fecha):
    cursor.execute("""
    UPDATE mensajes SET texto=%s, fecha=%s WHERE id=%s
    """, (texto, fecha, id))
    conn.commit()

# ===== ENVIAR =====
async def enviar(context):
    job = context.job.data
    bot = context.bot

    if job["tipo"] == "texto":
        await bot.send_message(job["chat_id"], job["texto"])
    elif job["tipo"] == "foto":
        await bot.send_photo(job["chat_id"], job["file_id"], caption=job["texto"])
    elif job["tipo"] == "video":
        await bot.send_video(job["chat_id"], job["file_id"], caption=job["texto"])

# ===== MENU =====
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return

    kb = [
        [InlineKeyboardButton("📅 Programar", callback_data="prog")],
        [InlineKeyboardButton("📋 Ver / Editar / Eliminar", callback_data="panel")]
    ]
    await update.message.reply_text("Panel PRO", reply_markup=InlineKeyboardMarkup(kb))

# ===== PANEL =====
async def panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()

    datos = obtener()

    if not datos:
        await q.message.reply_text("Vacío")
        return

    for m in datos:
        id, tipo, texto, file_id, chat_id, fecha = m

        kb = [
            [
                InlineKeyboardButton("✏️ Editar", callback_data=f"edit_{id}"),
                InlineKeyboardButton("❌ Eliminar", callback_data=f"del_{id}")
            ]
        ]

        await q.message.reply_text(
            f"ID:{id}\n{tipo}\n{fecha}",
            reply_markup=InlineKeyboardMarkup(kb)
        )

# ===== ELIMINAR BTN =====
async def eliminar_btn(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()

    id = int(q.data.split("_")[1])
    eliminar(id)

    await q.message.reply_text("❌ Eliminado")

# ===== EDITAR BTN =====
async def editar_btn(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()

    id = int(q.data.split("_")[1])
    context.user_data["editando"] = id

    await q.message.reply_text("Envía nuevo texto | YYYY-MM-DD HH:MM")

# ===== RECIBIR =====
async def recibir(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return

    # EDITAR
    if "editando" in context.user_data:
        try:
            texto, fecha = update.message.text.split("|")
            actualizar(context.user_data["editando"], texto.strip(), fecha.strip())
            context.user_data.clear()
            await update.message.reply_text("✅ Editado")
        except:
            await update.message.reply_text("Error formato")
        return

    # PROGRAMAR
    try:
        texto, fecha = update.message.text.split("|")
        fecha_dt = TIMEZONE.localize(datetime.strptime(fecha.strip(), "%Y-%m-%d %H:%M"))

        for canal in CANALES:
            m = {
                "tipo": "texto",
                "texto": texto.strip(),
                "file_id": None,
                "chat_id": canal,
                "fecha": fecha.strip()
            }

            guardar(m)

            context.job_queue.run_once(
                enviar,
                when=fecha_dt,
                data=m
            )

        await update.message.reply_text("✅ Programado en todos los canales")

    except:
        await update.message.reply_text("Formato: texto | YYYY-MM-DD HH:MM")

# ===== MAIN =====
app = ApplicationBuilder().token(TOKEN).build()

app.add_handler(CommandHandler("start", start))
app.add_handler(CallbackQueryHandler(panel, pattern="panel"))
app.add_handler(CallbackQueryHandler(eliminar_btn, pattern="del_"))
app.add_handler(CallbackQueryHandler(editar_btn, pattern="edit_"))
app.add_handler(MessageHandler(filters.TEXT, recibir))

app.run_polling()
