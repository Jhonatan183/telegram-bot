import os
import re
import time
import json
import requests
import psycopg2
from psycopg2 import OperationalError
from datetime import datetime, timedelta
import pytz
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, InputMediaPhoto
from telegram.ext import Updater, CommandHandler, CallbackQueryHandler, MessageHandler, Filters

# ===== CONFIG =====
TOKEN = ("8192711687:AAEMnhydzn-R0QICph4Jy66Iv8etaTO3CbA")
DB_URL = ("postgresql://postgres:sRkjAQLlMcBIsShoIMpCSsPTklMOsvoj@centerbeam.proxy.rlwy.net:45270/railway")

ADMINS = [5869414542]
TIMEZONE = pytz.timezone("America/Bogota")
ALBUMS = {}  # almacena fotos de álbum temporalmente por user_id

# ===== TRADUCCIÓN =====
def traducir(texto, destino):
    try:
        url = "https://translate.googleapis.com/translate_a/single"
        params = {"client": "gtx", "sl": "es", "tl": destino, "dt": "t", "q": texto}
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
        r = requests.get(url, params=params, headers=headers, timeout=10)
        data = r.json()
        return "".join([s[0] for s in data[0] if s[0]])
    except Exception as e:
        print(f"❌ Error traduciendo a {destino}: {e}", flush=True)
        return texto

def extraer_emojis(texto):
    emoji_pattern = re.compile(
        "[\U00010000-\U0010ffff\U00002600-\U000027BF"
        "\U0001f300-\U0001f5ff\U0001f600-\U0001f64f"
        "\U0001f680-\U0001f6ff\U00002702-\U000027B0]+",
        flags=re.UNICODE
    )
    emojis = emoji_pattern.findall(texto)
    return " ".join(emojis) if emojis else ""

def construir_mensaje_trilingue(texto_es):
    emojis = extraer_emojis(texto_es)
    prefix = f"{emojis} " if emojis else ""
    texto_en = traducir(texto_es, "en")
    texto_it = traducir(texto_es, "it")
    return f"{prefix}{texto_es}\n\n{prefix}{texto_en}\n\n{prefix}{texto_it}"

# ===== CONEXIÓN DB =====
def get_connection():
    retries = 10
    for i in range(retries):
        try:
            c = psycopg2.connect(DB_URL)
            print("✅ Conectado a la base de datos", flush=True)
            return c
        except OperationalError as e:
            print(f"⏳ DB no disponible ({i+1}/{retries}): {e}", flush=True)
            time.sleep(5)
    raise Exception("❌ No se pudo conectar a la base de datos")

conn = get_connection()
cursor = conn.cursor()

# ===== CREAR Y MIGRAR TABLAS =====
cursor.execute("""
    CREATE TABLE IF NOT EXISTS mensajes (
        id SERIAL PRIMARY KEY,
        tipo TEXT,
        contenido TEXT,
        file_id TEXT,
        fecha TEXT,
        canal TEXT,
        enviado BOOLEAN DEFAULT FALSE,
        recurrente TEXT DEFAULT NULL,
        origin_chat_id BIGINT DEFAULT NULL,
        origin_msg_id BIGINT DEFAULT NULL,
        traducir BOOLEAN DEFAULT FALSE,
        file_ids TEXT DEFAULT NULL
    )
""")
cursor.execute("ALTER TABLE mensajes ADD COLUMN IF NOT EXISTS recurrente TEXT DEFAULT NULL")
cursor.execute("ALTER TABLE mensajes ADD COLUMN IF NOT EXISTS enviado BOOLEAN DEFAULT FALSE")
cursor.execute("ALTER TABLE mensajes ADD COLUMN IF NOT EXISTS origin_chat_id BIGINT DEFAULT NULL")
cursor.execute("ALTER TABLE mensajes ADD COLUMN IF NOT EXISTS origin_msg_id BIGINT DEFAULT NULL")
cursor.execute("ALTER TABLE mensajes ADD COLUMN IF NOT EXISTS traducir BOOLEAN DEFAULT FALSE")
cursor.execute("ALTER TABLE mensajes ADD COLUMN IF NOT EXISTS file_ids TEXT DEFAULT NULL")
cursor.execute("ALTER TABLE mensajes ADD COLUMN IF NOT EXISTS destinatarios TEXT DEFAULT NULL")

cursor.execute("""
    CREATE TABLE IF NOT EXISTS canales (
        id SERIAL PRIMARY KEY,
        nombre TEXT UNIQUE,
        canal_id BIGINT UNIQUE
    )
""")
cursor.execute("""
    CREATE TABLE IF NOT EXISTS tematicas (
        id SERIAL PRIMARY KEY,
        nombre TEXT NOT NULL UNIQUE
    )
""")
cursor.execute("ALTER TABLE canales ADD COLUMN IF NOT EXISTS tematica_id INTEGER")
cursor.execute("ALTER TABLE canales DROP CONSTRAINT IF EXISTS canales_tematica_id_fkey")
cursor.execute("""ALTER TABLE canales ADD CONSTRAINT canales_tematica_id_fkey
                FOREIGN KEY (tematica_id) REFERENCES tematicas(id) ON DELETE SET NULL""")
cursor.execute("INSERT INTO tematicas (nombre) VALUES ('General') ON CONFLICT (nombre) DO NOTHING")
cursor.execute("""UPDATE canales SET tematica_id = (SELECT id FROM tematicas WHERE nombre = 'General')
                WHERE tematica_id IS NULL""")
cursor.execute("""
    CREATE TABLE IF NOT EXISTS errores (
        id SERIAL PRIMARY KEY,
        fecha TEXT,
        error TEXT
    )
""")

cursor.execute("SELECT COUNT(*) FROM canales")
if cursor.fetchone()[0] == 0:
    canales_base = [
        ("Canal 1", -1001939817105),
        ("Canal 2", -1002496825506),
        ("Canal 3", -1001972632210),
        ("Canal 4", -1002846744606),
        ("Canal 5", -1002707167875),
        ("Canal 6", -1002276974978),
    ]
    for nombre, cid in canales_base:
        cursor.execute(
            "INSERT INTO canales (nombre, canal_id) VALUES (%s, %s) ON CONFLICT DO NOTHING",
            (nombre, cid)
        )
conn.commit()

# ===== UTILIDADES DB =====
def safe_execute(query, params=()):
    global conn, cursor
    try:
        cursor.execute(query, params)
    except Exception:
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute(query, params)

def log_error(e):
    try:
        fecha = datetime.now(TIMEZONE).strftime("%Y-%m-%d %H:%M:%S")
        safe_execute("INSERT INTO errores (fecha, error) VALUES (%s, %s)", (fecha, str(e)))
        conn.commit()
    except Exception:
        pass

def get_canales():
    safe_execute("SELECT nombre, canal_id FROM canales ORDER BY nombre")
    return {row[0]: row[1] for row in cursor.fetchall()}

