# librerías.
import os
import psycopg2
import psycopg2.extras
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, MessageHandler,
    CallbackQueryHandler, ContextTypes, filters
)

# =====================
# CONFIG
# =====================
TOKEN = os.getenv("TOKEN")  # token del bot desde variables de entorno
CHANNEL_ID = os.getenv("CHANNEL_ID")
REVIEWER_ID = int(os.getenv("REVIEWER_ID", "0"))

DB_CONFIG = {
    'host': os.getenv("DB_HOST"),
    'dbname': os.getenv("DB_NAME"),
    'user': os.getenv("DB_USER"),
    'password': os.getenv("DB_PASSWORD"),
    'port': os.getenv("DB_PORT", "5432")
}

# =====================
# DB HELPERS
# =====================

def get_db_connection():
    return psycopg2.connect(**DB_CONFIG)


def guardar_referencia(media_group_id, caption, user_id, username, name):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        """
        INSERT INTO referencias (media_group_id, caption, user_id, username, name, status)
        VALUES (%s, %s, %s, %s, %s, 'pendiente')
        RETURNING id;
        """,
        (media_group_id, caption, user_id, username, name),
    )
    referencia_id = cursor.fetchone()[0]
    conn.commit()
    cursor.close()
    conn.close()
    return referencia_id


def guardar_foto(referencia_id, file_id, caption=""):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        """
        INSERT INTO referencias_fotos (referencia_id, file_id, caption, status)
        VALUES (%s, %s, %s, 'pendiente')
        RETURNING id;
        """,
        (referencia_id, file_id, caption),
    )
    foto_id = cursor.fetchone()[0]
    conn.commit()
    cursor.close()
    conn.close()
    return foto_id


def actualizar_estado_referencia(referencia_id, estado):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("UPDATE referencias SET status=%s WHERE id=%s", (estado, referencia_id))
    conn.commit()
    cursor.close()
    conn.close()


def actualizar_estado_foto(foto_id, estado):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("UPDATE referencias_fotos SET status=%s WHERE id=%s", (estado, foto_id))
    conn.commit()
    cursor.close()
    conn.close()


def obtener_referencia(referencia_id):
    conn = get_db_connection()
    cursor = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cursor.execute("SELECT * FROM referencias WHERE id=%s", (referencia_id,))
    ref = cursor.fetchone()
    cursor.close()
    conn.close()
    return ref


def obtener_fotos(referencia_id):
    conn = get_db_connection()
    cursor = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cursor.execute(
        "SELECT id, file_id, caption, status FROM referencias_fotos WHERE referencia_id=%s ORDER BY id ASC",
        (referencia_id,),
    )
    fotos = cursor.fetchall()
    cursor.close()
    conn.close()
    return fotos


def obtener_foto(foto_id):
    conn = get_db_connection()
    cursor = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cursor.execute("SELECT referencia_id, file_id, caption, status FROM referencias_fotos WHERE id=%s", (foto_id,))
    row = cursor.fetchone()
    cursor.close()
    conn.close()
    return row


def total_refes_usuario(user_id):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT COUNT(*)
        FROM referencias r
        JOIN referencias_fotos f ON r.id = f.referencia_id
        WHERE r.user_id = %s AND f.status = 'aprobado'
        """,
        (user_id,),
    )
    total = cursor.fetchone()[0]
    cursor.close()
    conn.close()
    return total


def ranking_refes():
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT r.username, COUNT(f.id) as total
        FROM referencias r
        JOIN referencias_fotos f ON r.id = f.referencia_id
        WHERE f.status = 'aprobado'
        GROUP BY r.username
        ORDER BY total DESC
        """
    )
    ranking = cursor.fetchall()
    cursor.close()
    conn.close()
    return ranking


def actualizar_status_global_de_referencia_si_corresponde(referencia_id):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT COUNT(*) FROM referencias_fotos WHERE referencia_id=%s AND status='pendiente'",
        (referencia_id,),
    )
    pendientes = cursor.fetchone()[0]
    cursor.execute(
        "SELECT COUNT(*) FROM referencias_fotos WHERE referencia_id=%s AND status='aprobado'",
        (referencia_id,),
    )
    aprobadas = cursor.fetchone()[0]
    cursor.execute(
        "SELECT COUNT(*) FROM referencias_fotos WHERE referencia_id=%s AND status='rechazado'",
        (referencia_id,),
    )
    rechazadas = cursor.fetchone()[0]

    if pendientes == 0:
        if aprobadas > 0 and rechazadas == 0:
            nuevo = 'aprobado'
        elif aprobadas == 0 and rechazadas > 0:
            nuevo = 'rechazado'
        else:
            nuevo = 'mixto'
    else:
        nuevo = 'pendiente'

    cursor.execute("UPDATE referencias SET status=%s WHERE id=%s", (nuevo, referencia_id))
    conn.commit()
    cursor.close()
    conn.close()


