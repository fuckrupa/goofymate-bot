import logging
import random
import psycopg2
import os
from datetime import datetime, timedelta
import pytz

from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton, User
from telegram.constants import ChatAction, ChatType, ParseMode
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
    Application,
)

# Logging setup
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO
)
logger = logging.getLogger(__name__)

# PostgreSQL connection using environment variable
DATABASE_URL = os.environ.get("DATABASE_URL")
if not DATABASE_URL:
    raise ValueError("DATABASE_URL environment variable not set.")

conn = psycopg2.connect(DATABASE_URL)
cursor = conn.cursor()

# Create tables if not exist
cursor.execute("""
    CREATE TABLE IF NOT EXISTS aura (
        user_id BIGINT PRIMARY KEY,
        name TEXT,
        aura INTEGER DEFAULT 0
    );
""")

cursor.execute("""
    CREATE TABLE IF NOT EXISTS aura_log (
        user_id BIGINT,
        command TEXT,
        used_at TIMESTAMP,
        PRIMARY KEY (user_id, command, used_at::date)
    );
""")
conn.commit()

# Update aura score
def update_aura(user: User, amount: int):
    try:
        cursor.execute("""
            INSERT INTO aura (user_id, name, aura)
            VALUES (%s, %s, %s)
            ON CONFLICT (user_id) DO UPDATE
            SET aura = aura.aura + %s, name = EXCLUDED.name;
        """, (user.id, user.full_name, amount, amount))
        conn.commit()
    except Exception as e:
        logger.error(f"DB Error (update_aura): {e}")
        conn.rollback()

# Check if user can use the command
def can_use_command(user_id: int, command: str):
    try:
        now = datetime.utcnow()
        one_hour_ago = now - timedelta(hours=1)
        today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)

        # Has the user used this command today?
        cursor.execute("""
            SELECT used_at FROM aura_log
            WHERE user_id = %s AND command = %s AND used_at >= %s
        """, (user_id, command, today_start))
        today_used = cursor.fetchone()

        # Was the last use over an hour ago?
        cursor.execute("""
            SELECT used_at FROM aura_log
            WHERE user_id = %s AND command = %s AND used_at >= %s
            ORDER BY used_at DESC LIMIT 1
        """, (user_id, command, one_hour_ago))
        recent = cursor.fetchone()

        if today_used is None and recent is None:
            return True
        return False
    except Exception as e:
        logger.error(f"DB Error (can_use_command): {e}")
        return False

# Log command usage
def log_command_usage(user_id: int, command: str):
    try:
        cursor.execute("""
            INSERT INTO aura_log (user_id, command, used_at)
            VALUES (%s, %s, %s)
        """, (user_id, command, datetime.utcnow()))
        conn.commit()
    except Exception as e:
        logger.error(f"DB Error (log_command_usage): {e}")
        conn.rollback()

# Leaderboard
def get_aura_leaderboard():
    try:
        cursor.execute("SELECT user_id, name, aura FROM aura ORDER BY aura DESC LIMIT 20;")
        return cursor.fetchall()
    except Exception as e:
        logger.error(f"DB Error (get_aura_leaderboard): {e}")
        return []

# Send typing
async def send_typing(context: ContextTypes.DEFAULT_TYPE, chat_id):
    await context.bot.send_chat_action(chat_id=chat_id, action=ChatAction.TYPING)