def get_tematicas():
    safe_execute("SELECT id, nombre FROM tematicas ORDER BY nombre")
    return cursor.fetchall()

def get_canales_tematica(tematica_id):
    safe_execute("SELECT nombre, canal_id FROM canales WHERE tematica_id=%s ORDER BY nombre", (tematica_id,))
    return cursor.fetchall()

def get_destinatarios(canal, destinatarios=None):
    """Resuelve sólo los destinatarios congelados de un mensaje nuevo.
    Los mensajes antiguos sin instantánea conservan su comportamiento previo.
    """
    if destinatarios:
        return [int(cid) for cid in destinatarios]
    canales = get_canales()
    if canal == "ALL":
        return list(canales.values())
    return [canales[canal]] if canal in canales else []

# ===== FUNCIONES MENSAJES =====
def guardar(tipo, contenido, file_id, fecha, canal, recurrente=None,
            origin_chat_id=None, origin_msg_id=None, traducir_msg=False, file_ids=None,
            destinatarios=None):
    file_ids_str = ",".join(file_ids) if file_ids else None
    safe_execute(
        """INSERT INTO mensajes
           (tipo, contenido, file_id, fecha, canal, recurrente,
            origin_chat_id, origin_msg_id, traducir, file_ids, destinatarios)
           VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id""",
        (tipo, contenido, file_id, fecha, canal, recurrente,
         origin_chat_id, origin_msg_id, traducir_msg, file_ids_str,
         json.dumps(destinatarios) if destinatarios is not None else None)
    )
    id_msg = cursor.fetchone()[0]
    conn.commit()
    return id_msg

def obtener(solo_pendientes=False, solo_enviados=False, solo_recurrentes=False):
    condiciones = []
    if solo_pendientes:
        condiciones.append("enviado=FALSE")
    if solo_enviados:
        condiciones.append("enviado=TRUE")
    if solo_recurrentes:
        condiciones.append("recurrente IS NOT NULL")
    where = f"WHERE {' AND '.join(condiciones)}" if condiciones else ""
    safe_execute(f"SELECT id,tipo,contenido,file_id,fecha,canal,enviado,recurrente,origin_chat_id,origin_msg_id,traducir,file_ids,destinatarios FROM mensajes {where} ORDER BY id DESC")
    return cursor.fetchall()

def eliminar(id):
    safe_execute("DELETE FROM mensajes WHERE id=%s", (id,))
    conn.commit()

def actualizar_mensaje(id, contenido, fecha):
    safe_execute("UPDATE mensajes SET contenido=%s, fecha=%s WHERE id=%s", (contenido, fecha, id))
    conn.commit()

# ===== LIMPIEZA AUTOMÁTICA =====
def limpiar_viejos(context):
    try:
        fecha_limite = (datetime.now(TIMEZONE) - timedelta(days=30)).strftime("%Y-%m-%d %H:%M")
        safe_execute("DELETE FROM mensajes WHERE enviado=TRUE AND fecha < %s", (fecha_limite,))
        eliminados_msg = cursor.rowcount
        safe_execute("DELETE FROM errores WHERE fecha < %s", (fecha_limite,))
        eliminados_err = cursor.rowcount
        conn.commit()
        print(f"🧹 Limpieza: {eliminados_msg} mensajes y {eliminados_err} errores eliminados", flush=True)
    except Exception as e:
        log_error(e)

# ===== RESUMEN SEMANAL =====
def resumen_semanal(context):
    try:
        safe_execute("SELECT COUNT(*) FROM mensajes")
        total = cursor.fetchone()[0]
        safe_execute("SELECT COUNT(*) FROM mensajes WHERE enviado=TRUE")
        enviados = cursor.fetchone()[0]
        safe_execute("SELECT COUNT(*) FROM mensajes WHERE enviado=FALSE")
        pendientes = cursor.fetchone()[0]
        safe_execute("SELECT COUNT(*) FROM mensajes WHERE recurrente IS NOT NULL AND enviado=FALSE")
        recurrentes = cursor.fetchone()[0]
        safe_execute("SELECT canal, COUNT(*) FROM mensajes WHERE enviado=TRUE GROUP BY canal ORDER BY COUNT(*) DESC LIMIT 3")
        top_canales = cursor.fetchall()
        safe_execute("SELECT COUNT(*) FROM canales")
        n_canales = cursor.fetchone()[0]
        safe_execute("SELECT COUNT(*) FROM errores")
        n_errores = cursor.fetchone()[0]
        top_txt = "".join([f"  • {c}: {n} mensajes\n" for c, n in top_canales])
        texto = (
            f"📊 *Resumen Semanal — Bot PRO*\n"
            f"_{datetime.now(TIMEZONE).strftime('%d/%m/%Y')}_\n\n"
            f"📨 Total: {total} | ✅ Enviados: {enviados}\n"
            f"⏳ Pendientes: {pendientes} | 🔁 Recurrentes: {recurrentes}\n"
            f"📢 Canales: {n_canales} | 🚨 Errores: {n_errores}\n\n"
            f"🏆 *Top canales:*\n{top_txt or '  Sin datos aún'}"
        )
        for admin_id in ADMINS:
            try:
                context.bot.send_message(admin_id, texto, parse_mode="Markdown")
            except Exception as e:
                log_error(e)
    except Exception as e:
        log_error(e)

# ===== ESTADÍSTICAS =====
def estadisticas():
    safe_execute("SELECT COUNT(*) FROM mensajes")
    total = cursor.fetchone()[0]
    safe_execute("SELECT COUNT(*) FROM mensajes WHERE enviado=TRUE")
    enviados = cursor.fetchone()[0]
    safe_execute("SELECT COUNT(*) FROM mensajes WHERE enviado=FALSE")
    pendientes = cursor.fetchone()[0]
    safe_execute("SELECT COUNT(*) FROM mensajes WHERE recurrente IS NOT NULL AND enviado=FALSE")
    recurrentes = cursor.fetchone()[0]
    safe_execute("SELECT COUNT(*) FROM canales")
    n_canales = cursor.fetchone()[0]
    safe_execute("SELECT COUNT(*) FROM errores")
    n_errores = cursor.fetchone()[0]
    return (
        f"📊 *Estadísticas del Bot*\n\n"
        f"📨 Total mensajes: {total}\n"
        f"✅ Enviados: {enviados}\n"
        f"⏳ Pendientes: {pendientes}\n"
        f"🔁 Recurrentes activos: {recurrentes}\n"
        f"📢 Canales registrados: {n_canales}\n"
        f"🚨 Errores en log: {n_errores}"
    )

