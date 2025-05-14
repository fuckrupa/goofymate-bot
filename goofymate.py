import logging
import random
import psycopg2
from datetime import datetime
import pytz
from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton, ChatAction
from telegram.constants import ChatType
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
    Application
)

# Logging setup
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO
)
logger = logging.getLogger(__name__)

# PostgreSQL connection using URL
conn = psycopg2.connect("postgresql://username:password@host:port/dbname")
cursor = conn.cursor()

# Create aura table if not exists
cursor.execute("""
    CREATE TABLE IF NOT EXISTS aura (
        user_id BIGINT PRIMARY KEY,
        username TEXT,
        aura INTEGER DEFAULT 0
    );
""")
conn.commit()

# Update aura score
def update_aura(user_id, username, amount):
    try:
        cursor.execute("""
            INSERT INTO aura (user_id, username, aura)
            VALUES (%s, %s, %s)
            ON CONFLICT (user_id) DO UPDATE
            SET aura = aura.aura + %s, username = EXCLUDED.username;
        """, (user_id, username, amount, amount))
        conn.commit()
    except Exception as e:
        logger.error(f"DB Error (update_aura): {e}")
        conn.rollback()

# Get leaderboard
def get_aura_leaderboard():
    try:
        cursor.execute("SELECT username, aura FROM aura ORDER BY aura DESC LIMIT 20;")
        return cursor.fetchall()
    except Exception as e:
        logger.error(f"DB Error (get_aura_leaderboard): {e}")
        return []

# Send typing action
async def send_typing(context: ContextTypes.DEFAULT_TYPE, chat_id):
    await context.bot.send_chat_action(chat_id=chat_id, action=ChatAction.TYPING)

# Track users for random selection
async def track_users(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if update.effective_chat.type != ChatType.PRIVATE:
        update_aura(user.id, user.username, 0)

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

# Get random user (from tracked users)
async def random_user(update: Update):
    members = await update.effective_chat.get_members_count()
    # Only from tracked users (real tracking requires full db of participants)
    cursor.execute("SELECT user_id, username FROM aura ORDER BY RANDOM() LIMIT 1;")
    result = cursor.fetchone()
    class Dummy:
        def __init__(self, uid, uname): self.id, self.username = uid, uname
        def mention_html(self): return f"<a href='tg://user?id={self.id}'>@{self.username or 'unknown'}</a>"
    return Dummy(result[0], result[1]) if result else update.effective_user

# Command: /gay
async def gay(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await send_typing(context, update.effective_chat.id)
    user = await random_user(update)
    update_aura(user.id, user.username, -100)
    await update.message.reply_html(f"{user.mention_html()} is the Gay of the Day! -100 aura")

# Command: /couple
async def couple(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await send_typing(context, update.effective_chat.id)
    cursor.execute("SELECT user_id, username FROM aura ORDER BY RANDOM() LIMIT 2;")
    users = cursor.fetchall()
    if len(users) < 2:
        await update.message.reply_text("Not enough members!")
        return
    user1, user2 = users
    update_aura(user1[0], user1[1], 50)
    update_aura(user2[0], user2[1], 50)
    await update.message.reply_html(
        f"Today's cutest couple is <a href='tg://user?id={user1[0]}'>@{user1[1]}</a> ❤️ <a href='tg://user?id={user2[0]}'>@{user2[1]}</a>! +50 aura each"
    )

# Command templates
async def aura_action(update: Update, context: ContextTypes.DEFAULT_TYPE, label, points):
    await send_typing(context, update.effective_chat.id)
    user = await random_user(update)
    update_aura(user.id, user.username, points)
    sign = "+" if points > 0 else ""
    await update.message.reply_html(f"{user.mention_html()} is {label}! {sign}{points} aura")

async def simp(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await aura_action(update, context, "the Simp of the Day", 100)

async def toxic(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await aura_action(update, context, "the most toxic one today", -50)

async def cringe(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await aura_action(update, context, "ultra cringe today", -50)

async def respect(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await aura_action(update, context, "respected like a legend", 500)

async def sus(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await aura_action(update, context, "acting kinda sus", 100)

# /aura leaderboard
async def aura(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await send_typing(context, update.effective_chat.id)
    leaderboard = get_aura_leaderboard()
    if not leaderboard:
        await update.message.reply_text("No aura data yet.")
        return
    msg = "🌟 Aura Leaderboard 🌟\n\n"
    for i, (username, aura) in enumerate(leaderboard, start=1):
        msg += f"{i}. @{username or 'unknown'} — {aura} aura\n"
    await update.message.reply_text(msg)

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

# Main
TOKEN = "YOUR_BOT_TOKEN"

def main():
    app = Application.builder().token(TOKEN).build()

    # Commands
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

    # Track all users who send any message
    app.add_handler(MessageHandler(filters.ALL, track_users))

    print("Bot is running...")
    app.run_polling()

if __name__ == "__main__":
    main()