# Track users
async def track_users(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if update.effective_chat.type != ChatType.PRIVATE:
        update_aura(user, 0)

# /start
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await send_typing(context, update.effective_chat.id)
    keyboard = [
        [InlineKeyboardButton("Updates", url="https://t.me/yourchannel"),
         InlineKeyboardButton("Support", url="https://t.me/yourgroup")],
        [InlineKeyboardButton("Add Me To Your Group", url="https://t.me/yourbot?startgroup=true")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(
        "Welcome to the Aura Bot! Use fun commands like /gay, /couple, /aura etc.",
        reply_markup=reply_markup
    )

# Random user
async def random_user(update: Update):
    cursor.execute("SELECT user_id, name FROM aura ORDER BY RANDOM() LIMIT 1;")
    result = cursor.fetchone()
    class Dummy:
        def __init__(self, uid, name): self.id, self.full_name = uid, name
        def mention_html(self): return f"<a href='tg://user?id={self.id}'>{self.full_name}</a>"
    return Dummy(result[0], result[1]) if result else update.effective_user

# Aura command with logic
async def aura_action(update: Update, context: ContextTypes.DEFAULT_TYPE, label, points, command_name):
    await send_typing(context, update.effective_chat.id)
    user = await random_user(update)

    if not can_use_command(user.id, command_name):
        await update.message.reply_text("You've already used this command today or within the past hour.")
        return

    update_aura(user, points)
    log_command_usage(update.effective_user.id, command_name)
    sign = "+" if points > 0 else ""
    await update.message.reply_html(f"{user.mention_html()} is {label}! {sign}{points} aura")

# Individual commands
async def gay(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await aura_action(update, context, "the Gay of the Day", -100, "gay")

async def couple(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await send_typing(context, update.effective_chat.id)
    cursor.execute("SELECT user_id, name FROM aura ORDER BY RANDOM() LIMIT 2;")
    users = cursor.fetchall()
    if len(users) < 2:
        await update.message.reply_text("Not enough members!")
        return
    user1, user2 = users
    update_aura(User(id=user1[0], full_name=user1[1]), 50)
    update_aura(User(id=user2[0], full_name=user2[1]), 50)
    await update.message.reply_html(
        f"<a href='tg://user?id={user1[0]}'>{user1[1]}</a> ❤️ <a href='tg://user?id={user2[0]}'>{user2[1]}</a> is today's couple! +50 aura each"
    )

async def simp(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await aura_action(update, context, "the Simp of the Day", 100, "simp")

async def toxic(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await aura_action(update, context, "the most toxic one today", -50, "toxic")

async def cringe(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await aura_action(update, context, "ultra cringe today", -50, "cringe")

async def respect(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await aura_action(update, context, "respected like a legend", 500, "respect")

async def sus(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await aura_action(update, context, "acting kinda sus", 100, "sus")

# /aura leaderboard
async def aura(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await send_typing(context, update.effective_chat.id)
    leaderboard = get_aura_leaderboard()
    if not leaderboard:
        await update.message.reply_text("No aura data yet.")
        return
    msg = "🌟 Aura Leaderboard 🌟\n\n"
    for i, (user_id, name, aura_val) in enumerate(leaderboard, start=1):
        msg += f"{i}. <a href='tg://user?id={user_id}'>{name}</a> — {aura_val} aura\n"
    await update.message.reply_text(msg, parse_mode=ParseMode.HTML)

# /ghost (night only)
async def ghost(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await send_typing(context, update.effective_chat.id)
    bd_tz = pytz.timezone("Asia/Dhaka")
    now = datetime.now(bd_tz)
    if 6 <= now.hour < 18:
        await update.message.reply_text(f"This command only works at night (BD time). Try again in {18 - now.hour}h.")
        return
    user = await random_user(update)
    await update.message.reply_html(f"{user.mention_html()} is tonight's ghost! No trace of life all night!")

# Main setup
TOKEN = os.environ.get("BOT_TOKEN")
if not TOKEN:
    raise ValueError("BOT_TOKEN environment variable not set.")

def main():
    app = Application.builder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("gay", gay))
    app.add_handler(CommandHandler("couple", couple))
    app.add_handler(CommandHandler("simp", simp))
    app.add_handler(CommandHandler("toxic", toxic))
    app.add_handler(CommandHandler("cringe", cringe))
    app.add_handler(CommandHandler("respect", respect))
    app.add_handler(CommandHandler("sus", sus))
    app.add_handler(CommandHandler("aura", aura))
    app.add_handler(CommandHandler("ghost", ghost))
    app.add_handler(MessageHandler(filters.ALL, track_users))

    print("Bot is running...")
    app.run_polling()

if __name__ == "__main__":
    main()