def grafico():
    safe_execute("SELECT canal, COUNT(*) FROM mensajes GROUP BY canal")
    datos = cursor.fetchall()
    if not datos:
        return None
    canales = [d[0] for d in datos]
    cantidades = [d[1] for d in datos]
    plt.figure(figsize=(8, 4))
    bars = plt.bar(canales, cantidades, color='steelblue')
    plt.title("Mensajes por canal")
    plt.xticks(rotation=15, ha='right')
    for bar, val in zip(bars, cantidades):
        plt.text(bar.get_x() + bar.get_width()/2, bar.get_height() + 0.1, str(val), ha='center')
    plt.tight_layout()
    ruta = "/tmp/grafico.png"
    plt.savefig(ruta)
    plt.close()
    return ruta

# ===== RECUPERAR AL INICIAR =====
def recuperar(dispatcher):
    safe_execute("SELECT id,tipo,contenido,file_id,fecha,canal,enviado,recurrente,origin_chat_id,origin_msg_id,traducir,file_ids,destinatarios FROM mensajes WHERE enviado=FALSE")
    for m in cursor.fetchall():
        id, tipo, contenido, file_id, fecha, canal, enviado, recurrente, origin_chat_id, origin_msg_id, traducir_msg, file_ids_str, destinatarios_str = m
        try:
            fecha_dt = TIMEZONE.localize(datetime.strptime(fecha, "%Y-%m-%d %H:%M"))
        except Exception:
            continue
        delay = (fecha_dt - datetime.now(TIMEZONE)).total_seconds()
        if delay <= 0:
            continue
        file_ids = file_ids_str.split(",") if file_ids_str else None
        dispatcher.job_queue.run_once(
            enviar, when=delay,
            context={
                "id": id, "tipo": tipo, "contenido": contenido,
                "file_id": file_id, "file_ids": file_ids,
                "canal": canal, "recurrente": recurrente,
                "fecha_str": fecha, "origin_chat_id": origin_chat_id,
                "origin_msg_id": origin_msg_id, "traducir": traducir_msg,
                "destinatarios": json.loads(destinatarios_str) if destinatarios_str else None
            }
        )

# ===== CALENDARIO =====
def calendario(update, context):
    hoy = datetime.now(TIMEZONE)
    botones = []
    fila = []
    for i in range(15):
        dia = hoy + timedelta(days=i)
        fecha_str = dia.strftime("%Y-%m-%d")
        fila.append(InlineKeyboardButton(dia.strftime("%d %b"), callback_data=f"fecha_{fecha_str}"))
        if len(fila) == 3:
            botones.append(fila)
            fila = []
    if fila:
        botones.append(fila)
    msg = update.message or update.callback_query.message
    msg.reply_text("📅 Selecciona el día:", reply_markup=InlineKeyboardMarkup(botones))

def mostrar_horas(update, context):
    q = update.callback_query
    q.answer()
    context.user_data["fecha"] = q.data.split("_")[1]
    botones = []
    fila = []
    for h in range(24):
        fila.append(InlineKeyboardButton(f"{h:02d}h", callback_data=f"hora_{h:02d}"))
        if len(fila) == 6:
            botones.append(fila)
            fila = []
    if fila:
        botones.append(fila)
    q.message.reply_text("⏰ Selecciona la hora:", reply_markup=InlineKeyboardMarkup(botones))

def mostrar_minutos(update, context):
    q = update.callback_query
    q.answer()
    context.user_data["hora"] = q.data.split("_")[1]
    botones = []
    fila = []
    for i in range(0, 60, 5):
        fila.append(InlineKeyboardButton(f"{i:02d}", callback_data=f"min_{i}"))
        if len(fila) == 6:
            botones.append(fila)
            fila = []
    if fila:
        botones.append(fila)
    q.message.reply_text("⏱ Selecciona los minutos:", reply_markup=InlineKeyboardMarkup(botones))

# ===== MENU PRINCIPAL =====
def start(update, context):
    if not update.effective_user or update.effective_user.id not in ADMINS:
        return
    context.user_data.clear()
    kb = [
        [InlineKeyboardButton("📅 Programar mensaje", callback_data="prog")],
        [InlineKeyboardButton("📋 Panel de mensajes", callback_data="panel_menu")],
        [InlineKeyboardButton("📢 Gestionar canales", callback_data="menu_canales")],
        [InlineKeyboardButton("📊 Estadísticas", callback_data="stats")]
    ]
    update.message.reply_text(
        "🔥 *BOT PRO* — Panel de control\n\nSelecciona una opción:",
        parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(kb)
    )

# ===== PANEL CON FILTROS =====
def panel_menu(update, context):
    q = update.callback_query
    q.answer()
    kb = [
        [InlineKeyboardButton("📋 Todos", callback_data="panel_filter_todos")],
        [InlineKeyboardButton("⏳ Pendientes", callback_data="panel_filter_pendientes")],
        [InlineKeyboardButton("✅ Enviados", callback_data="panel_filter_enviados")],
        [InlineKeyboardButton("🔁 Recurrentes", callback_data="panel_filter_recurrentes")],
        [InlineKeyboardButton("🔙 Menú principal", callback_data="main_menu")]
    ]
    q.message.reply_text("📋 *Panel de mensajes*\n\n¿Qué quieres ver?",
                         parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(kb))

def panel(update, context, filtro="todos"):
    q = update.callback_query
    q.answer()
    page = context.user_data.get("panel_page", 0)
    context.user_data["panel_filtro"] = filtro
    if filtro == "pendientes":
        datos = obtener(solo_pendientes=True)
    elif filtro == "enviados":
        datos = obtener(solo_enviados=True)
    elif filtro == "recurrentes":
        datos = obtener(solo_recurrentes=True)
    else:
        datos = obtener()
    total = len(datos)
    por_pagina = 5
    inicio = page * por_pagina
    fin = inicio + por_pagina
    pagina = datos[inicio:fin]
    if not pagina:
        kb = [[InlineKeyboardButton("🔙 Volver", callback_data="panel_menu")]]
        q.message.reply_text("📭 No hay mensajes en esta categoría.",
                             reply_markup=InlineKeyboardMarkup(kb))
        return
    filtro_txt = {"todos": "Todos", "pendientes": "⏳ Pendientes",
                  "enviados": "✅ Enviados", "recurrentes": "🔁 Recurrentes"}
    q.message.reply_text(
        f"*{filtro_txt.get(filtro, 'Todos')}* — Página {page+1} | Total: {total}",
        parse_mode="Markdown"
    )
    for m in pagina:
        id, tipo, contenido, file_id, fecha, canal, enviado, recurrente, _, _, traducir_msg, file_ids_str, _ = m
        estado = "✅ Enviado" if enviado else "⏳ Pendiente"
        rec = f" | 🔁 {recurrente}" if recurrente else ""
        trad = " | 🌐" if traducir_msg else ""
        n_fotos = f" | 📸{len(file_ids_str.split(','))}" if file_ids_str and tipo == "album" else ""
        texto = (
            f"*ID:* {id}\n*Canal:* {canal}\n"
            f"*Fecha:* {fecha}\n*Estado:* {estado}{rec}{trad}{n_fotos}\n*Tipo:* {tipo}"
        )
        kb = [[InlineKeyboardButton("👁 Ver detalle", callback_data=f"detalle_{id}")]]
        if not enviado:
            kb.append([
                InlineKeyboardButton("✏️ Editar", callback_data=f"edit_{id}"),
                InlineKeyboardButton("❌ Eliminar", callback_data=f"confirm_del_{id}")
            ])
        else:
            kb.append([InlineKeyboardButton("❌ Eliminar", callback_data=f"confirm_del_{id}")])
        q.message.reply_text(texto, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(kb))
    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton("⬅️ Anterior", callback_data=f"panel_page_{page-1}"))
    if fin < total:
        nav.append(InlineKeyboardButton("Siguiente ➡️", callback_data=f"panel_page_{page+1}"))
    nav_kb = []
    if nav:
        nav_kb.append(nav)
    nav_kb.append([InlineKeyboardButton("🔙 Filtros", callback_data="panel_menu")])
    q.message.reply_text("Navegación:", reply_markup=InlineKeyboardMarkup(nav_kb))