# =====================
# HANDLERS
# =====================
async def winter_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message.reply_to_message:
        await update.message.reply_text("responde a tus referencias con /winter ❤︎")
        return

    replied = update.message.reply_to_message
    media_group_id = replied.media_group_id or str(replied.message_id)
    user = update.message.from_user
    caption = replied.caption or ""

    referencia_id = guardar_referencia(
        media_group_id,
        caption,
        user.id,
        user.username or "sin_username",
        user.full_name,
    )

    if context.bot_data.get(media_group_id):
        for file_id, foto_caption in context.bot_data[media_group_id]:
            guardar_foto(referencia_id, file_id, foto_caption or caption)
    elif replied.photo:
        guardar_foto(referencia_id, replied.photo[-1].file_id, caption)

    await update.message.reply_text("¡gracias por tus referencias! han sido enviadas a revisión。。。 ♪")

    fotos = obtener_fotos(referencia_id)

    for foto in fotos:
        foto_id, file_id, foto_caption, _status = foto["id"], foto["file_id"], foto["caption"], foto["status"]
        keyboard = InlineKeyboardMarkup(
            [[
                InlineKeyboardButton("✔️ aprobar", callback_data=f"aprobar:{referencia_id}:{foto_id}"),
                InlineKeyboardButton("✖️ rechazar", callback_data=f"rechazar:{referencia_id}:{foto_id}"),
            ]]
        )
        await context.bot.send_photo(
            REVIEWER_ID,
            file_id,
            caption=f"referencia enviada por @{user.username or user.id}\n\n{foto_caption or caption or 'sin mensaje.'}",
            reply_markup=keyboard,
        )


async def handle_album(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    if msg.photo and msg.media_group_id:
        file_id = msg.photo[-1].file_id
        caption = msg.caption or ""

        # inicializamos lista del álbum si no existe
        if msg.media_group_id not in context.bot_data:
            context.bot_data[msg.media_group_id] = []

        context.bot_data[msg.media_group_id].append((file_id, caption))

        # si este mensaje tiene caption, actualizar todos los anteriores en el álbum
        if caption:
            fotos = context.bot_data[msg.media_group_id]
            context.bot_data[msg.media_group_id] = [
                (fid, cap or caption) for fid, cap in fotos
            ]



async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    try:
        action, referencia_id, foto_id = query.data.split(":")
    except ValueError:
        await query.edit_message_caption(caption="formato de callback inválido.")
        return

    referencia_id, foto_id = int(referencia_id), int(foto_id)

    ref = obtener_referencia(referencia_id)
    foto = obtener_foto(foto_id)

    if not foto:
        await query.edit_message_caption(caption="no se encontró la imagen.")
        return

    file_id = foto["file_id"]
    estado_actual = foto["status"]

    if action == "aprobar":
        if estado_actual == 'aprobado':
            total = total_refes_usuario(ref["user_id"])
            await query.edit_message_caption(caption=f"ya estaba aprobada. total del usuario: {total}")
            return

        actualizar_estado_foto(foto_id, "aprobado")
        actualizar_status_global_de_referencia_si_corresponde(referencia_id)

        total = total_refes_usuario(ref["user_id"])
        hora = datetime.now().strftime("%H:%M:%S")
        caption_channel = foto["caption"] or ref['caption'] or "sin mensaje."

        texto = f"""
𝓦inter 𝓡eferences 🪽⊹
‿‿‿‿‿‿‿‿‿‿‿‿‿‿‿ 

♪꒰ message : {caption_channel}
♪꒰ name : {ref['name']}
♪꒰ user : @{ref['username']}
♪꒰ id : {ref['user_id']}
‿‿‿‿‿‿‿‿‿‿‿‿‿‿‿

♪꒰ total refes : {total}  
♪꒰ time sent : {hora}
"""

        await context.bot.send_photo(CHANNEL_ID, file_id, caption=texto)
        await query.edit_message_caption(caption="referencia aprobada y publicada.")

    elif action == "rechazar":
        if estado_actual == 'rechazado':
            await query.edit_message_caption(caption="ya estaba rechazada.")
            return

        actualizar_estado_foto(foto_id, "rechazado")
        actualizar_status_global_de_referencia_si_corresponde(referencia_id)
        await query.edit_message_caption(caption="referencia rechazada.")

    else:
        await query.edit_message_caption(caption="acción no reconocida.")


async def refes_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.message.from_user
    total = total_refes_usuario(user.id)
    await update.message.reply_text(
        f"🪽 。。。holi {user.full_name}, actualmente llevas un total de {total} referencias aprobadas en 𝔀inter 𝓹riv."
    )


async def conteo_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id

    # solo el revisor puede usar este comando
    if user_id != REVIEWER_ID:
        await update.message.reply_text("no tienes permiso para usar este comando.")
        return

    ranking = ranking_refes()
    if not ranking:
        await update.message.reply_text("no hay referencias registradas aún.")
        return

    texto = "𝓣otal 𝓡efes\n"
    for user, total in ranking:
        texto += f"@{user} : {total} referencias\n"
    await update.message.reply_text(texto)



async def reset(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id

    if user_id != REVIEWER_ID:
        await update.message.reply_text("no tienes permiso para usar este comando.")
        return

    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("TRUNCATE TABLE referencias_fotos RESTART IDENTITY CASCADE;")
        cursor.execute("TRUNCATE TABLE referencias RESTART IDENTITY CASCADE;")
        conn.commit()
        cursor.close()
        conn.close()

        await update.message.reply_text(
            "toda la base de datos ha sido reseteada.\n"
            "las referencias se han reiniciado."
        )
    except Exception as e:
        await update.message.reply_text(f"error al resetear la base de datos: {e}")


# =====================
# MAIN
# =====================

def main():
    app = Application.builder().token(TOKEN).build()

    app.add_handler(CommandHandler("winter", winter_command))
    app.add_handler(CommandHandler("refes", refes_command))
    app.add_handler(CommandHandler("conteo", conteo_command))
    app.add_handler(MessageHandler(filters.PHOTO, handle_album))
    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_handler(CommandHandler("reset", reset))

    print("bot iniciado con webhooks...")

    PORT = int(os.getenv("PORT", "8443"))
    app.run_webhook(
        listen="0.0.0.0",
        port=PORT,
        url_path=TOKEN,
        webhook_url=f"https://{os.getenv('RENDER_EXTERNAL_HOSTNAME')}/{TOKEN}",
    )


if __name__ == "__main__":
    main()
# =====================