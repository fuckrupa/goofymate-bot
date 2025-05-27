import os
import sqlite3
import random
import pytz
from datetime import (
    datetime,
    date,
    timedelta
)

from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    User,
    BotCommand
)
from telegram.constants import ChatAction
from telegram.ext import (
    ApplicationBuilder,
    ContextTypes,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    filters
)

# --- Configuration ---
DB_PATH = "bot.db"
BD_TZ   = pytz.timezone("Asia/Dhaka")
TOKEN   = os.getenv("TELEGRAM_TOKEN")

# --- Database setup ---
conn = sqlite3.connect(
    DB_PATH,
    check_same_thread=False
)
c = conn.cursor()

c.execute(
    """
    CREATE TABLE IF NOT EXISTS users (
        user_id     INTEGER,
        chat_id     INTEGER,
        last_active TIMESTAMP,
        PRIMARY KEY (user_id,chat_id)
    )
    """
)
c.execute(
    """
    CREATE TABLE IF NOT EXISTS aura (
        user_id INTEGER,
        chat_id INTEGER,
        balance INTEGER DEFAULT 0,
        PRIMARY KEY (user_id,chat_id)
    )
    """
)
c.execute(
    """
    CREATE TABLE IF NOT EXISTS cooldowns (
        command  TEXT,
        chat_id  INTEGER,
        run_date DATE,
        PRIMARY KEY (command,chat_id,run_date)
    )
    """
)
c.execute(
    """
    CREATE TABLE IF NOT EXISTS announced (
        user_id INTEGER,
        chat_id INTEGER,
        command TEXT,
        last_ts TIMESTAMP,
        PRIMARY KEY (user_id,chat_id,command)
    )
    """
)
c.execute(
    """
    CREATE TABLE IF NOT EXISTS fights (
        fight_id INTEGER PRIMARY KEY AUTOINCREMENT,
        chat_id  INTEGER,
        user1    INTEGER,
        user2    INTEGER,
        msg_id   INTEGER,
        status   TEXT
    )
    """
)
conn.commit()

# --- Helpers ---
def record_user(
    user: User,
    chat_id: int
):
    now = datetime.utcnow().isoformat()
    c.execute(
        "INSERT OR REPLACE INTO users "
        "(user_id,chat_id,last_active) VALUES (?,?,?)",
        (user.id, chat_id, now)
    )
    c.execute(
        "INSERT OR IGNORE INTO aura "
        "(user_id,chat_id) VALUES (?,?)",
        (user.id, chat_id)
    )
    conn.commit()

def in_cooldown(
    cmd: str,
    chat_id: int
) -> bool:
    today = date.today().isoformat()
    c.execute(
        "SELECT 1 FROM cooldowns "
        "WHERE command=? AND chat_id=? AND run_date=?",
        (cmd, chat_id, today)
    )
    return c.fetchone() is not None

def set_cooldown(
    cmd: str,
    chat_id: int
):
    today = date.today().isoformat()
    c.execute(
        "INSERT OR REPLACE INTO cooldowns "
        "(command,chat_id,run_date) VALUES (?,?,?)",
        (cmd, chat_id, today)
    )
    conn.commit()

def can_announce(
    user_id: int,
    chat_id: int,
    cmd: str
) -> bool:
    now = datetime.utcnow()
    c.execute(
        "SELECT last_ts FROM announced "
        "WHERE user_id=? AND chat_id=? AND command=?",
        (user_id, chat_id, cmd)
    )
    row = c.fetchone()
    if not row:
        return True
    last = datetime.fromisoformat(row[0])
    return (now-last) >= timedelta(hours=1)

def set_announce_ts(
    user_id: int,
    chat_id: int,
    cmd: str
):
    now = datetime.utcnow().isoformat()
    c.execute(
        "INSERT OR REPLACE INTO announced "
        "(user_id,chat_id,command,last_ts) VALUES (?,?,?,?)",
        (user_id, chat_id, cmd, now)
    )
    conn.commit()

def change_aura(
    user_id: int,
    chat_id: int,
    delta: int
):
    c.execute(
        "UPDATE aura SET balance=balance+? "
        "WHERE user_id=? AND chat_id=?",
        (delta, user_id, chat_id)
    )
    conn.commit()

def pick_random_user(
    chat_id: int
) -> int:
    c.execute(
        "SELECT user_id FROM users "
        "WHERE chat_id=?",
        (chat_id,)
    )
    ids = [r[0] for r in c.fetchall()]
    return random.choice(ids) if ids else None

def pick_two_users(
    chat_id: int
):
    c.execute(
        "SELECT user_id FROM users "
        "WHERE chat_id=?",
        (chat_id,)
    )
    ids = [r[0] for r in c.fetchall()]
    if len(ids)<2:
        return None, None
    return random.sample(ids,2)

def bd_now():
    return datetime.now(BD_TZ)