def ver_detalle(update, context, id_msg):
    q = update.callback_query
    q.answer()
    safe_execute("SELECT id,tipo,contenido,file_id,fecha,canal,enviado,recurrente,origin_chat_id,origin_msg_id,traducir,file_ids,destinatarios FROM mensajes WHERE id=%s", (id_msg,))
    m = cursor.fetchone()
    if not m:
        q.message.reply_text("❌ Mensaje no encontrado.")
        return
    id, tipo, contenido, file_id, fecha, canal, enviado, recurrente, _, _, traducir_msg, file_ids_str, _ = m
    estado = "✅ Enviado" if enviado else "⏳ Pendiente"
    n_fotos = f"\n<b>Fotos en álbum:</b> {len(file_ids_str.split(','))}" if file_ids_str and tipo == "album" else ""
    texto = (
        f"👁 <b>Detalle #{id}</b>\n\n"
        f"<b>Canal:</b> {canal}\n<b>Fecha:</b> {fecha}\n"
        f"<b>Estado:</b> {estado}\n<b>Tipo:</b> {tipo}\n"
        f"<b>Recurrente:</b> {recurrente or 'No'}\n"
        f"<b>Trilingüe:</b> {'Sí 🌐' if traducir_msg else 'No'}"
        f"{n_fotos}\n\n"
        f"<b>Contenido:</b>\n{contenido or '<i>(archivo multimedia)</i>'}"
    )
    kb = [[InlineKeyboardButton("🔙 Volver",
           callback_data=f"panel_filter_{context.user_data.get('panel_filtro', 'todos')}")]]
    if not enviado:
        kb.insert(0, [
            InlineKeyboardButton("✏️ Editar", callback_data=f"edit_{id}"),
            InlineKeyboardButton("❌ Eliminar", callback_data=f"confirm_del_{id}")
        ])
    q.message.reply_text(texto, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(kb))

# ===== GESTIÓN DE CANALES =====
def menu_canales(update, context):
    q = update.callback_query
    q.answer()
    temas = get_tematicas()
    texto = "📁 *Temáticas*\n\nSelecciona una temática para administrar sus canales."
    kb = [
        [InlineKeyboardButton(nombre, callback_data=f"tema_{tema_id}")] for tema_id, nombre in temas
    ] + [
        [InlineKeyboardButton("➕ Nueva temática", callback_data="tema_nueva")],
        [InlineKeyboardButton("🔙 Menú principal", callback_data="main_menu")]
    ]
    q.message.reply_text(texto, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(kb))

def ver_tematica(update, context, tema_id):
    q = update.callback_query
    safe_execute("SELECT nombre FROM tematicas WHERE id=%s", (tema_id,))
    fila = cursor.fetchone()
    if not fila:
        q.message.reply_text("❌ Temática no encontrada.")
        return
    canales = get_canales_tematica(tema_id)
    texto = f"📁 *{fila[0]}*\n\n" + ("".join(f"📢 *{n}*: `{cid}`\n" for n, cid in canales) if canales else "_Sin canales_")
    kb = [
        [InlineKeyboardButton("➕ Agregar canal", callback_data=f"tema_add_{tema_id}")],
        [InlineKeyboardButton("✏️ Editar temática", callback_data=f"tema_edit_{tema_id}")],
        [InlineKeyboardButton("🗑 Eliminar temática", callback_data=f"tema_del_{tema_id}")],
        [InlineKeyboardButton("✏️ Editar canal", callback_data=f"tema_editcanal_{tema_id}")],
        [InlineKeyboardButton("🗑 Eliminar canal", callback_data=f"tema_delcanal_{tema_id}")],
        [InlineKeyboardButton("🔄 Mover canal", callback_data=f"tema_move_{tema_id}")],
        [InlineKeyboardButton("⬅️ Volver", callback_data="menu_canales")]
    ]
    q.message.reply_text(texto, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(kb))

def hacer_addcanal(update, context):
    if not update.effective_user or update.effective_user.id not in ADMINS:
        return
    args = context.args
    if len(args) < 2:
        update.message.reply_text(
            "❌ Uso:\n`/addcanal NombreCanal -100xxxxxxxxxx`", parse_mode="Markdown")
        return
    nombre = args[0]
    try:
        canal_id = int(args[1])
    except ValueError:
        update.message.reply_text("❌ El ID debe ser número.", parse_mode="Markdown")
        return
    try:
        safe_execute("INSERT INTO canales (nombre, canal_id, tematica_id) VALUES (%s, %s, (SELECT id FROM tematicas WHERE nombre='General'))", (nombre, canal_id))
        conn.commit()
        update.message.reply_text(f"✅ Canal *{nombre}* agregado.", parse_mode="Markdown")
    except Exception:
        conn.rollback()
        update.message.reply_text("❌ Ese nombre o ID ya existe.", parse_mode="Markdown")

def cmd_canales(update, context):
    if not update.effective_user or update.effective_user.id not in ADMINS:
        return
    canales = get_canales()
    if not canales:
        update.message.reply_text("📭 No hay canales registrados.")
        return
    texto = "📢 *Canales:*\n\n" + "".join([f"• *{n}*: `{c}`\n" for n, c in canales.items()])
    update.message.reply_text(texto, parse_mode="Markdown")

def cmd_delcanal(update, context):
    if not update.effective_user or update.effective_user.id not in ADMINS:
        return
    canales = get_canales()
    if not canales:
        update.message.reply_text("📭 No hay canales para eliminar.")
        return
    botones = [[InlineKeyboardButton(f"🗑 {n}", callback_data=f"delcanal_{n}")] for n in canales]
    update.message.reply_text("Selecciona el canal:", reply_markup=InlineKeyboardMarkup(botones))

