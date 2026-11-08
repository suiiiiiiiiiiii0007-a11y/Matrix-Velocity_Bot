"""
Matrix Velocity - Matrix Premier League Captain Registration Bot
DM-only bot (python-telegram-bot v20+)

Install:  pip install "python-telegram-bot>=20.7"
Run:      python matrix_velocity_bot.py
"""
import html
import logging
import os
import re
import sqlite3
import time

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ChatType, ParseMode
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

# ============================ CONFIG (EDIT THESE) ============================
BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
ADMIN_IDS = {8632603116}           # Telegram user IDs allowed to use /addfile
OWNER_USERNAME = "@Suiiiiiii_0007"

# Bot must be ADMIN in both the group and the channel to verify membership
GROUP_ID = -1001111111111          # tournament group chat id
GROUP_LINK = "https://t.me/your_group"
CHANNEL_ID = -1002222222222        # tournament channel chat id
CHANNEL_LINK = "https://t.me/your_channel"

# Registrations are posted here (bot must be admin of this channel)
LOG_CHANNEL_ID = -1003333333333

SLOTS_PER_TEAM = 2                 # captains allowed per franchise (0/2)
ONE_REGISTRATION_PER_USER = True
DB_FILE = "matrix_velocity.db"
# ============================================================================

# code -> full name  (15 franchises, same order as the screenshot)
TEAMS = {
    "CSK": "Chennai Super Kings",
    "MI": "Mumbai Indians",
    "RCB": "Royal Challengers Bengaluru",
    "SRH": "Sunrisers Hyderabad",
    "KKR": "Kolkata Knight Riders",
    "RR": "Rajasthan Royals",
    "DC": "Delhi Capitals",
    "GT": "Gujarat Titans",
    "LSG": "Lucknow Super Giants",
    "PBKS": "Punjab Kings",
    "JSK": "Joburg Super Kings",
    "DSG": "Durban's Super Giants",
    "MICT": "MI Cape Town",
    "PR": "Paarl Royals",
    "PC": "Pretoria Capitals",
}

IPL_TEAMS = ["CSK", "MI", "RCB", "SRH", "KKR", "RR", "DC", "GT", "LSG", "PBKS"]
SA20_TEAMS = ["JSK", "DSG", "MICT", "PR", "PC"]

USERNAME_RE = re.compile(r"^@[A-Za-z][A-Za-z0-9_]{4,31}$")

logging.basicConfig(
    format="%(asctime)s %(levelname)s %(name)s: %(message)s", level=logging.INFO
)
log = logging.getLogger("matrix_velocity")


# ------------------------------- DATABASE ----------------------------------
def db():
    con = sqlite3.connect(DB_FILE)
    con.row_factory = sqlite3.Row
    return con


def init_db():
    with db() as con:
        con.execute(
            "CREATE TABLE IF NOT EXISTS files (key TEXT PRIMARY KEY, file_id TEXT)"
        )
        con.execute(
            """CREATE TABLE IF NOT EXISTS registrations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER, team TEXT,
                captain TEXT, vice TEXT, retained TEXT, ts INTEGER)"""
        )


def set_file(key, file_id):
    with db() as con:
        con.execute("INSERT OR REPLACE INTO files VALUES (?, ?)", (key, file_id))


def get_file(key):
    with db() as con:
        r = con.execute("SELECT file_id FROM files WHERE key=?", (key,)).fetchone()
    return r["file_id"] if r else None


def team_count(code):
    with db() as con:
        return con.execute(
            "SELECT COUNT(*) c FROM registrations WHERE team=?", (code,)
        ).fetchone()["c"]


def user_registered(user_id):
    with db() as con:
        return (
            con.execute(
                "SELECT 1 FROM registrations WHERE user_id=?", (user_id,)
            ).fetchone()
            is not None
        )


