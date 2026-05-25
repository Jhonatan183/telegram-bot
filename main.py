import os
import time
import psycopg2
from psycopg2 import OperationalError
from datetime import datetime, timedelta
import pytz
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Updater, CommandHandler, CallbackQueryHandler, MessageHandler, Filters

# ===== CONFIG =====
TOKEN = ("8192711687:AAEMnhydzn-R0QICph4Jy66Iv8etaTO3CbA")
DB_URL = ("postgresql://postgres:sRkjAQLlMcBIsShoIMpCSsPTklMOsvoj@centerbeam.proxy.rlwy.net:45270/railway")

ADMINS = [5869414542]
TIMEZONE = pytz.timezone("America/Bogota")

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
        recurrente TEXT DEFAULT NULL
    )
""")
cursor.execute("ALTER TABLE mensajes ADD COLUMN IF NOT EXISTS recurrente TEXT DEFAULT NULL")
cursor.execute("ALTER TABLE mensajes ADD COLUMN IF NOT EXISTS enviado BOOLEAN DEFAULT FALSE")

cursor.execute("""
    CREATE TABLE IF NOT EXISTS canales (
        id SERIAL PRIMARY KEY,
        nombre TEXT UNIQUE,
        canal_id BIGINT UNIQUE
    )
""")
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

# ===== FUNCIONES MENSAJES =====
def guardar(tipo, contenido, file_id, fecha, canal, recurrente=None):
    safe_execute(
        "INSERT INTO mensajes (tipo, contenido, file_id, fecha, canal, recurrente) VALUES (%s,%s,%s,%s,%s,%s) RETURNING id",
        (tipo, contenido, file_id, fecha, canal, recurrente)
    )
    id_msg = cursor.fetchone()[0]
    conn.commit()
    return id_msg

def obtener(solo_pendientes=False, solo_enviados=False, solo_recurrentes=False, canal_filtro=None):
    condiciones = []
    params = []
    if solo_pendientes:
        condiciones.append("enviado=FALSE")
    if solo_enviados:
        condiciones.append("enviado=TRUE")
    if solo_recurrentes:
        condiciones.append("recurrente IS NOT NULL")
    if canal_filtro:
        condiciones.append("canal=%s")
        params.append(canal_filtro)
    where = f"WHERE {' AND '.join(condiciones)}" if condiciones else ""
    safe_execute(f"SELECT * FROM mensajes {where} ORDER BY id DESC", params)
    return cursor.fetchall()

def eliminar(id):
    safe_execute("DELETE FROM mensajes WHERE id=%s", (id,))
    conn.commit()

def actualizar_mensaje(id, contenido, fecha):
    safe_execute(
        "UPDATE mensajes SET contenido=%s, fecha=%s WHERE id=%s",
        (contenido, fecha, id)
    )
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

        top_txt = ""
        for canal, count in top_canales:
            top_txt += f"  • {canal}: {count} mensajes\n"

        texto = (
            f"📊 *Resumen Semanal — Bot PRO*\n"
            f"_{datetime.now(TIMEZONE).strftime('%d/%m/%Y')}_\n\n"
            f"📨 Total mensajes: {total}\n"
            f"✅ Enviados: {enviados}\n"
            f"⏳ Pendientes: {pendientes}\n"
            f"🔁 Recurrentes activos: {recurrentes}\n"
            f"📢 Canales registrados: {n_canales}\n"
            f"🚨 Errores registrados: {n_errores}\n\n"
            f"🏆 *Top canales:*\n{top_txt if top_txt else '  Sin datos aún'}"
        )
        bot = context.bot
        for admin_id in ADMINS:
            try:
                bot.send_message(admin_id, texto, parse_mode="Markdown")
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
    safe_execute("SELECT * FROM mensajes WHERE enviado=FALSE")
    for m in cursor.fetchall():
        id, tipo, contenido, file_id, fecha, canal, enviado, recurrente = m
        try:
            fecha_dt = TIMEZONE.localize(datetime.strptime(fecha, "%Y-%m-%d %H:%M"))
        except Exception:
            continue
        delay = (fecha_dt - datetime.now(TIMEZONE)).total_seconds()
        if delay <= 0:
            continue
        dispatcher.job_queue.run_once(
            enviar,
            when=delay,
            context={
                "id": id, "tipo": tipo, "contenido": contenido,
                "file_id": file_id, "canal": canal, "recurrente": recurrente,
                "fecha_str": fecha
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
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(kb)
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
    q.message.reply_text("📋 *Panel de mensajes*\n\n¿Qué quieres ver?", parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(kb))

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
        q.message.reply_text("📭 No hay mensajes en esta categoría.", reply_markup=InlineKeyboardMarkup(kb))
        return

    filtro_txt = {"todos": "Todos", "pendientes": "⏳ Pendientes", "enviados": "✅ Enviados", "recurrentes": "🔁 Recurrentes"}
    q.message.reply_text(f"*{filtro_txt.get(filtro, 'Todos')}* — Página {page+1} | Total: {total}", parse_mode="Markdown")

    for m in pagina:
        id, tipo, contenido, file_id, fecha, canal, enviado, recurrente = m
        estado = "✅ Enviado" if enviado else "⏳ Pendiente"
        rec = f" | 🔁 {recurrente}" if recurrente else ""
        texto = (
            f"*ID:* {id}\n"
            f"*Canal:* {canal}\n"
            f"*Fecha:* {fecha}\n"
            f"*Estado:* {estado}{rec}\n"
            f"*Tipo:* {tipo}"
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
    safe_execute("SELECT * FROM mensajes WHERE id=%s", (id_msg,))
    m = cursor.fetchone()
    if not m:
        q.message.reply_text("❌ Mensaje no encontrado.")
        return
    id, tipo, contenido, file_id, fecha, canal, enviado, recurrente = m
    estado = "✅ Enviado" if enviado else "⏳ Pendiente"
    rec = recurrente if recurrente else "No"
    file_txt = f"\n*File ID:* <code>{file_id}</code>" if file_id else ""
    texto = (
        f"👁 <b>Detalle del mensaje #{id}</b>\n\n"
        f"<b>Canal:</b> {canal}\n"
        f"<b>Fecha:</b> {fecha}\n"
        f"<b>Estado:</b> {estado}\n"
        f"<b>Tipo:</b> {tipo}\n"
        f"<b>Recurrente:</b> {rec}{file_txt}\n\n"
        f"<b>Contenido completo:</b>\n{contenido or '<i>(archivo multimedia)</i>'}"
    )
    kb = [[InlineKeyboardButton("🔙 Volver", callback_data=f"panel_filter_{context.user_data.get('panel_filtro', 'todos')}")]]
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
    canales = get_canales()
    texto = "📢 *Canales registrados:*\n\n"
    if canales:
        for nombre, cid in canales.items():
            texto += f"• *{nombre}*: `{cid}`\n"
    else:
        texto += "_No hay canales registrados_\n"
    kb = [
        [InlineKeyboardButton("➕ Agregar canal", callback_data="add_canal")],
        [InlineKeyboardButton("🗑 Eliminar canal", callback_data="del_canal_menu")],
        [InlineKeyboardButton("🔙 Menú principal", callback_data="main_menu")]
    ]
    q.message.reply_text(texto, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(kb))

def hacer_addcanal(update, context):
    if not update.effective_user or update.effective_user.id not in ADMINS:
        return
    args = context.args
    if len(args) < 2:
        update.message.reply_text(
            "❌ Uso correcto:\n`/addcanal NombreCanal -100xxxxxxxxxx`\n\nEjemplo:\n`/addcanal MiCanal -1001234567890`",
            parse_mode="Markdown"
        )
        return
    nombre = args[0]
    try:
        canal_id = int(args[1])
    except ValueError:
        update.message.reply_text("❌ El ID debe ser un número. Ejemplo: `-1001234567890`", parse_mode="Markdown")
        return
    try:
        safe_execute("INSERT INTO canales (nombre, canal_id) VALUES (%s, %s)", (nombre, canal_id))
        conn.commit()
        update.message.reply_text(f"✅ Canal *{nombre}* agregado correctamente.", parse_mode="Markdown")
    except Exception:
        conn.rollback()
        update.message.reply_text("❌ Error: ese nombre o ID ya existe.", parse_mode="Markdown")

def cmd_canales(update, context):
    if not update.effective_user or update.effective_user.id not in ADMINS:
        return
    canales = get_canales()
    if not canales:
        update.message.reply_text("📭 No hay canales registrados.")
        return
    texto = "📢 *Canales registrados:*\n\n"
    for nombre, cid in canales.items():
        texto += f"• *{nombre}*: `{cid}`\n"
    update.message.reply_text(texto, parse_mode="Markdown")

def cmd_delcanal(update, context):
    if not update.effective_user or update.effective_user.id not in ADMINS:
        return
    canales = get_canales()
    if not canales:
        update.message.reply_text("📭 No hay canales para eliminar.")
        return
    botones = [[InlineKeyboardButton(f"🗑 {n}", callback_data=f"delcanal_{n}")] for n in canales.keys()]
    update.message.reply_text("Selecciona el canal a eliminar:", reply_markup=InlineKeyboardMarkup(botones))

# ===== ENVÍO =====
def enviar(context):
    data = context.job.context
    bot = context.bot
    canales = get_canales()
    try:
        if data["canal"] == "ALL":
            for canal_id in canales.values():
                enviar_tipo(bot, canal_id, data)
        else:
            if data["canal"] in canales:
                enviar_tipo(bot, canales[data["canal"]], data)
        safe_execute("UPDATE mensajes SET enviado=TRUE WHERE id=%s", (data["id"],))
        conn.commit()

        if data.get("recurrente"):
            recurrente = data["recurrente"]
            fecha_actual = datetime.strptime(data["fecha_str"], "%Y-%m-%d %H:%M")
            if recurrente == "diario":
                nueva_fecha = fecha_actual + timedelta(days=1)
            elif recurrente == "semanal":
                nueva_fecha = fecha_actual + timedelta(weeks=1)
            else:
                return
            nueva_fecha_str = nueva_fecha.strftime("%Y-%m-%d %H:%M")
            nuevo_id = guardar(data["tipo"], data["contenido"], data["file_id"], nueva_fecha_str, data["canal"], recurrente)
            nueva_fecha_dt = TIMEZONE.localize(nueva_fecha)
            delay = (nueva_fecha_dt - datetime.now(TIMEZONE)).total_seconds()
            if delay > 0:
                context.job_queue.run_once(
                    enviar,
                    when=delay,
                    context={**data, "id": nuevo_id, "fecha_str": nueva_fecha_str}
                )
    except Exception as e:
        log_error(e)
        print(f"❌ Error en envío: {e}", flush=True)

def enviar_tipo(bot, canal_id, data):
    try:
        if data["tipo"] == "texto":
            bot.send_message(canal_id, data["contenido"], parse_mode="HTML")
        elif data["tipo"] == "foto":
            bot.send_photo(canal_id, data["file_id"], caption=data["contenido"], parse_mode="HTML")
        elif data["tipo"] == "video":
            bot.send_video(canal_id, data["file_id"], caption=data["contenido"], parse_mode="HTML")
    except Exception as e:
        log_error(e)
        print(f"❌ Error enviando a {canal_id}: {e}", flush=True)

# ===== VISTA PREVIA =====
def vista_previa(update, context):
    q = update.callback_query
    data_msg = context.user_data.get("data")
    canal = context.user_data.get("canal", "?")
    fecha = context.user_data.get("fecha_final", "?")
    recurrente = context.user_data.get("recurrente", None)
    rec_txt = f"\n🔁 Recurrencia: {recurrente}" if recurrente else ""
    texto = (
        f"👁 *Vista previa*\n\n"
        f"📢 Canal: {canal}\n"
        f"📅 Fecha: {fecha}{rec_txt}\n"
        f"📝 Tipo: {data_msg['tipo']}\n\n"
        f"*Contenido:*\n{data_msg['contenido'] or '_(archivo multimedia)_'}"
    )
    kb = [
        [InlineKeyboardButton("✅ Confirmar y programar", callback_data="confirmar_envio")],
        [InlineKeyboardButton("❌ Cancelar", callback_data="main_menu")]
    ]
    q.message.reply_text(texto, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(kb))

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
        q.message.reply_text("🔥 *BOT PRO* — Panel de control", parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(kb))

    elif data == "prog":
        canales = get_canales()
        kb = [[InlineKeyboardButton(c, callback_data=f"canal_{c}")] for c in canales.keys()]
        kb.append([InlineKeyboardButton("🔥 TODOS LOS CANALES", callback_data="canal_ALL")])
        kb.append([InlineKeyboardButton("🔙 Menú principal", callback_data="main_menu")])
        q.message.reply_text("📢 Selecciona el canal:", reply_markup=InlineKeyboardMarkup(kb))

    elif data.startswith("canal_"):
        context.user_data["canal"] = data.replace("canal_", "", 1)
        q.message.reply_text("📨 Envíame el contenido que quieres programar\n_(texto, foto o video)_", parse_mode="Markdown")

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
            q.message.reply_text("❌ Error: faltan datos. Empieza de nuevo con /start")
            return
        fecha_final = f"{fecha} {hora}:{minuto}"
        context.user_data["fecha_final"] = fecha_final
        kb = [
            [InlineKeyboardButton("📅 Solo una vez", callback_data="rec_none")],
            [InlineKeyboardButton("🔁 Diario", callback_data="rec_diario")],
            [InlineKeyboardButton("📆 Semanal", callback_data="rec_semanal")]
        ]
        q.message.reply_text("🔁 ¿Con qué frecuencia?", reply_markup=InlineKeyboardMarkup(kb))

    elif data.startswith("rec_"):
        recurrente = None if data == "rec_none" else data.replace("rec_", "")
        context.user_data["recurrente"] = recurrente
        vista_previa(update, context)

    elif data == "confirmar_envio":
        fecha_final = context.user_data.get("fecha_final")
        canal = context.user_data.get("canal")
        data_msg = context.user_data.get("data")
        recurrente = context.user_data.get("recurrente")
        try:
            fecha_dt = TIMEZONE.localize(datetime.strptime(fecha_final, "%Y-%m-%d %H:%M"))
        except Exception:
            q.message.reply_text("❌ Error al procesar la fecha.")
            return
        delay = (fecha_dt - datetime.now(TIMEZONE)).total_seconds()
        if delay <= 0:
            q.message.reply_text("❌ La fecha ya pasó. Selecciona una fecha futura.")
            return
        id_msg = guardar(data_msg["tipo"], data_msg["contenido"], data_msg["file_id"], fecha_final, canal, recurrente)
        context.job_queue.run_once(
            enviar,
            when=delay,
            context={**data_msg, "canal": canal, "id": id_msg, "recurrente": recurrente, "fecha_str": fecha_final}
        )
        rec_txt = f" | 🔁 {recurrente}" if recurrente else ""
        q.message.reply_text(f"✅ *Programado para {fecha_final}*{rec_txt}", parse_mode="Markdown")
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
        filtro = context.user_data.get("panel_filtro", "todos")
        panel(update, context, filtro=filtro)

    elif data.startswith("detalle_"):
        id_msg = int(data.split("_")[1])
        ver_detalle(update, context, id_msg)

    elif data.startswith("confirm_del_"):
        id_msg = int(data.split("_")[2])
        kb = [[
            InlineKeyboardButton("✅ Sí, eliminar", callback_data=f"eliminar_{id_msg}"),
            InlineKeyboardButton("❌ Cancelar", callback_data="panel_menu")
        ]]
        q.message.reply_text("⚠️ ¿Seguro que quieres eliminar este mensaje?", reply_markup=InlineKeyboardMarkup(kb))

    elif data.startswith("eliminar_"):
        eliminar(int(data.split("_")[1]))
        q.message.reply_text("🗑 Mensaje eliminado correctamente.")

    elif data.startswith("edit_"):
        id_msg = int(data.split("_")[1])
        context.user_data["editando_id"] = id_msg
        q.message.reply_text("✏️ Envíame el nuevo texto para este mensaje:")

    elif data == "stats":
        q.message.reply_text(estadisticas(), parse_mode="Markdown")
        ruta = grafico()
        if ruta:
            q.message.reply_photo(open(ruta, "rb"))

    elif data == "menu_canales":
        menu_canales(update, context)

    elif data == "add_canal":
        q.message.reply_text(
            "➕ Para agregar un canal usa:\n\n`/addcanal NombreCanal -100xxxxxxxxxx`\n\nEjemplo:\n`/addcanal MiCanal -1001234567890`",
            parse_mode="Markdown"
        )

    elif data == "del_canal_menu":
        canales = get_canales()
        if not canales:
            q.message.reply_text("📭 No hay canales para eliminar.")
            return
        botones_list = [[InlineKeyboardButton(f"🗑 {n}", callback_data=f"delcanal_{n}")] for n in canales.keys()]
        botones_list.append([InlineKeyboardButton("🔙 Volver", callback_data="menu_canales")])
        q.message.reply_text("Selecciona el canal a eliminar:", reply_markup=InlineKeyboardMarkup(botones_list))

    elif data.startswith("delcanal_"):
        nombre = data.replace("delcanal_", "", 1)
        kb = [[
            InlineKeyboardButton("✅ Sí, eliminar", callback_data=f"confirmar_delcanal_{nombre}"),
            InlineKeyboardButton("❌ Cancelar", callback_data="menu_canales")
        ]]
        q.message.reply_text(f"⚠️ ¿Eliminar el canal *{nombre}*?", parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(kb))

    elif data.startswith("confirmar_delcanal_"):
        nombre = data.replace("confirmar_delcanal_", "", 1)
        safe_execute("DELETE FROM canales WHERE nombre=%s", (nombre,))
        conn.commit()
        q.message.reply_text(f"🗑 Canal *{nombre}* eliminado.", parse_mode="Markdown")

# ===== RECIBIR MENSAJES =====
def recibir(update, context):
    if not update.effective_user:
        return
    if update.effective_user.id not in ADMINS:
        return
    if not update.message:
        return
    msg = update.message

    if "editando_id" in context.user_data:
        if msg.text and not msg.text.startswith("/"):
            id_msg = context.user_data.pop("editando_id")
            context.user_data["editando_id_confirmado"] = id_msg
            context.user_data["editando_contenido"] = msg.text_html
            msg.reply_text("📅 Ahora selecciona la nueva fecha:")
            calendario(update, context)
        return

    if "canal" not in context.user_data:
        return

    if msg.text and not msg.text.startswith("/"):
        context.user_data["data"] = {
            "tipo": "texto",
            "contenido": msg.text_html,
            "file_id": None
        }
        calendario(update, context)
    elif msg.photo:
        context.user_data["data"] = {
            "tipo": "foto",
            "contenido": msg.caption_html or "",
            "file_id": msg.photo[-1].file_id
        }
        calendario(update, context)
    elif msg.video:
        context.user_data["data"] = {
            "tipo": "video",
            "contenido": msg.caption_html or "",
            "file_id": msg.video.file_id
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
    texto = f"⏳ *{len(datos)} mensajes pendientes:*\n\n"
    for m in datos[:10]:
        id, tipo, contenido, file_id, fecha, canal, enviado, recurrente = m
        rec = " 🔁" if recurrente else ""
        texto += f"• ID {id} | {canal} | {fecha}{rec}\n"
    update.message.reply_text(texto, parse_mode="Markdown")

def cmd_errores(update, context):
    if not update.effective_user or update.effective_user.id not in ADMINS:
        return
    safe_execute("SELECT * FROM errores ORDER BY id DESC LIMIT 10")
    errores = cursor.fetchall()
    if not errores:
        update.message.reply_text("✅ No hay errores registrados.")
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
        eliminados_msg = cursor.rowcount
        safe_execute("DELETE FROM errores WHERE fecha < %s", (fecha_limite,))
        eliminados_err = cursor.rowcount
        conn.commit()
        update.message.reply_text(
            f"🧹 *Limpieza completada*\n\n"
            f"🗑 Mensajes eliminados: {eliminados_msg}\n"
            f"🚨 Errores eliminados: {eliminados_err}",
            parse_mode="Markdown"
        )
    except Exception as e:
        log_error(e)
        update.message.reply_text(f"❌ Error en limpieza: {e}")

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
    jq.run_daily(
        resumen_semanal,
        time=datetime.strptime("08:00", "%H:%M").time(),
        days=(0,)
    )

    recuperar(dp)
    print("🚀 Bot iniciado correctamente", flush=True)
    updater.start_polling(drop_pending_updates=True)
    updater.idle()

if __name__ == "__main__":
    main()