# ===== ENVÍO =====
def enviar(context):
    data = context.job.context
    bot = context.bot
    try:
        # Para las nuevas programaciones se usa una instantánea; nunca la lista global.
        for canal_id in get_destinatarios(data["canal"], data.get("destinatarios")):
            enviar_tipo(bot, canal_id, data)
        safe_execute("UPDATE mensajes SET enviado=TRUE WHERE id=%s", (data["id"],))
        conn.commit()
        if data.get("recurrente"):
            recurrente = data["recurrente"]
            fecha_actual = datetime.strptime(data["fecha_str"], "%Y-%m-%d %H:%M")
            nueva_fecha = fecha_actual + (timedelta(days=1) if recurrente == "diario" else timedelta(weeks=1))
            nueva_fecha_str = nueva_fecha.strftime("%Y-%m-%d %H:%M")
            nuevo_id = guardar(
                data["tipo"], data["contenido"], data["file_id"],
                nueva_fecha_str, data["canal"], recurrente,
                data.get("origin_chat_id"), data.get("origin_msg_id"),
                data.get("traducir", False), data.get("file_ids"), data.get("destinatarios")
            )
            delay = (TIMEZONE.localize(nueva_fecha) - datetime.now(TIMEZONE)).total_seconds()
            if delay > 0:
                context.job_queue.run_once(
                    enviar, when=delay,
                    context={**data, "id": nuevo_id, "fecha_str": nueva_fecha_str}
                )
    except Exception as e:
        log_error(e)
        print(f"❌ Error en envío: {e}", flush=True)

def enviar_tipo(bot, canal_id, data):
    try:
        usar_traduccion = data.get("traducir", False)

        # ÁLBUM DE FOTOS
        if data["tipo"] == "album":
            fotos = data.get("file_ids") or []
            caption = data.get("contenido", "") or ""
            if usar_traduccion and caption:
                caption = construir_mensaje_trilingue(caption)
            media = []
            for i, fid in enumerate(fotos):
                if i == 0:
                    media.append(InputMediaPhoto(fid, caption=caption))
                else:
                    media.append(InputMediaPhoto(fid))
            if media:
                bot.send_media_group(canal_id, media)
            return

        # TEXTO CON TRADUCCIÓN
        if usar_traduccion and data["tipo"] == "texto":
            bot.send_message(canal_id, construir_mensaje_trilingue(data["contenido"]))
            return

        # FOTO CON TRADUCCIÓN EN CAPTION
        if usar_traduccion and data["tipo"] == "foto":
            caption = construir_mensaje_trilingue(data["contenido"]) if data.get("contenido") else ""
            bot.send_photo(canal_id, data["file_id"], caption=caption)
            return

        # VIDEO CON TRADUCCIÓN EN CAPTION
        if usar_traduccion and data["tipo"] == "video":
            caption = construir_mensaje_trilingue(data["contenido"]) if data.get("contenido") else ""
            bot.send_video(canal_id, data["file_id"], caption=caption)
            return

        # COPY_MESSAGE (preserva emojis premium)
        if data.get("origin_chat_id") and data.get("origin_msg_id"):
            bot.copy_message(
                chat_id=canal_id,
                from_chat_id=data["origin_chat_id"],
                message_id=data["origin_msg_id"]
            )
            return

        # ENVÍO NORMAL
        if data["tipo"] == "texto":
            bot.send_message(canal_id, data["contenido"], parse_mode="HTML")
        elif data["tipo"] == "foto":
            bot.send_photo(canal_id, data["file_id"],
                          caption=data.get("contenido", ""), parse_mode="HTML")
        elif data["tipo"] == "video":
            bot.send_video(canal_id, data["file_id"],
                          caption=data.get("contenido", ""), parse_mode="HTML")
    except Exception as e:
        log_error(e)
        print(f"❌ Error enviando a {canal_id}: {e}", flush=True)

# ===== VISTA PREVIA =====
def vista_previa(update, context):
    q = update.callback_query
    data_msg = context.user_data.get("data")
    canal = context.user_data.get("canal", "?")
    fecha = context.user_data.get("fecha_final", "?")
    recurrente = context.user_data.get("recurrente")
    traducir_msg = context.user_data.get("traducir", False)
    rec_txt = f"\n🔁 Recurrencia: {recurrente}" if recurrente else ""
    trad_txt = "\n🌐 Se enviará en ES / EN / IT" if traducir_msg else ""
    tipo = data_msg.get("tipo", "")
    n_fotos = f"\n📸 Álbum de {len(data_msg.get('file_ids', []))} fotos" if tipo == "album" else ""
    texto = (
        f"👁 *Vista previa*\n\n"
        f"📢 Canal: {canal}\n📅 Fecha: {fecha}{rec_txt}{trad_txt}{n_fotos}\n"
        f"📝 Tipo: {tipo}\n\n"
        f"*Contenido:*\n{data_msg.get('contenido') or '_(archivo multimedia)_'}"
    )
    kb = [
        [InlineKeyboardButton("✅ Confirmar y programar", callback_data="confirmar_envio")],
        [InlineKeyboardButton("❌ Cancelar", callback_data="main_menu")]
    ]
    q.message.reply_text(texto, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(kb))

# ===== PROCESAR ÁLBUM =====
def procesar_album(context):
    user_id = context.job.context["user_id"]
    update = context.job.context["update"]
    ctx = context.job.context["ctx"]
    if user_id not in ALBUMS:
        return
    album_data = ALBUMS.pop(user_id)
    fotos = album_data.get("fotos", [])
    caption = album_data.get("caption", "")
    if not fotos:
        return
    ctx.user_data["data"] = {
        "tipo": "album",
        "contenido": caption,
        "file_id": fotos[0],
        "file_ids": fotos,
        "origin_chat_id": None,
        "origin_msg_id": None
    }
    update.message.reply_text(
        f"📸 Álbum de *{len(fotos)} fotos* recibido. Ahora selecciona el día:",
        parse_mode="Markdown"
    )
    calendario(update, ctx)