def username_taken(name):
    n = name.lower()
    with db() as con:
        return (
            con.execute(
                """SELECT 1 FROM registrations WHERE lower(captain)=? 
                   OR lower(vice)=? OR lower(retained)=?""",
                (n, n, n),
            ).fetchone()
            is not None
        )


def save_registration(user_id, team, cap, vice, ret):
    with db() as con:
        con.execute(
            "INSERT INTO registrations (user_id,team,captain,vice,retained,ts) "
            "VALUES (?,?,?,?,?,?)",
            (user_id, team, cap, vice, ret, int(time.time())),
        )


# ------------------------------- HELPERS -----------------------------------
def private_only(update: Update) -> bool:
    chat = update.effective_chat
    return chat is not None and chat.type == ChatType.PRIVATE


async def send_with_image(bot, chat_id, key, caption, reply_markup=None):
    """Send image stored under `key` with caption; fall back to plain text."""
    file_id = get_file(key)
    if file_id:
        try:
            return await bot.send_photo(
                chat_id,
                file_id,
                caption=caption,
                parse_mode=ParseMode.HTML,
                reply_markup=reply_markup,
            )
        except Exception as e:  # bad/expired file id
            log.warning("send_photo failed for %s: %s", key, e)
    return await bot.send_message(
        chat_id, caption, parse_mode=ParseMode.HTML, reply_markup=reply_markup
    )


def team_keyboard():
    buttons = [
        InlineKeyboardButton(
            f"{code} ({team_count(code)}/{SLOTS_PER_TEAM})", callback_data=f"team:{code}"
        )
        for code in TEAMS
    ]
    rows = [buttons[i : i + 2] for i in range(0, len(buttons), 2)]
    return InlineKeyboardMarkup(rows)


async def is_member(bot, chat_id, user_id) -> bool:
    try:
        m = await bot.get_chat_member(chat_id, user_id)
    except Exception as e:
        log.warning("get_chat_member(%s) failed: %s", chat_id, e)
        return False
    if m.status in ("member", "administrator", "creator"):
        return True
    return m.status == "restricted" and getattr(m, "is_member", False)


# ------------------------------- HANDLERS ----------------------------------
async def start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not private_only(update):
        return
    ctx.user_data.clear()
    caption = (
        "🏏 <b>MATRIX VELOCITY</b>\n\n"
        "Welcome to <b>Matrix Premier League!</b>\n\n"
        "Get ready to represent your franchise. "
        "Tap the button below to begin captain registration."
    )
    kb = InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("🏆 Captain Registration", callback_data="captain")],
            [InlineKeyboardButton("👤 Owner", callback_data="owner")],
        ]
    )
    await send_with_image(ctx.bot, update.effective_chat.id, "welcome", caption, kb)


