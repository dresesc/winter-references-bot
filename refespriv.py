# librerías.
import os
import psycopg2
import psycopg2.extras
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, InputMediaPhoto
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
    cursor.execute("""
        INSERT INTO referencias (media_group_id, caption, user_id, username, name, status)
        VALUES (%s, %s, %s, %s, %s, 'pendiente')
        RETURNING id;
    """, (media_group_id, caption, user_id, username, name))
    referencia_id = cursor.fetchone()[0]
    conn.commit()
    cursor.close()
    conn.close()
    return referencia_id

def guardar_foto(referencia_id, file_id):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO referencias_fotos (referencia_id, file_id)
        VALUES (%s, %s)
    """, (referencia_id, file_id))
    conn.commit()
    cursor.close()
    conn.close()

def actualizar_estado(referencia_id, estado):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("UPDATE referencias SET status=%s WHERE id=%s", (estado, referencia_id))
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
    cursor = conn.cursor()
    cursor.execute("SELECT file_id FROM referencias_fotos WHERE referencia_id=%s", (referencia_id,))
    fotos = [row[0] for row in cursor.fetchall()]
    cursor.close()
    conn.close()
    return fotos

def total_refes_usuario(user_id):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT COUNT(f.id)
        FROM referencias r
        JOIN referencias_fotos f ON r.id = f.referencia_id
        WHERE r.user_id=%s AND r.status='aprobado'
    """, (user_id,))
    total = cursor.fetchone()[0]
    cursor.close()
    conn.close()
    return total

def ranking_refes():
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT r.username, COUNT(f.id) as total
        FROM referencias r
        JOIN referencias_fotos f ON r.id = f.referencia_id
        WHERE r.status='aprobado'
        GROUP BY r.username
        ORDER BY total DESC
    """)
    ranking = cursor.fetchall()
    cursor.close()
    conn.close()
    return ranking

# =====================
# HANDLERS
# =====================
async def winter_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message.reply_to_message:
        await update.message.reply_text("responde a tus referencias con /winter.")
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
        user.full_name
    )

    if context.bot_data.get(media_group_id):
        for file_id in context.bot_data[media_group_id]:
            guardar_foto(referencia_id, file_id)
    elif replied.photo:
        guardar_foto(referencia_id, replied.photo[-1].file_id)

    await update.message.reply_text("estoy procesando tus imágenes...")
    await update.message.reply_text("¡gracias por tus referencias! han sido enviadas a revisión.")

    fotos = obtener_fotos(referencia_id)
    media = [InputMediaPhoto(photo) for photo in fotos]
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("✔️ aprobar", callback_data=f"aprobar:{referencia_id}"),
         InlineKeyboardButton("✖️ rechazar", callback_data=f"rechazar:{referencia_id}")]
    ])
    await context.bot.send_media_group(REVIEWER_ID, media)
    await context.bot.send_message(REVIEWER_ID, f"referencia enviada por @{user.username or user.id}",
                                   reply_markup=keyboard)

async def handle_album(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    if msg.photo and msg.media_group_id:
        file_id = msg.photo[-1].file_id
        if msg.media_group_id not in context.bot_data:
            context.bot_data[msg.media_group_id] = []
        context.bot_data[msg.media_group_id].append(file_id)

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    action, referencia_id = query.data.split(":")
    referencia_id = int(referencia_id)

    ref = obtener_referencia(referencia_id)
    fotos = obtener_fotos(referencia_id)

    if action == "aprobar":
        actualizar_estado(referencia_id, "aprobado")
        total = total_refes_usuario(ref["user_id"])
        hora = datetime.now().strftime("%H:%M:%S")

        caption = ref['caption'] if ref['caption'] and ref['caption'].strip() else "sin mensaje."

        texto = f"""
𝗪𝗜𝗡𝗧𝗘𝗥 𝗥𝗘𝗙𝗘𝗥𝗘𝗡𝗖𝗘𝗦 
‿‿‿‿‿‿‿‿‿‿‿‿‿‿‿ 

꒰ 𝗠𝗘𝗦𝗦𝗔𝗚𝗘 ꒱ : {caption}
꒰ 𝗡𝗔𝗠𝗘 ꒱ : {ref['name']}
꒰ 𝗨𝗦𝗘𝗥 ꒱ : @{ref['username']}
꒰ 𝗜𝗗 ꒱ : {ref['user_id']}
‿‿‿‿‿‿‿‿‿‿‿‿‿‿‿

꒰ 𝗧𝗢𝗧𝗔𝗟 𝗥𝗘𝗙𝗘𝗦 ꒱ : {total}  
꒰ 𝗧𝗜𝗠𝗘 𝗦𝗘𝗡𝗧 ꒱ : {hora}
"""
    fotos = obtener_fotos(referencia_id)

    # Enviar cada foto por separado, todas con la caption completa
    for photo in fotos:
        await context.bot.send_photo(CHANNEL_ID, photo, caption=texto)

    await query.edit_message_text(f"referencia aprobada y publicada.")

    elif action == "rechazar":
        actualizar_estado(referencia_id, "rechazado")
        await query.edit_message_text(f"referencia rechazada.")

async def refes_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.message.from_user
    total = total_refes_usuario(user.id)
    await update.message.reply_text(
        f"🪽 . . . holi {user.full_name}, actualmente llevas un total de {total} referencias aprobadas en 𝘄𝗶𝗻𝘁𝗲𝗿 𝗽𝗿𝗶𝘃."
    )

async def conteo_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    ranking = ranking_refes()
    if not ranking:
        await update.message.reply_text("No hay referencias aprobadas aún.")
        return

    texto = "𝗧𝗢𝗧𝗔𝗟 𝗥𝗘𝗙𝗘𝗦\n"
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
        webhook_url=f"https://{os.getenv('RENDER_EXTERNAL_HOSTNAME')}/{TOKEN}"
    )

if __name__ == "__main__":
    main()