# ===== MANEJADOR CENTRAL DE BOTONES =====
def botones(update, context):
    if not update.effective_user or update.effective_user.id not in ADMINS:
        return
    q = update.callback_query
    q.answer()
    data = q.data

    if data == "main_menu":
        context.user_data.clear()
        kb = [
            [InlineKeyboardButton("📅 Programar mensaje", callback_data="prog")],
            [InlineKeyboardButton("📋 Panel de mensajes", callback_data="panel_menu")],
            [InlineKeyboardButton("📢 Gestionar canales", callback_data="menu_canales")],
            [InlineKeyboardButton("📊 Estadísticas", callback_data="stats")]
        ]
        q.message.reply_text("🔥 *BOT PRO* — Panel de control",
                             parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(kb))

    elif data == "prog":
        temas = get_tematicas()
        kb = [[InlineKeyboardButton(nombre, callback_data=f"enviar_tema_{tema_id}")] for tema_id, nombre in temas]
        kb.append([InlineKeyboardButton("🔙 Menú principal", callback_data="main_menu")])
        q.message.reply_text("📁 Selecciona la temática:", reply_markup=InlineKeyboardMarkup(kb))

    elif data.startswith("enviar_tema_"):
        tema_id = int(data.rsplit("_", 1)[1])
        safe_execute("SELECT nombre FROM tematicas WHERE id=%s", (tema_id,))
        tema = cursor.fetchone()
        canales = get_canales_tematica(tema_id)
        if not tema or not canales:
            q.message.reply_text("❌ Esta temática no tiene canales. Agrega uno primero.")
            return
        context.user_data["canal"] = "TEMATICA"
        context.user_data["tematica_id"] = tema_id
        context.user_data["destinatarios"] = [cid for _, cid in canales]
        q.message.reply_text(
            f"📁 Temática: *{tema[0]}*\n\n📢 Canales asociados:\n" +
            "\n".join(f"☑ {nombre}" for nombre, _ in canales) +
            "\n\n📨 Envíame el contenido\n_(texto, foto, video o varias fotos para álbum)_",
            parse_mode="Markdown"
        )

    elif data.startswith("canal_"):
        context.user_data["canal"] = data.replace("canal_", "", 1)
        q.message.reply_text(
            "📨 Envíame el contenido\n_(texto, foto, video o varias fotos para álbum)_",
            parse_mode="Markdown"
        )

    elif data.startswith("fecha_"):
        mostrar_horas(update, context)

    elif data.startswith("hora_"):
        mostrar_minutos(update, context)

    elif data.startswith("min_"):
        minuto = data.split("_")[1]
        fecha = context.user_data.get("fecha")
        hora = context.user_data.get("hora")
        canal = context.user_data.get("canal")
        data_msg = context.user_data.get("data")
        if not all([fecha, hora, canal, data_msg]):
            q.message.reply_text("❌ Faltan datos. Empieza de nuevo con /start")
            return
        context.user_data["fecha_final"] = f"{fecha} {hora}:{minuto}"
        kb = [
            [InlineKeyboardButton("📅 Solo una vez", callback_data="rec_none")],
            [InlineKeyboardButton("🔁 Diario", callback_data="rec_diario")],
            [InlineKeyboardButton("📆 Semanal", callback_data="rec_semanal")]
        ]
        q.message.reply_text("🔁 ¿Con qué frecuencia?", reply_markup=InlineKeyboardMarkup(kb))

    elif data.startswith("rec_"):
        context.user_data["recurrente"] = None if data == "rec_none" else data.replace("rec_", "")
        data_msg = context.user_data.get("data", {})
        tipo = data_msg.get("tipo", "")
        if tipo in ("texto", "foto", "video", "album"):
            kb = [
                [InlineKeyboardButton("🌐 Sí, traducir (ES / EN / IT)", callback_data="trad_si")],
                [InlineKeyboardButton("❌ No, solo español", callback_data="trad_no")]
            ]
            q.message.reply_text(
                "🌐 ¿Enviar en 3 idiomas?\n_Español, Inglés e Italiano_",
                parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(kb)
            )
        else:
            context.user_data["traducir"] = False
            vista_previa(update, context)

    elif data == "trad_si":
        context.user_data["traducir"] = True
        vista_previa(update, context)

    elif data == "trad_no":
        context.user_data["traducir"] = False
        vista_previa(update, context)

    elif data == "confirmar_envio":
        fecha_final = context.user_data.get("fecha_final")
        canal = context.user_data.get("canal")
        data_msg = context.user_data.get("data")
        recurrente = context.user_data.get("recurrente")
        traducir_msg = context.user_data.get("traducir", False)
        try:
            fecha_dt = TIMEZONE.localize(datetime.strptime(fecha_final, "%Y-%m-%d %H:%M"))
        except Exception:
            q.message.reply_text("❌ Error al procesar la fecha.")
            return
        delay = (fecha_dt - datetime.now(TIMEZONE)).total_seconds()
        if delay <= 0:
            q.message.reply_text("❌ La fecha ya pasó.")
            return
        id_msg = guardar(
            data_msg["tipo"], data_msg.get("contenido", ""), data_msg.get("file_id"),
            fecha_final, canal, recurrente,
            data_msg.get("origin_chat_id"), data_msg.get("origin_msg_id"),
            traducir_msg, data_msg.get("file_ids"), context.user_data.get("destinatarios")
        )
        context.job_queue.run_once(
            enviar, when=delay,
            context={
                **data_msg, "canal": canal, "id": id_msg,
                "recurrente": recurrente, "fecha_str": fecha_final,
                "traducir": traducir_msg,
                "destinatarios": context.user_data.get("destinatarios")
            }
        )
        rec_txt = f" | 🔁 {recurrente}" if recurrente else ""
        trad_txt = " | 🌐 Trilingüe" if traducir_msg else ""
        q.message.reply_text(f"✅ *Programado para {fecha_final}*{rec_txt}{trad_txt}",
                             parse_mode="Markdown")
        context.user_data.clear()

    elif data == "panel_menu":
        panel_menu(update, context)
    elif data == "panel_filter_todos":
        context.user_data["panel_page"] = 0
        panel(update, context, filtro="todos")
    elif data == "panel_filter_pendientes":
        context.user_data["panel_page"] = 0
        panel(update, context, filtro="pendientes")
    elif data == "panel_filter_enviados":
        context.user_data["panel_page"] = 0
        panel(update, context, filtro="enviados")
    elif data == "panel_filter_recurrentes":
        context.user_data["panel_page"] = 0
        panel(update, context, filtro="recurrentes")
    elif data.startswith("panel_page_"):
        context.user_data["panel_page"] = int(data.split("_")[2])
        panel(update, context, filtro=context.user_data.get("panel_filtro", "todos"))
    elif data.startswith("detalle_"):
        ver_detalle(update, context, int(data.split("_")[1]))
    elif data.startswith("confirm_del_"):
        id_msg = int(data.split("_")[2])
        kb = [[
            InlineKeyboardButton("✅ Sí, eliminar", callback_data=f"eliminar_{id_msg}"),
            InlineKeyboardButton("❌ Cancelar", callback_data="panel_menu")
        ]]
        q.message.reply_text("⚠️ ¿Seguro que quieres eliminar este mensaje?",
                             reply_markup=InlineKeyboardMarkup(kb))
    elif data.startswith("eliminar_"):
        eliminar(int(data.split("_")[1]))
        q.message.reply_text("🗑 Eliminado correctamente.")
    elif data.startswith("edit_"):
        context.user_data["editando_id"] = int(data.split("_")[1])
        q.message.reply_text("✏️ Envíame el nuevo texto:")
    elif data == "stats":
        q.message.reply_text(estadisticas(), parse_mode="Markdown")
        ruta = grafico()
        if ruta:
            q.message.reply_photo(open(ruta, "rb"))
    elif data == "menu_canales":
        menu_canales(update, context)
    elif data.startswith("tema_") and len(data.split("_")) == 2 and data.rsplit("_", 1)[1].isdigit():
        ver_tematica(update, context, int(data.rsplit("_", 1)[1]))
    elif data == "tema_nueva":
        context.user_data["accion_tematica"] = "nueva"
        q.message.reply_text("➕ Envía el nombre de la nueva temática:")
    elif data.startswith("tema_add_"):
        context.user_data["accion_canal"] = ("nuevo", int(data.rsplit("_", 1)[1]))
        q.message.reply_text("➕ Envía `Nombre del canal | -100xxxxxxxxxx`", parse_mode="Markdown")
    elif data.startswith("tema_edit_"):
        context.user_data["accion_tematica"] = ("editar", int(data.rsplit("_", 1)[1]))
        q.message.reply_text("✏️ Envía el nuevo nombre de la temática:")
    elif data.startswith("tema_del_"):
        tema_id = int(data.rsplit("_", 1)[1])
        kb = [[InlineKeyboardButton("✅ Confirmar", callback_data=f"tema_confirmdel_{tema_id}"), InlineKeyboardButton("❌ Cancelar", callback_data="menu_canales")]]
        q.message.reply_text("⚠️ La temática se eliminará y sus canales pasarán a General. ¿Continuar?", reply_markup=InlineKeyboardMarkup(kb))
    elif data.startswith("tema_confirmdel_"):
        tema_id = int(data.rsplit("_", 1)[1])
        safe_execute("SELECT id FROM tematicas WHERE nombre='General'")
        general_id = cursor.fetchone()[0]
        if tema_id == general_id:
            q.message.reply_text("❌ La temática General conserva los canales existentes y no se puede eliminar.")
            return
        safe_execute("UPDATE canales SET tematica_id=%s WHERE tematica_id=%s", (general_id, tema_id))
        safe_execute("DELETE FROM tematicas WHERE id=%s AND nombre <> 'General'", (tema_id,))
        conn.commit()
        q.message.reply_text("🗑 Temática eliminada; los canales quedaron en General.")
    elif data.startswith("tema_delcanal_") or data.startswith("tema_editcanal_") or data.startswith("tema_move_"):
        accion, tema_id = data.split("_")[1], int(data.rsplit("_", 1)[1])
        canales = get_canales_tematica(tema_id)
        if not canales:
            q.message.reply_text("📭 No hay canales en esta temática.")
            return
        prefijo = {"delcanal": "borrarcanal", "editcanal": "editarcanal", "move": "movercanal"}[accion]
        kb = [[InlineKeyboardButton(nombre, callback_data=f"{prefijo}_{cid}_{tema_id}")] for nombre, cid in canales]
        q.message.reply_text("Selecciona el canal:", reply_markup=InlineKeyboardMarkup(kb))
    elif data.startswith("borrarcanal_"):
        _, canal_id, tema_id = data.split("_")
        kb = [[InlineKeyboardButton("✅ Confirmar", callback_data=f"confirmarborrar_{canal_id}"), InlineKeyboardButton("❌ Cancelar", callback_data=f"tema_{tema_id}")]]
        q.message.reply_text("⚠️ ¿Seguro que quieres eliminar este canal? Sólo se desvinculará del bot.", reply_markup=InlineKeyboardMarkup(kb))
    elif data.startswith("confirmarborrar_"):
        safe_execute("DELETE FROM canales WHERE canal_id=%s", (int(data.rsplit("_", 1)[1]),))
        conn.commit()
        q.message.reply_text("🗑 Canal desvinculado correctamente.")
    elif data.startswith("editarcanal_"):
        _, canal_id, tema_id = data.split("_")
        context.user_data["accion_canal"] = ("editar", int(canal_id), int(tema_id))
        q.message.reply_text("✏️ Envía `Nuevo nombre | -100xxxxxxxxxx`", parse_mode="Markdown")
    elif data.startswith("movercanal_"):
        _, canal_id, tema_id = data.split("_")
        destinos = [(tid, nombre) for tid, nombre in get_tematicas() if tid != int(tema_id)]
        kb = [[InlineKeyboardButton(nombre, callback_data=f"confirmarmover_{canal_id}_{tid}")] for tid, nombre in destinos]
        q.message.reply_text("🔄 Mover a:", reply_markup=InlineKeyboardMarkup(kb))
    elif data.startswith("confirmarmover_"):
        _, canal_id, destino_id = data.split("_")
        safe_execute("UPDATE canales SET tematica_id=%s WHERE canal_id=%s", (int(destino_id), int(canal_id)))
        conn.commit()
        q.message.reply_text("✅ Canal movido correctamente.")
    elif data == "add_canal":
        q.message.reply_text(
            "➕ Usa:\n`/addcanal NombreCanal -100xxxxxxxxxx`", parse_mode="Markdown")
    elif data == "del_canal_menu":
        canales = get_canales()
        if not canales:
            q.message.reply_text("📭 No hay canales.")
            return
        blist = [[InlineKeyboardButton(f"🗑 {n}", callback_data=f"delcanal_{n}")] for n in canales]
        blist.append([InlineKeyboardButton("🔙 Volver", callback_data="menu_canales")])
        q.message.reply_text("Selecciona:", reply_markup=InlineKeyboardMarkup(blist))
    elif data.startswith("delcanal_"):
        nombre = data.replace("delcanal_", "", 1)
        kb = [[
            InlineKeyboardButton("✅ Sí", callback_data=f"confirmar_delcanal_{nombre}"),
            InlineKeyboardButton("❌ No", callback_data="menu_canales")
        ]]
        q.message.reply_text(f"⚠️ ¿Eliminar *{nombre}*?",
                             parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(kb))
    elif data.startswith("confirmar_delcanal_"):
        nombre = data.replace("confirmar_delcanal_", "", 1)
        safe_execute("DELETE FROM canales WHERE nombre=%s", (nombre,))
        conn.commit()
        q.message.reply_text(f"🗑 Canal *{nombre}* eliminado.", parse_mode="Markdown")