async def on_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    if not private_only(update):
        await q.answer()
        return
    data = q.data
    uid = q.from_user.id

    if data == "owner":
        await q.answer()
        await ctx.bot.send_message(
            q.message.chat_id,
            f"👤 <b>Owner</b>\n\nContact: {html.escape(OWNER_USERNAME)}",
            parse_mode=ParseMode.HTML,
        )

    elif data == "captain":
        await q.answer()
        if ONE_REGISTRATION_PER_USER and user_registered(uid):
            await ctx.bot.send_message(
                q.message.chat_id, "⚠️ You have already completed a registration."
            )
            return
        kb = InlineKeyboardMarkup(
            [
                [InlineKeyboardButton("👥 Join Tournament Group", url=GROUP_LINK)],
                [InlineKeyboardButton("📢 Join Tournament Channel", url=CHANNEL_LINK)],
                [InlineKeyboardButton("✅ Verify Membership", callback_data="verify")],
            ]
        )
        await ctx.bot.send_message(
            q.message.chat_id,
            "🔐 <b>Member Verification</b>\n\n"
            "To continue with Captain Registration, please join BOTH the "
            "tournament group and channel. Then tap Verify Membership.",
            parse_mode=ParseMode.HTML,
            reply_markup=kb,
        )

    elif data == "verify":
        in_group = await is_member(ctx.bot, GROUP_ID, uid)
        in_channel = await is_member(ctx.bot, CHANNEL_ID, uid)
        if not (in_group and in_channel):
            missing = []
            if not in_group:
                missing.append("group")
            if not in_channel:
                missing.append("channel")
            await q.answer(
                f"❌ Please join the tournament {' and '.join(missing)} first.",
                show_alert=True,
            )
            return
        await q.answer()
        ctx.user_data["verified"] = True
        ctx.user_data["step"] = None
        await ctx.bot.send_message(
            q.message.chat_id,
            "✅ <b>Membership verified successfully!</b>\n\n"
            "🏆 Now select your franchise:",
            parse_mode=ParseMode.HTML,
            reply_markup=team_keyboard(),
        )

    elif data.startswith("team:"):
        code = data.split(":", 1)[1]
        if code not in TEAMS:
            await q.answer()
            return
        if not ctx.user_data.get("verified"):
            await q.answer("Please verify your membership first (/start).", show_alert=True)
            return
        if ONE_REGISTRATION_PER_USER and user_registered(uid):
            await q.answer("You have already completed a registration.", show_alert=True)
            return
        if team_count(code) >= SLOTS_PER_TEAM:
            await q.answer("❌ This franchise is full. Pick another one.", show_alert=True)
            try:
                await q.edit_message_reply_markup(reply_markup=team_keyboard())
            except Exception:
                pass
            return
        await q.answer()
        ctx.user_data.update(step="captain", team=code)
        await ctx.bot.send_message(
            q.message.chat_id,
            f"🏆 <b>{html.escape(TEAMS[code])} selected</b>\n\n"
            "Enter Captain's Telegram username starting with @:",
            parse_mode=ParseMode.HTML,
        )
    else:
        await q.answer()


PROMPTS = {
    "vice": "🥈 Enter Vice-Captain's Telegram username starting with @:",
    "retained": "⭐ Enter Retained Player's Telegram username starting with @:",
}