def is_bd_night() -> bool:
    h = bd_now().hour
    return h>=20 or h<6

# --- Handlers ---
async def start(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):
    await context.bot.send_chat_action(
        update.effective_chat.id,
        ChatAction.TYPING
    )
    kb = [
        [
            InlineKeyboardButton(
                "Updates",
                url="https://t.me/YourChannel"
            ),
            InlineKeyboardButton(
                "Support",
                url="https://t.me/YourGroup"
            )
        ],
        [
            InlineKeyboardButton(
                "Add Me To Your Group",
                url=(
                    f"https://t.me/"
                    f"{context.bot.username}"
                    f"?startgroup=true"
                )
            )
        ]
    ]
    await update.effective_message.reply_text(
        "Welcome! I’m your fun Aura Bot. "
        "Use /gay, /couple, /simp, /toxic, "
        "/fight, /cringe, /respect, /sus, "
        "/aura or /ghost.",
        reply_markup=InlineKeyboardMarkup(kb)
    )

async def handle_daily(
    ctx,
    update,
    cmd,
    delta,
    award=True,
    text_template="{}"
):
    chat_id = update.effective_chat.id
    if in_cooldown(cmd,chat_id):
        return await update.effective_message.reply_text(
            f"❌ /{cmd} already used today."
        )

    if cmd in ("couple","fight_random"):
        u1,u2 = pick_two_users(chat_id)
        if not u1 or not u2:
            return await update.effective_message.reply_text(
                "Not enough users yet."
            )
        users = [
            await ctx.bot.get_chat_member(chat_id,u)
            for u in (u1,u2)
        ]
        mentions = [u.user.mention_html() for u in users]
        msg = text_template.format(*mentions)
        for u in (u1,u2):
            change_aura(u,chat_id,delta)
            if can_announce(u,chat_id,cmd):
                await ctx.bot.send_message(
                    chat_id, msg, parse_mode="HTML"
                )
                set_announce_ts(u,chat_id,cmd)
    else:
        uid = pick_random_user(chat_id)
        if not uid:
            return await update.effective_message.reply_text(
                "No users recorded yet."
            )
        member = await ctx.bot.get_chat_member(chat_id,uid)
        mention = member.user.mention_html()
        msg = text_template.format(mention)
        change_aura(uid,chat_id,delta)
        if can_announce(uid,chat_id,cmd):
            await update.effective_message.reply_html(msg)
            set_announce_ts(uid,chat_id,cmd)
        else:
            await update.effective_message.reply_html(
                msg+"\n(Already announced within the last hour.)"
            )

    set_cooldown(cmd,chat_id)

async def gay(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):
    await handle_daily(
        context,update,
        "gay",-100,
        award=False,
        text_template=(
            "🏳️‍🌈 Gay of the Day: {} 🏳️‍🌈"
        )
    )

async def couple(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):
    await handle_daily(
        context,update,
        "couple",+100,
        text_template=(
            "💕 Couple of the Day: {} + {} 💕"
        )
    )

async def simp(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):
    await handle_daily(
        context,update,
        "simp",+100,
        text_template=(
            "🥴 Biggest Simp Today: {} 🥴"
        )
    )

async def toxic(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):
    await handle_daily(
        context,update,
        "toxic",-100,
        text_template=(
            "☠️ Most Toxic Member: {} ☠️"
        )
    )

async def cringe(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):
    await handle_daily(
        context,update,
        "cringe",-100,
        text_template=(
            "🤢 Cringiest User: {} 🤢"
        )
    )

async def respect(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):
    await handle_daily(
        context,update,
        "respect",+500,
        text_template=(
            "🙏 Infinite Respect to: {} 🙏"
        )
    )

async def sus(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):
    await handle_daily(
        context,update,
        "sus",+100,
        text_template=(
            "🔍 Sus of the Day: {} 🔍"
        )
    )

async def fight(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):
    chat_id = update.effective_chat.id
    if update.message.reply_to_message:
        challenger = update.effective_user.id
        target      = (
            update.message
            .reply_to_message
            .from_user.id
        )
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton(
                "Accept Fight 🥊",
                callback_data=(
                    f"accept|{challenger}|"
                    f"{target}"
                )
            )]
        ])
        msg = await update.effective_message.reply_text(
            f"{update.effective_user.mention_html()} "
            f"has challenged "
            f"{update.message.reply_to_message.from_user.mention_html()} "
            f"to a fight!",
            parse_mode="HTML",
            reply_markup=kb
        )
        c.execute(
            "INSERT INTO fights "
            "(chat_id,user1,user2,msg_id,status) "
            "VALUES (?,?,?,?,?)",
            (chat_id,challenger,target,
             msg.message_id,'pending')
        )
        conn.commit()
    else:
        if in_cooldown("fight",chat_id):
            return await update.effective_message.reply_text(
                "❌ /fight already used today."
            )
        u1,u2 = pick_two_users(chat_id)
        if not u1 or not u2:
            return await update.effective_message.reply_text(
                "Not enough users yet."
            )
        m1 = (
            await context.bot
            .get_chat_member(chat_id,u1)
        ).user.mention_html()
        m2 = (
            await context.bot
            .get_chat_member(chat_id,u2)
        ).user.mention_html()
        winner  = random.choice([u1,u2])
        wmention=(
            await context.bot
            .get_chat_member(chat_id,winner)
        ).user.mention_html()
        change_aura(winner,chat_id,+100)
        await update.effective_message.reply_html(
            f"🥊 Fight: {m1} vs {m2}! "
            f"Winner: {wmention} 🎉"
        )
        set_cooldown("fight",chat_id)