# ===== RECIBIR MENSAJES =====
def recibir(update, context):
    if not update.effective_user or update.effective_user.id not in ADMINS:
        return
    if not update.message:
        return
    msg = update.message
    user_id = update.effective_user.id

    if msg.text and "accion_tematica" in context.user_data:
        accion = context.user_data.pop("accion_tematica")
        nombre = msg.text.strip()
        try:
            if not nombre:
                raise ValueError("El nombre no puede estar vacío.")
            if accion == "nueva":
                safe_execute("INSERT INTO tematicas (nombre) VALUES (%s)", (nombre,))
            else:
                _, tema_id = accion
                safe_execute("UPDATE tematicas SET nombre=%s WHERE id=%s", (nombre, tema_id))
            conn.commit()
            msg.reply_text("✅ Temática guardada.")
        except Exception as e:
            conn.rollback()
            log_error(e)
            msg.reply_text("❌ No se pudo guardar. El nombre puede estar duplicado.")
        return

    if msg.text and "accion_canal" in context.user_data:
        accion = context.user_data.pop("accion_canal")
        try:
            nombre, canal_id_txt = [parte.strip() for parte in msg.text.split("|", 1)]
            canal_id = int(canal_id_txt)
            if accion[0] == "nuevo":
                safe_execute("INSERT INTO canales (nombre, canal_id, tematica_id) VALUES (%s,%s,%s)", (nombre, canal_id, accion[1]))
            else:
                _, anterior_id, _ = accion
                safe_execute("UPDATE canales SET nombre=%s, canal_id=%s WHERE canal_id=%s", (nombre, canal_id, anterior_id))
            conn.commit()
            msg.reply_text("✅ Canal guardado.")
        except Exception as e:
            conn.rollback()
            log_error(e)
            msg.reply_text("❌ Formato inválido, nombre/ID duplicado o error al guardar.")
        return

    if "editando_id" in context.user_data:
        if msg.text and not msg.text.startswith("/"):
            context.user_data.pop("editando_id")
            context.user_data["editando_contenido"] = msg.text_html
            msg.reply_text("📅 Selecciona la nueva fecha:")
            calendario(update, context)
        return

    if "canal" not in context.user_data:
        return

    # ÁLBUM — múltiples fotos enviadas juntas
    if msg.photo and msg.media_group_id:
        if user_id not in ALBUMS:
            ALBUMS[user_id] = {"fotos": [], "caption": ""}
        ALBUMS[user_id]["fotos"].append(msg.photo[-1].file_id)
        if msg.caption_html:
            ALBUMS[user_id]["caption"] = msg.caption_html
        for job in context.job_queue.get_jobs_by_name(f"album_{user_id}"):
            job.schedule_removal()
        context.job_queue.run_once(
            procesar_album,
            when=2,
            context={"user_id": user_id, "update": update, "ctx": context},
            name=f"album_{user_id}"
        )
        return

    # FOTO SOLA
    if msg.photo and not msg.media_group_id:
        context.user_data["data"] = {
            "tipo": "foto", "contenido": msg.caption_html or "",
            "file_id": msg.photo[-1].file_id,
            "origin_chat_id": msg.chat_id, "origin_msg_id": msg.message_id
        }
        calendario(update, context)

    # VIDEO
    elif msg.video:
        context.user_data["data"] = {
            "tipo": "video", "contenido": msg.caption_html or "",
            "file_id": msg.video.file_id,
            "origin_chat_id": msg.chat_id, "origin_msg_id": msg.message_id
        }
        calendario(update, context)

    # TEXTO
    elif msg.text and not msg.text.startswith("/"):
        context.user_data["data"] = {
            "tipo": "texto", "contenido": msg.text,
            "file_id": None,
            "origin_chat_id": msg.chat_id, "origin_msg_id": msg.message_id
        }
        calendario(update, context)