async def on_text(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not private_only(update) or not update.message or not update.message.text:
        return
    step = ctx.user_data.get("step")
    if step not in ("captain", "vice", "retained"):
        return

    text = update.message.text.strip()
    if not USERNAME_RE.match(text):
        await update.message.reply_text(
            "❌ Invalid username. It must start with @ and be 5-32 characters "
            "(letters, numbers, underscore). Try again:"
        )
        return

    entered = [ctx.user_data.get(k, "").lower() for k in ("captain", "vice", "retained")]
    if text.lower() in entered:
        await update.message.reply_text("❌ This username is already used in your entry. Send a different one:")
        return
    if username_taken(text):
        await update.message.reply_text("❌ This username is already registered in another team. Send a different one:")
        return

    ctx.user_data[step] = text

    if step == "captain":
        ctx.user_data["step"] = "vice"
        await update.message.reply_text(PROMPTS["vice"])
    elif step == "vice":
        ctx.user_data["step"] = "retained"
        await update.message.reply_text(PROMPTS["retained"])
    else:
        await finish_registration(update, ctx)


async def finish_registration(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    d = ctx.user_data
    code = d["team"]
    uid = update.effective_user.id

    if team_count(code) >= SLOTS_PER_TEAM:
        d.clear()
        await update.message.reply_text(
            "❌ Sorry, this franchise just got filled. Send /start to pick another."
        )
        return

    save_registration(uid, code, d["captain"], d["vice"], d["retained"])

    caption = (
        "🏏 <b>MATRIX PREMIER LEAGUE — CAPTAIN REGISTRATION</b>\n\n"
        f"🏆 <b>Franchise:</b> {html.escape(TEAMS[code])} ({code})\n"
        f"👑 <b>Captain:</b> {d['captain']}\n"
        f"🥈 <b>Vice-Captain:</b> {d['vice']}\n"
        f"⭐ <b>Retained:</b> {d['retained']}\n\n"
        "✅ <b>Registration Confirmed!</b>"
    )

    # Confirmation to the user
    await send_with_image(ctx.bot, update.effective_chat.id, f"logo:{code}", caption)
    # Post to log channel
    try:
        await send_with_image(ctx.bot, LOG_CHANNEL_ID, f"logo:{code}", caption)
    except Exception as e:
        log.error("Could not post to log channel: %s", e)

    d.clear()


async def addfile(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """
    Admin only.
      /addfile            -> set welcome image
      /addfile MI         -> set Mumbai Indians logo
    Use it as the caption of a photo, or reply to a photo with the command.
    """
    if not private_only(update) or not update.message:
        return
    msg = update.message
    if update.effective_user.id not in ADMIN_IDS:
        await msg.reply_text("⛔ Admins only.")
        return

    text = msg.text or msg.caption or ""
    args = text.split()[1:]

    src = msg
    if not msg.photo and msg.reply_to_message:
        src = msg.reply_to_message
    file_id = None
    if src.photo:
        file_id = src.photo[-1].file_id
    elif src.document and (src.document.mime_type or "").startswith("image/"):
        file_id = src.document.file_id

    if not file_id:
        await msg.reply_text(
            "Send a photo with caption:\n"
            "• /addfile  → welcome image\n"
            "• /addfile MI  → team logo\n\n"
            "Or reply to a photo with the same command.\n"
            "Teams: " + ", ".join(TEAMS)
        )
        return

    if not args:
        set_file("welcome", file_id)
        await msg.reply_text("✅ Welcome image updated.")
        return

    code = args[0].upper()
    if code not in TEAMS:
        await msg.reply_text("❌ Unknown team. Valid: " + ", ".join(TEAMS))
        return
    set_file(f"logo:{code}", file_id)
    await msg.reply_text(f"✅ Logo saved for {TEAMS[code]} ({code}).")


async def info(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Show all team short names with full forms."""
    if not private_only(update) or not update.message:
        return
    ipl = "\n".join(f"• <b>{c}</b> — {html.escape(TEAMS[c])}" for c in IPL_TEAMS)
    sa = "\n".join(f"• <b>{c}</b> — {html.escape(TEAMS[c])}" for c in SA20_TEAMS)
    await update.message.reply_text(
        "🏏 <b>MATRIX PREMIER LEAGUE — TEAMS</b>\n\n"
        "🇮🇳 <b>IPL Teams (10)</b>\n" + ipl + "\n\n"
        "🇿🇦 <b>SA20 Teams (5)</b>\n" + sa,
        parse_mode=ParseMode.HTML,
    )


async def files_status(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Admin: show which images are set."""
    if not private_only(update) or update.effective_user.id not in ADMIN_IDS:
        return
    lines = [f"Welcome image: {'✅' if get_file('welcome') else '❌'}"]
    for c in TEAMS:
        lines.append(f"{c}: {'✅' if get_file('logo:' + c) else '❌'}")
    await update.message.reply_text("\n".join(lines))


def main():
    if not BOT_TOKEN:
        raise RuntimeError("BOT_TOKEN is missing. Set it as an environment variable.")
    init_db()
    app = Application.builder().token(BOT_TOKEN).build()
    P = filters.ChatType.PRIVATE

    app.add_handler(CommandHandler("start", start, filters=P))
    app.add_handler(CommandHandler("addfile", addfile, filters=P))
    app.add_handler(CommandHandler("files", files_status, filters=P))
    app.add_handler(CommandHandler("info", info, filters=P))
    # /addfile sent as a photo caption
    app.add_handler(
        MessageHandler(
            P & (filters.PHOTO | filters.Document.IMAGE) & filters.CaptionRegex(r"^/addfile"),
            addfile,
        )
    )
    app.add_handler(CallbackQueryHandler(on_callback))
    app.add_handler(MessageHandler(P & filters.TEXT & ~filters.COMMAND, on_text))

    log.info("Matrix Velocity bot running (DM only)...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