async def button(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):
    query = update.callback_query
    await query.answer()
    data = query.data.split("|")
    if data[0]=="accept":
        _,u1,u2 = data
        u1,u2   = int(u1),int(u2)
        if query.from_user.id!=u2:
            return await query.edit_message_text(
                "Only the challenged user can accept."
            )
        winner = random.choice([u1,u2])
        wmention=(
            await query.bot
            .get_chat_member(
                query.message.chat_id,
                winner
            )
        ).user.mention_html()
        change_aura(
            winner,
            query.message.chat_id,
            +100
        )
        await query.edit_message_text(
            f"🥊 Fight accepted! "
            f"Winner: {wmention} 🎉",
            parse_mode="HTML"
        )

async def aura_cmd(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):
    chat_id = update.effective_chat.id
    c.execute(
        "SELECT user_id,balance FROM aura "
        "WHERE chat_id=?ORDER BY balance DESC",
        (chat_id,)
    )
    rows = c.fetchall()
    if not rows:
        return await update.effective_message.reply_text(
            "No aura data yet."
        )
    text = "🏆 Aura Leaderboard 🏆\n"
    for uid,bal in rows:
        user = (
            await context.bot
            .get_chat_member(chat_id,uid)
        ).user
        text += f"{user.full_name}: {bal}\n"
    await update.effective_message.reply_text(text)

async def ghost(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):
    chat_id = update.effective_chat.id
    now     = bd_now()
    if not is_bd_night():
        nxt = now.replace(
            hour=20,minute=0,
            second=0,microsecond=0
        )
        if now.hour>=20:
            nxt+=timedelta(days=1)
        mins = int(
            (nxt-now).total_seconds()//60
        )
        return await update.effective_message.reply_text(
            f"🌙 /ghost only works at "
            f"night BD time. {mins} mins until next."
        )
    c.execute(
        "SELECT user_id,MIN(last_active) "
        "FROM users WHERE chat_id=?",
        (chat_id,)
    )
    row = c.fetchone()
    if not row or not row[0]:
        return await update.effective_message.reply_text(
            "No activity data."
        )
    uid     = row[0]
    mention = (
        await context.bot
        .get_chat_member(chat_id,uid)
    ).user.mention_html()
    await update.effective_message.reply_html(
        f"👻 Ghost of the Night: {mention} 👻"
    )

async def track_all(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):
    record_user(
        update.effective_user,
        update.effective_chat.id
    )

async def set_commands(app):
    cmds = [
        BotCommand("start","Menu"),
        BotCommand("gay","Gay of Day"),
        BotCommand("couple","Couple of Day"),
        BotCommand("simp","Simp of Day"),
        BotCommand("toxic","Toxic Member"),
        BotCommand("cringe","Cringiest"),
        BotCommand("respect","Respect"),
        BotCommand("sus","Sus of Day"),
        BotCommand("fight","Fight"),
        BotCommand("aura","Aura Board"),
        BotCommand("ghost","Ghost Night")
    ]
    await app.bot.set_my_commands(cmds)

def main():
    app = (
        ApplicationBuilder()
        .token(TOKEN)
        .post_init(set_commands)
        .build()
    )
    app.add_handler(
        MessageHandler(
            filters.ALL&filters.ChatType.GROUPS,
            track_all
        )
    )
    app.add_handler(CommandHandler("start",start))
    app.add_handler(CommandHandler("gay",gay))
    app.add_handler(CommandHandler("couple",couple))
    app.add_handler(CommandHandler("simp",simp))
    app.add_handler(CommandHandler("toxic",toxic))
    app.add_handler(CommandHandler("cringe",cringe))
    app.add_handler(CommandHandler("respect",respect))
    app.add_handler(CommandHandler("sus",sus))
    app.add_handler(CommandHandler("fight",fight))
    app.add_handler(CallbackQueryHandler(button))
    app.add_handler(CommandHandler("aura",aura_cmd))
    app.add_handler(CommandHandler("ghost",ghost))
    app.run_polling()

if __name__=="__main__":
    main()