# ===== COMANDOS =====
def cmd_pendientes(update, context):
    if not update.effective_user or update.effective_user.id not in ADMINS:
        return
    datos = obtener(solo_pendientes=True)
    if not datos:
        update.message.reply_text("✅ No hay mensajes pendientes.")
        return
    texto = f"⏳ *{len(datos)} pendientes:*\n\n"
    for m in datos[:10]:
        id, tipo, contenido, file_id, fecha, canal, enviado, recurrente, _, _, traducir_msg, file_ids_str, _ = m
        rec = " 🔁" if recurrente else ""
        trad = " 🌐" if traducir_msg else ""
        album = f" 📸{len(file_ids_str.split(','))}" if file_ids_str and tipo == "album" else ""
        texto += f"• ID {id} | {canal} | {fecha}{rec}{trad}{album}\n"
    update.message.reply_text(texto, parse_mode="Markdown")

def cmd_errores(update, context):
    if not update.effective_user or update.effective_user.id not in ADMINS:
        return
    safe_execute("SELECT * FROM errores ORDER BY id DESC LIMIT 10")
    errores = cursor.fetchall()
    if not errores:
        update.message.reply_text("✅ No hay errores.")
        return
    texto = "🚨 *Últimos errores:*\n\n"
    for e in errores:
        texto += f"• {e[1]}: `{str(e[2])[:80]}`\n"
    update.message.reply_text(texto, parse_mode="Markdown")

def cmd_limpiar(update, context):
    if not update.effective_user or update.effective_user.id not in ADMINS:
        return
    try:
        fecha_limite = (datetime.now(TIMEZONE) - timedelta(days=30)).strftime("%Y-%m-%d %H:%M")
        safe_execute("DELETE FROM mensajes WHERE enviado=TRUE AND fecha < %s", (fecha_limite,))
        msg = cursor.rowcount
        safe_execute("DELETE FROM errores WHERE fecha < %s", (fecha_limite,))
        err = cursor.rowcount
        conn.commit()
        update.message.reply_text(
            f"🧹 *Limpieza completada*\n\n🗑 Mensajes: {msg}\n🚨 Errores: {err}",
            parse_mode="Markdown"
        )
    except Exception as e:
        log_error(e)
        update.message.reply_text(f"❌ Error: {e}")

# ===== MAIN =====
def main():
    updater = Updater(TOKEN, use_context=True)
    dp = updater.dispatcher
    jq = updater.job_queue

    dp.add_handler(CommandHandler("start", start))
    dp.add_handler(CommandHandler("addcanal", hacer_addcanal, pass_args=True))
    dp.add_handler(CommandHandler("canales", cmd_canales))
    dp.add_handler(CommandHandler("delcanal", cmd_delcanal))
    dp.add_handler(CommandHandler("pendientes", cmd_pendientes))
    dp.add_handler(CommandHandler("errores", cmd_errores))
    dp.add_handler(CommandHandler("limpiar", cmd_limpiar))
    dp.add_handler(CallbackQueryHandler(botones))
    dp.add_handler(MessageHandler(Filters.all & ~Filters.command, recibir))

    jq.run_daily(limpiar_viejos, time=datetime.strptime("00:00", "%H:%M").time())
    jq.run_daily(resumen_semanal, time=datetime.strptime("08:00", "%H:%M").time(), days=(0,))

    recuperar(dp)
    print("🚀 Bot iniciado correctamente", flush=True)
    updater.start_polling(drop_pending_updates=True)
    updater.idle()

if __name__ == "__main__":
    main()
