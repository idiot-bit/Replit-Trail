import json
import time
import random
import os
import re
import sys
import traceback
import asyncio
import zipfile
import inspect
import shutil
from html import escape
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from telegram.error import BadRequest, Forbidden
from telegram.constants import ParseMode
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, KeyboardButton, InputMediaDocument
from telegram.ext import Application, CommandHandler, MessageHandler, filters, CallbackQueryHandler, ContextTypes, ApplicationBuilder

# Load bot token from Railway environment
BOT_TOKEN = os.getenv("BOT_TOKEN")
if not BOT_TOKEN:
    raise ValueError("BOT_TOKEN environment variable not set")

# === GLOBAL CONSTANTS AND DEFAULTS ===
STATE_FILE = "state.json"
START_TIME = time.time()
UPDATE_DATE = datetime.fromtimestamp(START_TIME, ZoneInfo("Asia/Kolkata")).strftime("%d-%m-%Y")
LAST_ERROR_TIME = 0
ERROR_COOLDOWN = 30
BROADCAST_SESSION = {}
state_lock = asyncio.Lock()

# === DEFAULT GLOBAL DICTS ===
USER_STATE = {}
AUTO4_STATE = {
    "pending_apks": [],
    "timer": None,
    "waiting_since": None,
    "countdown_msg_id": None,
    "setup_mode": 1
}
AUTO_SETUP = {}
USER_DATA = {}

# === Load config.json ===
with open("config.json") as f:
    config = json.load(f)

OWNER_ID = config.get("owner_id")
ALLOWED_USERS = set(config.get("allowed_users", []))
USER_DATA = config.get("user_data", {})
BOT_ADMIN_LINK = config.get("bot_admin_link", "")
BOT_ACTIVE = config.get("bot_active", True)

AUTO_SETUP = config.get("auto_setup", {
    "setup1": {
        "source_channel": "",
        "dest_channel": "",
        "dest_caption": "",
        "key_mode": "auto",
        "style": "mono",
        "enabled": False,
        "completed_count": 0
    },
    "setup2": {
        "source_channel": "",
        "dest_channel": "",
        "dest_caption": "",
        "key_mode": "auto",
        "style": "mono",
        "enabled": False,
        "completed_count": 0
    },
    "setup3": {
        "source_channel": "",
        "dest_channel": "",
        "dest_caption": "",
        "key_mode": "auto",
        "style": "mono",
        "enabled": False,
        "completed_count": 0
    },
    "setup4": {
        "source_channel": "",
        "dest_channel": "",
        "dest_caption": "",
        "key_mode": "auto",
        "style": "mono",
        "enabled": False,
        "completed_count": 0,
        "processed_count": 0
    }
})

# Reusable button for all reports
CENTRAL_AUTHORITY_BTN = InlineKeyboardMarkup([
    [InlineKeyboardButton("⚙ Contact Central Authority", url="https://t.me/Ceo_DarkFury")]
])

# === Load saved state.json ===
def load_state():
    global USER_STATE, AUTO4_STATE, AUTO_SETUP, USER_DATA, ALLOWED_USERS
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, "r") as f:
                data = json.load(f)
                # Safely load user state
                restored_users = data.get("user_state", {})
                for uid, udata in restored_users.items():
                    USER_STATE[int(uid)] = udata  # Convert to int for consistency
                AUTO4_STATE.update(data.get("auto4_state", {}))
                AUTO_SETUP.update(data.get("auto_setup", {}))
                USER_DATA.update(data.get("user_data", {}))
        except json.JSONDecodeError as e:
            print(f"[ERROR] Failed to load state.json: {e}")

    if os.path.exists("config.json"):
        with open("config.json") as f:
            config = json.load(f)
            ALLOWED_USERS = set(config.get("allowed_users", []))

def save_state():
    try:
        # Ensure keys are saved as strings for JSON compatibility
        serializable_user_state = {
            str(user_id): data for user_id, data in USER_STATE.items()
        }

        with open(STATE_FILE, "w") as f:
            json.dump({
                "user_state": serializable_user_state,
                "auto4_state": AUTO4_STATE,
                "auto_setup": AUTO_SETUP,
                "user_data": USER_DATA
            }, f, indent=4)

        print("[STATE] Saved state.json successfully.")
    except Exception as e:
        print(f"[ERROR] Failed to save state.json: {e}")

def update_user_stats(user_id: int, method: str, apks: int = 0, keys: int = 0):
    if user_id not in USER_STATE:
        USER_STATE[user_id] = {}

    # All-time Total Stats (Fix part)
    USER_STATE[user_id][f"alltime_{method}_apks"] = USER_STATE[user_id].get(f"alltime_{method}_apks", 0) + apks
    USER_STATE[user_id][f"alltime_{method}_keys"] = USER_STATE[user_id].get(f"alltime_{method}_keys", 0) + keys

    # Total Persistent
    USER_STATE[user_id][f"total_{method}_apks"] = USER_STATE[user_id].get(f"total_{method}_apks", 0) + apks
    USER_STATE[user_id][f"total_{method}_keys"] = USER_STATE[user_id].get(f"total_{method}_keys", 0) + keys

    # Scoped Reporting
    for scope in ["8hr", "daily", "weekly", "monthly"]:
        USER_STATE[user_id][f"{scope}_{method}_apks"] = USER_STATE[user_id].get(f"{scope}_{method}_apks", 0) + apks
        USER_STATE[user_id][f"{scope}_{method}_keys"] = USER_STATE[user_id].get(f"{scope}_{method}_keys", 0) + keys

def save_config():
    with open("config.json", "w") as f:
        json.dump({
            "owner_id": OWNER_ID,
            "allowed_users": list(ALLOWED_USERS),
            "user_data": USER_DATA,
            "auto_setup": AUTO_SETUP,
            "bot_active": BOT_ACTIVE,
            "bot_admin_link": BOT_ADMIN_LINK
        }, f, indent=4)

def save_auto_setup():
    if os.path.exists("config.json"):
        try:
            with open("config.json", "r") as f:
                data = json.load(f)
            data["auto_setup"] = AUTO_SETUP
            with open("config.json", "w") as f:
                json.dump(data, f, indent=4)
        except Exception as e:
            print(f"[ERROR] save_auto_setup failed: {e}")

# Add this helper function at top
def parse_buttons_grid_2x2(raw: str) -> InlineKeyboardMarkup:
    """
    Converts lines like:
    Join | https://t.me/yourchannel
    Support | https://t.me/support
    Into:
    [ Join     ] [ Support ]
    """
    from telegram import InlineKeyboardMarkup, InlineKeyboardButton

    lines = raw.strip().splitlines()
    buttons = []
    row = []

    for line in lines:
        if not line.strip():
            continue  # skip blank lines

        if "|" in line:
            parts = line.strip().split("|", 1)
            if len(parts) == 2:
                text, url = parts
                if url.strip().startswith("http"):
                    row.append(InlineKeyboardButton(text.strip(), url.strip()))
                    if len(row) == 2:
                        buttons.append(row)
                        row = []

    if row:
        buttons.append(row)

    return InlineKeyboardMarkup(buttons) if buttons else None

def generate_method_keyboard(user_id: int) -> InlineKeyboardMarkup:
    user_data = USER_DATA.get(str(user_id), {})
    channel = user_data.get("channel")
    caption = user_data.get("caption")
    current_method = USER_STATE.get(user_id, {}).get("current_method")

    buttons = []

    # Row 1: Bot Admin always on top if available
    if BOT_ADMIN_LINK:
        buttons.append([InlineKeyboardButton("👨‍💻 Bot Admin", url=BOT_ADMIN_LINK)])

    # Row 2: Set/Reset Channel and Caption
    row2 = []
    if channel:
        row2.append(InlineKeyboardButton("📡 Reset Channel", callback_data="reset_channel"))
    else:
        row2.append(InlineKeyboardButton("📡 Set Channel", callback_data="set_channel"))

    if caption:
        row2.append(InlineKeyboardButton("📝 Reset Caption", callback_data="reset_caption"))
    else:
        row2.append(InlineKeyboardButton("📝 Set Caption", callback_data="set_caption"))
    buttons.append(row2)

    # Row 3: Send APK button only if both are set
    if channel and caption:
        if current_method == "method1":
            buttons.append([InlineKeyboardButton("📤 Send One APK", callback_data="send_apk_method1")])
        elif current_method == "method2":
            buttons.append([InlineKeyboardButton("📤 Send 2–3 APKs", callback_data="send_apk_method2")])

    # Row 4: Back to Methods
    buttons.append([InlineKeyboardButton("🔙 Back to Methods", callback_data="back_to_methods")])

    return InlineKeyboardMarkup(buttons)

# Load persisted state from previous session
load_state()

# === Keyboards ===
owner_keyboard = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton("UserStats")],
        [KeyboardButton("Userlist"), KeyboardButton("Help")],
        [KeyboardButton("Ping"), KeyboardButton("Rules")],
        [KeyboardButton("Reset"), KeyboardButton("Settings")],
        [KeyboardButton("Broadcast")],
        [KeyboardButton("On"), KeyboardButton("Off")]
    ],
    resize_keyboard=True,
    one_time_keyboard=False
)

allowed_user_keyboard = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton("METHOD 1"), KeyboardButton("METHOD 2")],
        [KeyboardButton("My Channel"), KeyboardButton("My Caption")],
        [KeyboardButton("Viewsetup")],
        [KeyboardButton("Help"), KeyboardButton("Reset")],
        [KeyboardButton("Ping"), KeyboardButton("Rules")]
    ],
    resize_keyboard=True,
    one_time_keyboard=False
)

async def autosave_task():
    while True:
        await asyncio.sleep(60)
        async with state_lock:
            save_state()

async def backup_config(context=None, query=None):
    now = datetime.now(ZoneInfo("Asia/Kolkata"))
    date_str = now.strftime("%d-%m-%Y")
    time_str = now.strftime("%I:%M%p").lower()
    zip_filename = f"/tmp/Backup_{date_str}_{time_str}.zip"

    async with state_lock:
        save_state()

    try:
        with zipfile.ZipFile(zip_filename, "w") as zipf:
            for filename in ["config.json", "state.json", "main.py", "requirements.txt", "Procfile"]:
                if os.path.exists(filename):
                    zipf.write(filename)
                else:
                    print(f"[WARN] {filename} not found, skipping...")
    except Exception as e:
        print(f"Error creating ZIP: {e}")
        return

    if context:
        try:
            caption = (
                "<pre>\n"
                "[✔] BOT BACKUP SUCCESS\n"
                "├ Date : {date}\n"
                "├ Time : {time}\n"
                "├ File : backup_{date}.zip\n"
                "└ Path : /var/bot/\n"
                "</pre>"
            ).format(date=date_str, time=time_str)
    
            with open(zip_filename, "rb") as f:
                await context.bot.send_document(
                    chat_id=OWNER_ID,
                    document=f,
                    caption=caption,
                    parse_mode="HTML"
                )
        except Exception as e:
            print(f"Failed to send backup: {e}")

    if os.path.exists(zip_filename):
        os.remove(zip_filename)

    if query:
        await query.edit_message_text(
            text="✅ Full backup ZIP sent to your PM!",
            reply_markup=get_main_inline_keyboard()
        )

def is_authorized(user_id: int) -> bool:
    return user_id == OWNER_ID or user_id in ALLOWED_USERS

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        user = update.effective_user
        user_id = user.id
        user_key = str(user_id)

        # Save user info for tracking
        if user_key not in USER_DATA:
            USER_DATA[user_key] = {
                "first_name": user.first_name,
                "username": user.username,
                "first_seen": int(time.time()),
            }
            save_config()
        else:
            # Ensure first_seen is always present
            if "first_seen" not in USER_DATA[user_key]:
                USER_DATA[user_key]["first_seen"] = int(time.time())
                save_config()

        # Authorization check
        if not is_authorized(user_id):
            keyboard = [
                [InlineKeyboardButton("📩 Request Access", url="https://t.me/Ceo_DarkFury")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)

            await update.message.reply_text(
                "⛔️ <b>Unauthorized Access</b>\n"
                "━━━━━━━━━━━━━━━━━━━━━━\n"
                "You are not whitelisted to use this system.\n"
                "Access is restricted to approved users only.\n\n"
                "🛡️ <i>Your activity has been logged.</i>\n"
                "━━━━━━━━━━━━━━━━━━━━━━\n"
                "🧠 <b>Secure Systems by:</b> @Ceo_DarkFury",
                parse_mode="HTML",
                disable_web_page_preview=True,
                reply_markup=reply_markup
            )
            return

        # Cancel any leftover countdown task
        if user_id in USER_STATE:
            task = USER_STATE[user_id].get("countdown_task")
            if task and not task.done():
                task.cancel()

        # Reset session state
        USER_STATE[user_id] = {
            "current_method": None,
            "status": "selecting_method",
            "session_files": [],
            "session_filenames": [],
            "saved_key": None,
            "apk_posts": [],
            "waiting_key": False,
            "key_prompt_sent": False,
            "quote_applied": False,
            "mono_applied": False,
            "key_mode": "normal",
            "last_apk_time": None,
            "last_post_link": None,
            "preview_message_id": None,
            "progress_message_id": None,
            "countdown_msg_id": None,
            "countdown_task": None,
            "last_post_session": {}
        }

        # Format user info
        first_seen = USER_DATA[user_key]["first_seen"]
        now = int(time.time())
        days_count = (now - first_seen) // 86400
        india_tz = ZoneInfo("Asia/Kolkata")
        join_date = datetime.fromtimestamp(first_seen, tz=india_tz)

        keyboard = [
            [InlineKeyboardButton("⚡ Method 1", callback_data="method_1")],
            [InlineKeyboardButton("🚀 Method 2", callback_data="method_2")]
        ]

        if user_id == OWNER_ID:
            keyboard.append([InlineKeyboardButton("🛠 Method 3", callback_data="method_3")])

        await update.message.reply_text(
            "<b>𝗖𝗘𝗢 𝗣𝗔𝗡𝗘𝗟 🏆</b>\n"
            "<blockquote>"
            "<b>━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"• 👤 Name     : {user.first_name or 'User'}\n"
            f"• 🆔 User ID  : <a href=\"tg://user?id={user_id}\">{user_id}</a>\n"
            f"• ⏱️ Days     : {days_count} Days\n"
            "• ✅ Access   : Authorized ✓\n"
            "• ⚙️ System   : Online ✓\n\n"
            "      <b>𝗨𝗽𝗹𝗼𝗮𝗱 𝗠𝗲𝘁𝗵𝗼𝗱𝘀</b>\n"
            "➡ Method 1 - 𝚄𝚙𝚕𝚘𝚊𝚍 𝟷/𝟷 𝙰𝚙𝚔\n"
            "➡ Method 2 - 𝚄𝚙𝚕𝚘𝚊𝚍 𝟹/𝟹 𝙰𝚙𝚔𝚜\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━</b>"
            "</blockquote>\n"
            "<i><b>NOTE:</b> System logs are being monitored.</i>",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(keyboard),
            disable_web_page_preview=True
        )

    except Exception as e:
        await notify_owner_on_error(context.bot, e, source="start")

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        user_id = update.effective_user.id

        if user_id == OWNER_ID:
            await update.message.reply_text(
                "<b>🧰 BOT CONTROL PANEL – OWNER ACCESS</b>\n\n"
                "<b>📌 Core Management</b>\n"
                "• /start — Restart bot session\n"
                "• /ping — Check bot uptime\n"
                "• /rules — View bot usage policy\n\n"
                "<b>📤 Upload Configuration</b>\n"
                "• /setchannelid — Set target channel\n"
                "• /setcaption — Define custom caption\n"
                "• /resetcaption — Clear caption\n"
                "• /resetchannelid — Clear channel setting\n"
                "• /reset — Full user data reset\n\n"
                "<b>👥 User Access Control</b>\n"
                "• /adduser — Grant user access\n"
                "• /removeuser — Revoke access\n"
                "• /userlist — View allowed users",
                parse_mode="HTML"
            )

        elif user_id in ALLOWED_USERS:
            await update.message.reply_text(
                "<b>🧩 USER MENU</b>\n\n"
                "<b>🔧 Essentials</b>\n"
                "• /start — Start interaction\n"
                "• /ping — Bot status\n"
                "• /rules — Usage guidelines\n\n"
                "<b>⚙️ Settings</b>\n"
                "• /setchannelid — Set your upload channel\n"
                "• /setcaption — Set your caption\n"
                "• /resetchannelid — Reset channel\n"
                "• /resetcaption — Reset caption\n"
                "• /reset — Reset all settings",
                parse_mode="HTML"
            )

        else:
            await update.message.reply_text("🚫 Access Denied: You are not authorized to use this bot.")

    except Exception as e:
        await notify_owner_on_error(context.bot, e, source="help_command")
        
async def add_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        if update.effective_user.id != OWNER_ID:
            await update.message.reply_text(
                "⛔ <b>Access Denied</b>\n"
                "You are not authorized to add users.\n\n"
                "🔗 Contact admin: <a href='https://t.me/Ceo_DarkFury'>@Ceo_DarkFury</a>",
                parse_mode="HTML"
            )
            return

        if not context.args:
            await update.message.reply_text(
                "⚠️ <b>Missing Argument</b>\n"
                "You need to provide a user ID to add.\n\n"
                "📝 Example:\n<code>/adduser 123456789</code>",
                parse_mode="HTML"
            )
            return

        try:
            user_id = int(context.args[0])
            ALLOWED_USERS.add(user_id)

            # Fetch user info
            try:
                user = await context.bot.get_chat(user_id)
                USER_DATA[str(user_id)] = {
                    "first_name": user.first_name or "—",
                    "username": user.username or "—",
                    "channel": USER_DATA.get(str(user_id), {}).get("channel", "—"),
                    "first_seen": int(time.time())
                }
            except Exception as e:
                print(f"[!] Failed to fetch user info: {e}")
                USER_DATA[str(user_id)] = {
                    "first_name": "—",
                    "username": "—",
                    "channel": "—",
                    "first_seen": int(time.time())
                }

            save_config()

            await update.message.reply_text(
                f"✅ <b>User Added Successfully!</b>\n\n"
                f"<b>🆔 ID:</b> <code>{user_id}</code>",
                parse_mode="HTML"
            )

        except ValueError:
            await update.message.reply_text(
                "❌ <b>Invalid ID</b>\n"
                "Please enter a numeric user ID.",
                parse_mode="HTML"
            )

    except Exception as e:
        await notify_owner_on_error(context.bot, e, source="add_user")
        
async def remove_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        if update.effective_user.id != OWNER_ID:
            await update.message.reply_text(
                "🗣️ <b>𝖳𝗁𝗂𝗋𝗎𝗆𝖻𝗂 𝖯𝖺𝖺𝗋𝗎𝖽𝖺 𝖳𝗁𝖾𝗏𝖽𝗂𝗒𝖺 𝖯𝖺𝗂𝗒𝖺</b>",
                parse_mode=ParseMode.HTML
            )
            return

        if not context.args:
            await update.message.reply_text(
                "📝 <b>Usage:</b> <code>/removeuser &lt;user_id&gt;</code>\n"
                "Don't leave me hanging!",
                parse_mode=ParseMode.HTML
            )
            return

        try:
            user_id = int(context.args[0])
            ALLOWED_USERS.discard(user_id)
            save_config()
            await update.message.reply_text(
                f"👋 <b>User</b> <code>{user_id}</code> <b>has been kicked out of the VIP list!</b> 🚪💨",
                parse_mode=ParseMode.HTML
            )
        except ValueError:
            await update.message.reply_text(
                "❌ <b>Invalid ID:</b> Please enter numbers only! 🔢",
                parse_mode=ParseMode.HTML
            )

    except Exception as e:
        await notify_owner_on_error(context.bot, e, source="remove_user")
    
async def userlist(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        user_id = update.effective_user.id
    
        if user_id != OWNER_ID:
            msg = (
                f"<pre>"
                f"┌─『 UNAUTHORIZED ACCESS 』─┐\n"
                f"│ 🆔 ID: {user_id}\n"
                f"│ ❌ Only the CEO can access this.\n"
                f"└────────────────────────────┘"
                f"</pre>\n"
                f"🧠 <i>Powered by</i> <a href='https://t.me/Ceo_DarkFury'>@Ceo_DarkFury</a>"
            )
            if update.message:
                await update.message.reply_text(msg, parse_mode="HTML", disable_web_page_preview=True)
            elif update.callback_query:
                await update.callback_query.message.reply_text(msg, parse_mode="HTML", disable_web_page_preview=True)
            return
    
        if not ALLOWED_USERS:
            reply = "❌ <b>No allowed users found.</b>"
            if update.message:
                await update.message.reply_text(reply, parse_mode="HTML")
            elif update.callback_query:
                await update.callback_query.message.reply_text(reply, parse_mode="HTML")
            return
    
        lines = [f"🧾 <b>Total Allowed Users:</b> {len(ALLOWED_USERS)}\n"]
    
        for index, uid in enumerate(ALLOWED_USERS, start=1):
            user_data = USER_DATA.get(str(uid), {})
    
            if "first_name" not in user_data or "username" not in user_data:
                try:
                    chat = await context.bot.get_chat(uid)
                    user_data["first_name"] = chat.first_name or "—"
                    user_data["username"] = chat.username or "—"
                    USER_DATA[str(uid)] = user_data
                    save_config()
                except:
                    user_data.setdefault("first_name", "—")
                    user_data.setdefault("username", "—")
    
            name = user_data.get("first_name", "—")
            username = user_data.get("username", "—")
            channel = user_data.get("channel", "—")
    
            lines.append(
                f"📌 <b>User {index}</b>\n"
                f"├─ 👤 <b>Name:</b> {name}\n"
                f"├─ 🧬 <b>Username:</b> {'@' + username if username and username != '—' else '—'}\n"
                f"├─ 📡 <b>Channel:</b> {channel}\n"
                f"└─ 🆔 <b>ID:</b> <a href=\"tg://openmessage?user_id={uid}\">{uid}</a>\n"
                f"━━━━━━━━━━━━━━━━━━━━"
            )
    
        text = "\n".join(lines)
    
        if update.message:
            await update.message.reply_text(text, parse_mode="HTML", disable_web_page_preview=True)
        elif update.callback_query:
            await update.callback_query.message.reply_text(text, parse_mode="HTML", disable_web_page_preview=True)

    except Exception as e:
        await notify_owner_on_error(context.bot, e, source="userlist")

async def ping(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        if not is_authorized(update.effective_user.id):
            await update.message.reply_text("𝖵𝖺𝗇𝗍𝗁𝖺 𝗈𝖽𝖺𝗇𝖾 𝖮𝗆𝖻𝗎𝗍𝗁𝖺 𝖽𝖺𝖺 𝖻𝖺𝖺𝖽𝗎🫂")
            return
    
        uptime_seconds = int(time.time() - START_TIME)
        days, remainder = divmod(uptime_seconds, 86400)
        hours, remainder = divmod(remainder, 3600)
        minutes, seconds = divmod(remainder, 60)
    
        ping_ms = round(random.uniform(10, 60), 2)
        now = datetime.now(ZoneInfo("Asia/Kolkata"))
        date_str = now.strftime("%d-%m-%Y")
        time_str = now.strftime("%I:%M %p")
    
        msg = (
            "<b>⚙️ 𝗦𝗬𝗦𝗧𝗘𝗠 𝗦𝗧𝗔𝗧𝗨𝗦 𝗥𝗘𝗣𝗢𝗥𝗧</b>\n"
            "━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"📅 <b>Date:</b> <code>{date_str}</code>\n"
            f"⏰ <b>Time:</b> <code>{time_str}</code>\n"
            f"🧾 <b>Update:</b> <code>{UPDATE_DATE}</code>\n"
            f"⏱️ <b>Uptime:</b> <code>{days}D {hours}H {minutes}M {seconds}S</code>\n"
            f"⚡ <b>Latency:</b> <code>{ping_ms} ms</code>\n"
            "━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"🧠 <i>Powered by</i> <a href='https://t.me/Ceo_DarkFury'>@Ceo_DarkFury</a>"
        )
    
        await update.message.reply_text(msg, parse_mode="HTML", disable_web_page_preview=True)
    
    except Exception as e:
        await notify_owner_on_error(context.bot, e, source="ping")
    
async def rules(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        user_id = update.effective_user.id

        if not is_authorized(user_id):
            await update.message.reply_text(
                "📜 <b>Bot Usage Notice</b>\n\n"
                "This bot is restricted to <b>authorized users only</b>.\n"
                "If you believe you should have access, please contact the administrator.\n\n"
                "🔗 <a href='https://t.me/Ceo_DarkFury'>@Ceo_DarkFury</a>",
                parse_mode="HTML",
                disable_web_page_preview=True
            )
            return

        # Inline keyboard for authorized users only
        keyboard = [
            [InlineKeyboardButton("📩 Contact Central Authority", url="https://t.me/Ceo_DarkFury")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)

        await update.message.reply_text(
            "🧬 <b>ACCESS LEVEL:</b> <code>CEO INTERFACE</code>\n"
            "<i>Initializing Rule Matrix...</i>\n"
            "━━━━━━━━━━━━━━━━━━━━━━━\n"
            "⚠️ <b>Rule 01:</b> <code>No spamming</code>\n"
            "⚠️ <b>Rule 02:</b> <code>No flooding commands</code>\n"
            "⚠️ <b>Rule 03:</b> <code>Violators = Immediate lockdown</code>\n"
            "━━━━━━━━━━━━━━━━━━━━━━━\n"
            "<i>Uplink: <b>Secure</b> | Monitoring: <b>Active</b></i>\n"
            "💬 <b>Need escalation?</b>",
            parse_mode="HTML",
            disable_web_page_preview=True,
            reply_markup=reply_markup
        )

    except Exception as e:
        await notify_owner_on_error(context.bot, e, source="rules")
        
async def reset_caption(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        user_id = update.effective_user.id
        if not is_authorized(user_id):
            await update.message.reply_text("🫥𝖭𝖺𝖺𝗇𝗍𝗁𝖺𝗇 𝖽𝖺𝖺 𝗅𝖾𝗈𝗈")
            return

        USER_DATA.setdefault(str(user_id), {})["caption"] = ""
        save_config()

        await update.message.reply_text(
            "🧼 *Caption Cleared\\!* \nReady for a fresh start\\? ➕\nUse /SetCaption to drop a new vibe 🎯",
            parse_mode="MarkdownV2"
        )

    except Exception as e:
        await notify_owner_on_error(context.bot, e, source="reset_caption")

async def reset_channel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        user_id = update.effective_user.id
        if not is_authorized(user_id):
            await update.message.reply_text("🗣️𝖮𝗈𝗆𝖻𝗎𝗎𝗎")
            return

        USER_DATA.setdefault(str(user_id), {})["channel"] = ""
        save_config()

        await update.message.reply_text(
            "📡 <b>Channel ID wiped!</b> ✨\nSet new one: <b>/setchannelid</b> 🛠️🚀",
            parse_mode="HTML"
        )

    except Exception as e:
        await notify_owner_on_error(context.bot, e, source="reset_channel")

async def reset(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        user_id = update.effective_user.id

        if not is_authorized(user_id):
            await update.message.reply_text("🗣️𝖮𝗈𝗆𝖻𝗎𝗎𝗎")
            return

        # Reset only this user's data
        USER_DATA[str(user_id)] = {
            "channel": "",
            "caption": ""
        }
        save_config()

        # Decide which keyboard to show
        if user_id == OWNER_ID:
            reply_markup = owner_keyboard
        else:
            reply_markup = allowed_user_keyboard

        await update.message.reply_text(
            "🧹 <b>Your data cleaned!</b>\n"
            "No more caption or channel. 🚮\n"
            "Ready to Setup. 🚀",
            parse_mode="HTML",
            reply_markup=reply_markup
        )

    except Exception as e:
        await notify_owner_on_error(context.bot, e, source="reset")

async def set_channel_id(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        user_id = update.effective_user.id

        if not is_authorized(user_id):
            await update.effective_message.reply_text("🗣️ 𝖮𝗈𝗆𝖻𝗎𝗎𝗎")
            return

        USER_STATE.setdefault(user_id, {}).update({"status": "waiting_channel"})

        keyboard = []
        if BOT_ADMIN_LINK:
            keyboard.append([InlineKeyboardButton("👨‍💻 Bot Admin", url=BOT_ADMIN_LINK)])

        await update.effective_message.reply_text(
            "🔧 <b>Setup Time!</b>\n"
            "Send me your Channel ID now. 📡\n"
            "Format: <code>@yourchannel</code> or <code>-100xxxxxxxxxx</code>\n\n"
            "⚠️ Make sure the bot is added as ADMIN in that channel!",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(keyboard) if keyboard else None
        )

    except Exception as e:
        await notify_owner_on_error(context.bot, e, source="set_channel_id")

async def validate_channel_admin(update: Update, context: ContextTypes.DEFAULT_TYPE, channel_id: str) -> bool:
    bot = context.bot
    user_id = update.effective_user.id

    try:
        admins = await bot.get_chat_administrators(chat_id=channel_id)
    except Exception as e:
        await update.message.reply_text(f"❌ Channel not found or inaccessible: {e}")
        return False

    # Check if bot is admin
    bot_is_admin = any(admin.user.id == bot.id and admin.status in ["administrator", "creator"] for admin in admins)
    if not bot_is_admin:
        await update.message.reply_text("❌ Bot is not admin in the channel. Please add bot as admin first.")
        return False

    # Check if user is admin
    user_is_admin = any(admin.user.id == user_id and admin.status in ["administrator", "creator"] for admin in admins)
    if not user_is_admin:
        await update.message.reply_text("❌ You are not admin in the channel. Only admins can set the channel.")
        return False

    return True

async def set_caption(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        user_id = update.effective_user.id

        if not is_authorized(user_id):
            await update.effective_message.reply_text("𝖮𝗈𝗆𝖻𝗎𝗎𝗎 😭")
            return

        # Set user state to waiting for caption
        USER_STATE[user_id] = {"status": "waiting_caption"}

        await update.effective_message.reply_text(
            "📝 <b>Caption Time!</b>\n"
            "Send me your Caption including ⬇️\n"
            "The placeholder <code>Key -</code> 🔑",
            parse_mode="HTML"
        )

    except Exception as e:
        await notify_owner_on_error(context.bot, e, source="set_caption")
        
async def user_viewsetup(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        user_id = update.effective_user.id
        if not is_authorized(user_id):
            await update.message.reply_text("⛔ Unauthorized Access.")
            return

        user_data = USER_DATA.get(str(user_id), {})
        channel = user_data.get("channel", "Not Set")
        caption = user_data.get("caption", "No caption set.")
        first_seen_ts = user_data.get("first_seen", int(START_TIME))
        days_active = (time.time() - first_seen_ts) // 86400

        # Get stats
        state = USER_STATE.get(user_id, {})
        m1_apk = state.get("total_method1_apks", 0)
        m2_apk = state.get("total_method2_apks", 0)
        m1_key = state.get("total_method1_keys", 0)
        m2_key = state.get("total_method2_keys", 0)

        # Build the message
        msg = (
            "<b>🔍 𝗣𝗘𝗥𝗦𝗢𝗡𝗔𝗟 𝗦𝗘𝗧𝗨𝗣 𝗦𝗧𝗔𝗧𝗨𝗦</b>\n"
            "<blockquote>"
            "━━━━━━━━━━━━━━━━━━━━━\n"
            f"<b>🆔 User:</b> <code>{user_id}</code>\n"
            f"<b>🗓️ Active Since:</b> {int(days_active)} days\n"
            f"<b>📡 Channel:</b> <code>{channel}</code>\n"
            "━━━━━━━━━━━━━━━━━━━━━\n"
            "<b>🖋️ Saved Caption:</b>\n\n"
            f"{caption}\n"
            "━━━━━━━━━━━━━━━━━━━━━\n"
            "<b>📦 Method Stats:</b>\n"
            f"• <b>Method 1:</b> {m1_apk} APKs / {m1_key} Keys\n"
            f"• <b>Method 2:</b> {m2_apk} APKs / {m2_key} Keys\n"
            "━━━━━━━━━━━━━━━━━━━━━\n"
            "<i>✨ Stay consistent, we’re tracking your journey!</i>"
            "</blockquote>"
        )

        await update.message.reply_text(msg, parse_mode="HTML")

    except Exception as e:
        await notify_owner_on_error(context.bot, e, source="user_viewsetup")

async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        user = update.effective_user
        user_id = user.id
        msg = update.message

        if str(user_id) not in USER_DATA:
            USER_DATA[str(user_id)] = {
                "first_name": user.first_name,
                "username": user.username,
            }
            save_config()

        # --- Broadcast capture for owner ---
        if user_id == OWNER_ID and BROADCAST_SESSION.get(user_id, {}).get("waiting_for_message"):

            # Handle button input in caption
            if msg.caption and "|" in msg.caption and "http" in msg.caption:
                BROADCAST_SESSION[user_id]["buttons_raw"] = msg.caption
                await msg.reply_text("✅ Buttons received. Now confirm broadcast or send new media.")
                return

            # Check photo present
            if not msg.photo:
                await msg.reply_text("❌ No photo found.")
                return

            # Set message and close session
            BROADCAST_SESSION[user_id]["message"] = msg
            BROADCAST_SESSION[user_id]["waiting_for_message"] = False

            preview_keyboard = InlineKeyboardMarkup([
                [InlineKeyboardButton("✅ Confirm", callback_data="confirm_broadcast"),
                 InlineKeyboardButton("❌ Cancel", callback_data="cancel_broadcast")]
            ])

            # Escape caption safely
            safe_caption = escape(msg.caption or "🖼️ Image received.")

            await context.bot.send_photo(
                chat_id=user_id,
                photo=msg.photo[-1].file_id,
                caption=safe_caption,
                parse_mode="HTML",
                reply_markup=preview_keyboard
            )
            return

    except Exception as e:
        await notify_owner_on_error(context.bot, e, source="handle_photo")

async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        user = update.effective_user
        user_id = user.id
        message = update.message
        document = message.document
        file_name = document.file_name or ""

        if not document:
            await message.reply_text("❌ No document found in this message.")
            return

        # --- Save user if new (for broadcast) ---
        if str(user_id) not in USER_DATA:
            USER_DATA[str(user_id)] = {
                "first_name": user.first_name,
                "username": user.username,
            }
            save_config()

        # --- 📢 Owner Broadcast Capture ---
        if user_id == OWNER_ID and BROADCAST_SESSION.get(user_id, {}).get("waiting_for_message"):
            msg = update.message

            if msg.caption and "|" in msg.caption and "http" in msg.caption:
                BROADCAST_SESSION[user_id]["buttons_raw"] = msg.caption
                await msg.reply_text("✅ Buttons received. Ready to confirm.")
                return

            BROADCAST_SESSION[user_id]["message"] = msg
            BROADCAST_SESSION[user_id]["waiting_for_message"] = False

            preview_keyboard = InlineKeyboardMarkup([
                [InlineKeyboardButton("✅ Confirm", callback_data="confirm_broadcast"),
                 InlineKeyboardButton("❌ Cancel", callback_data="cancel_broadcast")]
            ])

            buttons_raw = BROADCAST_SESSION[user_id].get("buttons_raw")
            keyboard = parse_buttons_grid_2x2(buttons_raw) if buttons_raw else None

            safe_caption = escape((msg.caption or "📄 Document received.")[:1000])

            await context.bot.send_document(
                chat_id=user_id,
                document=msg.document.file_id,
                caption=safe_caption,
                parse_mode="HTML",
                reply_markup=preview_keyboard
            )
            return

        # --- ❌ Unauthorized User ---
        if not is_authorized(user_id):
            await message.reply_text(
                "⛔️ <b>Unauthorized Access</b>\n"
                "━━━━━━━━━━━━━━━━━━━━━━\n"
                "You are not whitelisted to use this system.\n"
                "Access is restricted to approved users only.\n\n"
                "📩 <b>Request Access:</b> <a href='https://t.me/Ceo_DarkFury'>@Ceo_DarkFury</a>\n"
                "🛡️ <i>Your activity has been logged.</i>\n"
                "━━━━━━━━━━━━━━━━━━━━━━\n"
                "🧠 <b>Secure Systems by:</b> <a href='https://t.me/Ceo_DarkFury'>@Ceo_DarkFury</a>",
                parse_mode="HTML",
                disable_web_page_preview=True
            )
            return

        # --- 🗂️ Restore ZIP Upload (Owner Only) ---
        if user_id == OWNER_ID and USER_STATE.get(user_id, {}).get("awaiting_zip"):
            if not file_name.endswith(".zip"):
                await message.reply_text("❌ Only .zip files are accepted for restore.")
                return

            USER_STATE[user_id]["pending_restore_file"] = document
            USER_STATE[user_id]["awaiting_zip"] = False

            await message.reply_text(
                "⚠️ You uploaded a backup ZIP file.\nConfirm restore?",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("✅ Confirm Restore", callback_data="confirm_restore")],
                    [InlineKeyboardButton("❌ Cancel", callback_data="settings_back")]
                ])
            )
            return

        # --- ❌ Invalid File Type ---
        if not file_name.lower().endswith(".apk"):
            await message.reply_text(
                f"⛔️ <b>ACCESS DENIED: Invalid File Detected</b>\n"
                f"━━━━━━━━━━━━━━━━━━━━━━━\n"
                f"This system accepts <b>APK</b> files only.\n"
                f"Your submission has been rejected.\n\n"
                f"📄 <b>File Name:</b> <code>{file_name}</code>\n"
                f"📦 <b>Allowed Format:</b> .apk\n"
                f"🚫 <b>Status:</b> Rejected\n"
                f"━━━━━━━━━━━━━━━━━━━━━━━\n"
                f"🛡️ <i>This action has been logged for security review.</i>\n"
                f"🧠 <b>Powered & Secured by:</b> <a href='https://t.me/Ceo_DarkFury'>@Ceo_DarkFury</a>",
                parse_mode="HTML",
                disable_web_page_preview=True
            )
            return

        # --- ⚙️ Check Method Selected ---
        state = USER_STATE.get(user_id)
        if not state or not state.get("current_method"):
            keyboard = [[InlineKeyboardButton("⚡ Choose Method", callback_data="back_to_methods")]]
            await message.reply_text(
                "⚠️ *You didn't select any Method yet!*\n\n"
                "Please select Method 1 or Method 2 first.",
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
            return

        # --- Route APK by Method ---
        method = state.get("current_method")
        if method == "method1":
            await process_method1_apk(update, context)
        elif method == "method2":
            await process_method2_apk(update, context)

    except Exception as e:
        await notify_owner_on_error(context.bot, e, source="handle_document")

async def process_method1_apk(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        user_id = update.effective_user.id
        doc = update.message.document
        caption = update.message.caption or ""

        key = None

        # Try regex extraction
        match = re.search(r'Key\s*-\s*(\S+)', caption)
        if match:
            key = match.group(1)

        # Try code entity fallback
        if not key and update.message.caption_entities:
            for entity in update.message.caption_entities:
                if entity.type == "code":
                    offset = entity.offset
                    length = entity.length
                    key = caption[offset:offset + length]
                    break

        # Ask for key if still missing
        if not key:
            USER_STATE.setdefault(user_id, {})
            USER_STATE[user_id]["waiting_key"] = True
            USER_STATE[user_id]["file_id"] = doc.file_id
            await update.message.reply_text(
                text=(
                    "<blockquote>"
                    "<b>▌𝐌𝐄𝐓𝐇𝐎𝐃 𝟏 𝐒𝐘𝐒𝐓𝐄𝐌𝐒 ▌</b>\n"
                    "▶<b>𝐒𝐞𝐧𝐝 𝐲𝐨𝐮𝐫 𝐊𝐞𝐲 𝐍𝐨𝐰</b>\n"
                    "▶<i>𝐔𝐬𝐚𝐠𝐞 𝐟𝐨𝐫 𝐌𝐨𝐝𝐬 , 𝐋𝐨𝐚𝐝𝐞𝐫𝐬</i>\n"
                    "────────────────────"
                    "</blockquote>"
                ),
                parse_mode="HTML"
            )
            return

        # Check user setup
        user_info = USER_DATA.get(str(user_id), {})
        saved_caption = user_info.get("caption", "")
        channel_id = user_info.get("channel", "")

        if not saved_caption or not channel_id:
            await update.message.reply_text(
                "⚠️ <b>Please setup your Channel and Caption first!</b>",
                parse_mode="HTML"
            )
            return

        # Format caption with key
        final_caption = saved_caption.replace("Key -", f"Key - <code>{key}</code>")

        # Store pending APK
        USER_STATE.setdefault(user_id, {})
        USER_STATE[user_id]["pending_apk"] = {
            "file_id": doc.file_id,
            "caption": final_caption,
            "channel": channel_id,
            "confirm_message_id": update.message.message_id
        }

        await ask_to_share(update, context)

    except Exception as e:
        await notify_owner_on_error(context.bot, e, source="process_method1_apk")

async def ask_to_share(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        keyboard = [
            [
                InlineKeyboardButton("🚀 YES, Post It!", callback_data="share_yes"),
                InlineKeyboardButton("❌ Cancel", callback_data="share_no")
            ]
        ]

        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text=(
                "<b>┌─[ 𝐏𝐎𝐒𝐓 𝐂𝐎𝐍𝐅𝐈𝐑𝐌𝐀𝐓𝐈𝐎𝐍 ]</b>\n"
                "<blockquote>"
                "│<b>𝖱𝖾𝖺𝖽𝗒 𝗍𝗈 𝗌𝗁𝖺𝗋𝖾 𝗒𝗈𝗎𝗋 𝖼𝗈𝗇𝗍𝖾𝗇𝗍?</b>\n"
                "│ \n"
                "│ <b>▶ If yes, it will be posted now.</b>\n"
                "│ <b>▶ If no, it will be discarded.</b>\n"
                "└──────────────────────────"
                "</blockquote>"
            ),
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )

    except Exception as e:
        await notify_owner_on_error(context.bot, e, source="ask_to_share")

async def process_method2_apk(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        user_id = update.effective_user.id
        doc = update.message.document
        file_id = doc.file_id
        file_name = doc.file_name or ""
    
        state = USER_STATE.setdefault(user_id, {})
    
        # Cancel old countdown task if key was pending
        if state.get("waiting_key"):
            task = state.get("countdown_task")
            if task and not task.done():
                task.cancel()
    
            state.update({
                "session_files": [],
                "session_filenames": [],
                "saved_key": None,
                "waiting_key": False,
                "quote_applied": False,
                "mono_applied": False,
                "progress_message_id": None,
                "key_prompt_sent": False,
                "countdown_msg_id": None,
                "countdown_task": None
            })
    
        session_files = state.setdefault("session_files", [])
        session_filenames = state.setdefault("session_filenames", [])
    
        # Handle overflow (start a new session if more than 3)
        if len(session_files) >= 3:
            task = state.get("countdown_task")
            if task and not task.done():
                task.cancel()
    
            session_files.clear()
            session_filenames.clear()
            state.update({
                "saved_key": None,
                "waiting_key": False,
                "key_prompt_sent": False,
                "countdown_msg_id": None,
                "countdown_task": None
            })
    
        # Append the new APK
        session_files.append(file_id)
        session_filenames.append(file_name)
    
        # Update tracking info
        state["last_apk_time"] = time.time()
        state["last_method"] = "Method 2"
        state["last_style"] = state.get("key_mode", "normal")
        state["last_used_time"] = time.time()
    
        # Prompt for key if 3 APKs received
        if len(session_files) >= 3 and not state.get("waiting_key") and not state.get("key_prompt_sent"):
            task = state.get("countdown_task")
            if task and not task.done():
                task.cancel()
    
            if state.get("countdown_msg_id"):
                try:
                    await context.bot.delete_message(chat_id=user_id, message_id=state["countdown_msg_id"])
                except:
                    pass
    
            state.update({
                "waiting_key": True,
                "key_prompt_sent": True,
                "countdown_msg_id": None,
                "countdown_task": None
            })
    
            await context.bot.send_message(
                chat_id=user_id,
                text=(
                    "<blockquote>"
                    "▌ 𝐌𝐄𝐓𝐇𝐎𝐃 𝟐 𝐒𝐘𝐒𝐓𝐄𝐌 ▌\n"
                    "▶ Send your Key Now\n"
                    "▶ Used for all Mods , Loaders\n"
                    "────────────────────"
                    "</blockquote>"
                ),
                parse_mode="HTML"
            )
            return
    
        # Cancel existing countdown task if running
        task = state.get("countdown_task")
        if task and not task.done():
            try:
                task.cancel()
            except Exception as e:
                print(f"[Countdown Cancel Error] User: {user_id} | {e}")
        
        # Start new countdown task
        new_task = asyncio.create_task(start_method2_countdown(user_id, context))
        state["countdown_task"] = new_task

    except Exception as e:
        await notify_owner_on_error(context.bot, e, source="process_method2_apk")

async def start_method2_countdown(user_id: int, context: ContextTypes.DEFAULT_TYPE):
    try:
        state = USER_STATE[user_id]
        chat_id = user_id
        filenames = state.get("session_filenames", [])
        file_ids = state.get("session_files", [])
        channel = USER_DATA.get(str(user_id), {}).get("channel", "@NotSet")

        # Track countdown timing
        start_time = time.time()
        prev_start = state.get("countdown_start_time")
        elapsed = int(start_time - prev_start) if prev_start else 0
        remaining_time = max(10 - elapsed, 10)
        state["countdown_start_time"] = start_time

        # Build list of captured APKs
        apk_lines = []
        for idx, (name, fid) in enumerate(zip(filenames, file_ids), start=1):
            try:
                file_info = await context.bot.get_file(fid)
                size = round(file_info.file_size / (1024 * 1024), 2)
                size_str = f"{size} MB" if size < 1024 else f"{round(size / 1024, 2)} GB"
            except:
                size_str = "— MB"
            apk_lines.append(f"➤ {idx}. {name} ({size_str})")

        apk_list = "\n".join(apk_lines) if apk_lines else "➤ No APKs yet."

        # Dynamic button text based on the number of APKs
        apk_count = len(filenames)
        confirm_text = f"✅ Confirm {apk_count} APK" if apk_count == 1 else f"✅ Confirm {apk_count} APKs"

        # Buttons for user actions
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton(confirm_text, callback_data="method2_confirm_apks"),
             InlineKeyboardButton("Erase all 🔖", callback_data="method2_cancel_session")]
        ])

        # Countdown message builder (Style 40)
        def build_message(sec):
            bar = "".join("⣿" if i < sec else "⠂" for i in range(10))
            return (
                f"<b>☑ M2 :: DEPLOYMENT STATUS</b>\n"
                f"<blockquote>"
                f"➤ Current Files: <b>{len(filenames)}/3</b>\n"
                f"{apk_list}\n\n"
                f"⏳ Sync Window: <b>{sec} sec</b>\n"
                f"{bar}\n\n"
                f"➜ File expected\n"
                f"➜ Or key to continue"
                f"</blockquote>"
            )

        # Send the initial message
        try:
            sent = await context.bot.send_message(
                chat_id,
                text=build_message(remaining_time),
                parse_mode="HTML",
                reply_markup=keyboard
            )
        except Exception as e:
            print(f"[Countdown Send Error] User: {user_id} | {e}")
            return

        state["countdown_msg_id"] = sent.message_id

        # Countdown loop
        for sec in range(remaining_time - 1, -1, -1):
            await asyncio.sleep(1)

            if not state.get("countdown_msg_id"):
                return

            try:
                await context.bot.edit_message_text(
                    chat_id=chat_id,
                    message_id=sent.message_id,
                    text=build_message(sec),
                    parse_mode="HTML",
                    reply_markup=keyboard
                )
            except:
                pass

            if len(state["session_files"]) >= 3:
                break

        # Delete countdown display
        try:
            await context.bot.delete_message(chat_id, sent.message_id)
        except:
            pass

        state["countdown_msg_id"] = None
        state["countdown_task"] = None
        state["waiting_key"] = True

        # Key input prompt message
        await context.bot.send_message(
            chat_id=user_id,
            text=(
                "<b>▌ METHOD 2 SYSTEM ▌</b>\n"
                "<blockquote>"
                "▶ Send your Key now\n"
                "▶ Applies to all Mods / Loaders\n"
                "────────────────────"
                "</blockquote>"
            ),
            parse_mode="HTML"
        )

    except Exception as e:
        await notify_owner_on_error(context.bot, e, source="start_method2_countdown")

async def method2_send_to_channel(user_id, context):
    try:
        user_info = USER_DATA.get(str(user_id), {})
        channel_id = user_info.get("channel")
        saved_caption = user_info.get("caption")
        state = USER_STATE.setdefault(user_id, {})
    
        session_files = state.get("session_files", [])
        session_filenames = state.get("session_filenames", [])
        key = state.get("saved_key", "")
        key_mode = state.get("key_mode", "normal")
    
        if not channel_id or not saved_caption or not session_files or not key:
            await context.bot.send_message(
                chat_id=user_id,
                text="❌ <b>Session Data Missing! Please /start again.</b>",
                parse_mode="HTML"
            )
            return
    
        # Auto-reset previous post data to avoid old delete targets
        state["apk_posts"] = []
        state["last_post_session"] = {}

        posted_ids = []
        last_message = None

        for idx, file_id in enumerate(session_files, start=1):
            is_last_apk = (idx == len(session_files))

            # Build caption based on key mode
            if key_mode == "quote":
                caption = (
                    saved_caption.replace("Key -", f"<blockquote>Key - <code>{key}</code></blockquote>")
                    if is_last_apk or len(session_files) == 1
                    else f"<blockquote>Key - <code>{key}</code></blockquote>"
                )
            elif key_mode == "mono":
                caption = (
                    saved_caption.replace("Key -", f"Key - <code>{key}</code>")
                    if is_last_apk or len(session_files) == 1
                    else f"Key - <code>{key}</code>"
                )
            else:
                caption = (
                    saved_caption.replace("Key -", f"Key - {key}")
                    if is_last_apk or len(session_files) == 1
                    else f"Key - {key}"
                )

            sent_message = await context.bot.send_document(
                chat_id=channel_id,
                document=file_id,
                caption=caption,
                parse_mode="HTML"
            )
            posted_ids.append(sent_message.message_id)
            last_message = sent_message

        if not posted_ids:
            await context.bot.send_message(
                chat_id=user_id,
                text="⚠️ No APKs were posted. Try again or /reset.",
                parse_mode="HTML"
            )
            return
        
        # New CEO-level tracking system
        update_user_stats(user_id, method="method2", apks=len(posted_ids), keys=1)
        save_state()

        # Build post link
        post_link = "Unknown"
        if last_message:
            if str(channel_id).startswith("@"):
                post_link = f"https://t.me/{channel_id.strip('@')}/{last_message.message_id}"
            elif str(channel_id).startswith("-100"):
                post_link = f"https://t.me/c/{channel_id.replace('-100', '')}/{last_message.message_id}"
            state["last_post_link"] = post_link

        # Save session details
        state["last_post_session"] = {
            "file_ids": session_files.copy(),
            "filenames": session_filenames.copy(),
            "key": key,
            "key_mode": key_mode,
            "caption_template": saved_caption,
            "channel_id": channel_id,
            "post_message_ids": posted_ids
        }
        
       # Store message IDs for deletion panel
        USER_STATE[user_id]["apk_posts"] = posted_ids

        # Reset session
        state.update({
            "session_files": [],
            "session_filenames": [],
            "saved_key": None,
            "waiting_key": False,
            "key_prompt_sent": False,
            "quote_applied": False,
            "mono_applied": False,
            "last_apk_time": None,
            "key_mode": "normal",
            "countdown_msg_id": None,
            "countdown_task": None
        })

        # Styled CEO summary output
        apk_quotes = "\n".join([f"{i+1}. “<b>{name}</b>”" for i, name in enumerate(session_filenames[:3])])
        
        if key_mode == "quote":
            key_line = f"<blockquote>🔐 Key - <code>{key}</code></blockquote>"
        elif key_mode == "mono":
            key_line = f"🔐 Key - <code>{key}</code>"
        else:
            key_line = f"🔐 Key - {key}"
        
        summary = (
            "<b>𝗖𝗵𝗮𝗻𝗻𝗲𝗹 𝗣𝗼𝘀𝘁𝗲𝗱 𝗜𝗻𝗳𝗼 💀</b>\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            f"<pre>{apk_quotes}</pre>\n\n"
            f"{key_line}\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            "<i>𝚂𝚎𝚕𝚎𝚌𝚝 𝚊𝚗𝚢 𝚋𝚎𝚕𝚘𝚠</i>\n"
            "<i>𝚖𝚘𝚛𝚎 𝚏𝚎𝚊𝚝𝚞𝚛𝚎𝚜 𝚑𝚎𝚛𝚎 🔖</i>"
        )

        # Build inline buttons
        buttons = [[InlineKeyboardButton("📄 View Posted APK", url=post_link)]]
        
        if len(posted_ids) >= 2:
            buttons.append([
                InlineKeyboardButton("✏️ Add Key to All", callback_data="auto_recaption"),
                InlineKeyboardButton("✨ Add Key to Last", callback_data="auto_last_caption")
            ])
            buttons.append([
                InlineKeyboardButton("🔑 Key as Full Caption", callback_data="last_caption_key"),
                InlineKeyboardButton("🪄 Key Only on Last APK", callback_data="key_after_apks")
            ])
            buttons.append([
                InlineKeyboardButton("🧷 Add Key to End of Caption", callback_data="caption_plus_key")
            ])
        
        buttons.append([
            InlineKeyboardButton("🗑️ Delete This Post", callback_data="delete_apk_post"),
            InlineKeyboardButton("🧹 Clear Session", callback_data="erase_all")
        ])
        buttons.append([
            InlineKeyboardButton("🔙 Back to Upload Options", callback_data="back_to_methods")
        ])

        # Edit preview message if possible
        preview_id = state.get("preview_message_id")
        if preview_id:
            try:
                await context.bot.edit_message_text(
                    chat_id=user_id,
                    message_id=preview_id,
                    text=summary,
                    parse_mode="HTML",
                    reply_markup=InlineKeyboardMarkup(buttons)
                )
            except:
                pass

    except Exception as e:
        await notify_owner_on_error(context.bot, e, source="method2_send_to_channel")

async def method2_convert_quote(user_id, context: ContextTypes.DEFAULT_TYPE):
    try:
        state = USER_STATE.get(user_id, {})
        preview_message_id = state.get("preview_message_id")
        key = state.get("saved_key", "")
        session_files = state.get("session_files", [])
        session_filenames = state.get("session_filenames", [])
    
        if not preview_message_id or not key or not session_files:
            await context.bot.send_message(
                chat_id=user_id,
                text="⚠️ <b>No active APK session found!</b>",
                parse_mode="HTML"
            )
            return
    
        # Apply quote key style
        USER_STATE[user_id]["quote_applied"] = True
        USER_STATE[user_id]["key_mode"] = "quote"  # update key_mode to reflect change
    
        # Build preview message like show_preview
        preview_text = "<b>𝗤𝗨𝗢𝗧𝗘 𝗞𝗘𝗬 𝗜𝗡𝗙𝗢 📝</b>\n<pre>"
    
        for idx, (file_id, file_name) in enumerate(zip(session_files, session_filenames), start=1):
            try:
                file_info = await context.bot.get_file(file_id)
                file_size = round(file_info.file_size / (1024 * 1024), 2)
            except Exception as e:
                print(f"Failed to fetch file size: {e}")
                file_size = "?"
    
            preview_text += f"{idx}. {file_name} [{file_size} MB]\n"
    
        preview_text += "</pre>\n"
        preview_text += f"<blockquote>🔐 Key - <code>{key}</code></blockquote>"
    
        # Inline keyboard copied from show_preview
        keyboard = [
            [
                InlineKeyboardButton("✅ Send to Channel", callback_data="method2_yes"),
                InlineKeyboardButton("❌ Cancel Upload", callback_data="method2_no")
            ],
            [
                InlineKeyboardButton("✍️ Add Quote Style", callback_data="method2_quote"),
                InlineKeyboardButton("🔤 Add Mono Style", callback_data="method2_mono")
            ],
            [
                InlineKeyboardButton("📝 Edit Caption", callback_data="method2_edit"),
                InlineKeyboardButton("👁️ Preview Before Posting", callback_data="method2_preview")
            ],
            [
                InlineKeyboardButton("🧹 Clear all", callback_data="erase_all_session")
            ]
        ]
    
        try:
            await context.bot.edit_message_text(
                chat_id=user_id,
                message_id=preview_message_id,
                text=preview_text,
                parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
        except Exception as e:
            print(f"Error converting to quote style: {e}")

    except Exception as e:
        await notify_owner_on_error(context.bot, e, source="method2_convert_quote")

async def method2_convert_mono(user_id, context: ContextTypes.DEFAULT_TYPE):
    try:
        state = USER_STATE.get(user_id, {})
        preview_message_id = state.get("preview_message_id")
        key = state.get("saved_key", "")
        session_files = state.get("session_files", [])
        session_filenames = state.get("session_filenames", [])
    
        if not preview_message_id or not key or not session_files:
            await context.bot.send_message(
                chat_id=user_id,
                text="⚠️ <b>No active APK session found!</b>",
                parse_mode="HTML"
            )
            return
    
        # Apply mono key style
        USER_STATE[user_id]["mono_applied"] = True
        USER_STATE[user_id]["key_mode"] = "mono"  # update key_mode to reflect change
    
        # Build preview message like show_preview
        preview_text = "<b>𝗠𝗢𝗡𝗢 𝗞𝗘𝗬 𝗜𝗡𝗙𝗢 🏆</b>\n<pre>"
    
        for idx, (file_id, file_name) in enumerate(zip(session_files, session_filenames), start=1):
            try:
                file_info = await context.bot.get_file(file_id)
                file_size = round(file_info.file_size / (1024 * 1024), 2)
            except Exception as e:
                print(f"Failed to fetch file size: {e}")
                file_size = "?"
    
            preview_text += f"{idx}. {file_name} [{file_size} MB]\n"
    
        preview_text += "</pre>\n"
        preview_text += f"🔐 Key - <code>{key}</code>"
    
        # Inline keyboard copied from show_preview
        keyboard = [
            [
                InlineKeyboardButton("✅ Send to Channel", callback_data="method2_yes"),
                InlineKeyboardButton("❌ Cancel Upload", callback_data="method2_no")
            ],
            [
                InlineKeyboardButton("✍️ Add Quote Style", callback_data="method2_quote"),
                InlineKeyboardButton("🔤 Add Mono Style", callback_data="method2_mono")
            ],
            [
                InlineKeyboardButton("📝 Edit Caption", callback_data="method2_edit"),
                InlineKeyboardButton("👁️ Preview Before Posting", callback_data="method2_preview")
            ],
            [
                InlineKeyboardButton("🧹 Clear all", callback_data="erase_all_session")
            ]
        ]
    
        try:
            await context.bot.edit_message_text(
                chat_id=user_id,
                message_id=preview_message_id,
                text=preview_text,
                parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
        except Exception as e:
            print(f"Error converting to mono style: {e}")

    except Exception as e:
        await notify_owner_on_error(context.bot, e, source="method2_convert_mono")

async def method2_edit_caption(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        user_id = update.effective_user.id
        new_caption = update.message.text.strip()
    
        if "Key -" not in new_caption:
            await update.message.reply_text(
                "❌ *Invalid Caption!*\n\nMust contain `Key -` placeholder.",
                parse_mode="Markdown"
            )
            return
    
        # Save the new caption
        USER_DATA[str(user_id)] = USER_DATA.get(str(user_id), {})
        USER_DATA[str(user_id)]["caption"] = new_caption
        save_config()
    
        USER_STATE[user_id]["status"] = "normal"
        USER_STATE[user_id]["quote_applied"] = False
        USER_STATE[user_id]["mono_applied"] = False
    
        preview_message_id = USER_STATE.get(user_id, {}).get("preview_message_id")
        key = USER_STATE.get(user_id, {}).get("saved_key", "")
        session_files = USER_STATE.get(user_id, {}).get("session_files", [])
        key_mode = USER_STATE.get(user_id, {}).get("key_mode", "normal")
    
        if not preview_message_id or not key or not session_files:
            await update.message.reply_text(
                "⚠️ *No active session found!*",
                parse_mode="Markdown"
            )
            return
    
        # Escape user caption
        safe_caption = escape(new_caption)
    
        # Inject key using correct mode
        if key_mode == "quote":
            key_display = f"<blockquote>🔐 Key - <code>{key}</code></blockquote>"
        elif key_mode == "mono":
            key_display = f"🔐 Key - <code>{key}</code>"
        else:
            key_display = f"🔐 Key - {key}"
    
        # Compose message
        text = f"<b>𝗖𝗔𝗣𝗧𝗜𝗢𝗡 𝗨𝗣𝗗𝗔𝗧𝗘𝗗 📝</b>\n\n"
        text += f"{safe_caption}\n\n{key_display}"
    
        # Inline "Back" button
        buttons = [[InlineKeyboardButton("🔙 Back", callback_data="method2_back_fullmenu")]]
    
        # Delete old preview message
        try:
            await context.bot.delete_message(chat_id=user_id, message_id=preview_message_id)
        except Exception as e:
            print(f"Failed to delete old preview message: {e}")
    
        # Send updated message with inline keyboard
        new_msg = await context.bot.send_message(
            chat_id=user_id,
            text=text,
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(buttons)
        )
    
        # Update message ID in session
        USER_STATE[user_id]["preview_message_id"] = new_msg.message_id

    except Exception as e:
        await notify_owner_on_error(context.bot, e, source="method2_edit_caption")

async def method2_show_preview(user_id, context):
    try:
        user_state = USER_STATE.get(user_id, {})
        session_files = user_state.get("session_files", [])
        session_filenames = user_state.get("session_filenames", [])
        key = user_state.get("saved_key", "")
        key_mode = user_state.get("key_mode", "normal")
        saved_caption = USER_DATA.get(str(user_id), {}).get("caption", "")
    
        if not session_files or not key:
            await context.bot.send_message(
                chat_id=user_id,
                text="⚠️ <b>No active APK session found!</b>",
                parse_mode="HTML"
            )
            return
    
        # Begin terminal preview
        preview_text = "<b>𝗣𝗥𝗘𝗩𝗜𝗘𝗪 𝗜𝗡𝗙𝗢 📃</b>\n<pre>"
    
        for idx, (file_id, file_name) in enumerate(zip(session_files, session_filenames), start=1):
            try:
                file_info = await context.bot.get_file(file_id)
                file_size = round(file_info.file_size / (1024 * 1024), 2)
            except Exception as e:
                print(f"Failed to fetch file size: {e}")
                file_size = "?"
    
            preview_text += f"{idx}. {file_name} [{file_size} MB]\n"
    
        preview_text += "</pre>\n"
    
        # Append key in the selected style
        if key_mode == "quote":
            preview_text += f"<blockquote>🔐 Key - <code>{key}</code></blockquote>"
        elif key_mode == "mono":
            preview_text += f"🔐 Key - <code>{key}</code>"
        else:
            preview_text += f"🔐 Key - {key}"
    
        # Inline keyboard
        keyboard = [
            [
                InlineKeyboardButton("✅ Send to Channel", callback_data="method2_yes"),
                InlineKeyboardButton("❌ Cancel Upload", callback_data="method2_no")
            ],
            [
                InlineKeyboardButton("✍️ Add Quote Style", callback_data="method2_quote"),
                InlineKeyboardButton("🔤 Add Mono Style", callback_data="method2_mono")
            ],
            [
                InlineKeyboardButton("📝 Edit Caption", callback_data="method2_edit"),
                InlineKeyboardButton("👁️ Preview Before Posting", callback_data="method2_preview")
            ],
            [
                InlineKeyboardButton("🧹 Clear all", callback_data="erase_all_session")
            ]
        ]
    
        try:
            await context.bot.edit_message_text(
                chat_id=user_id,
                message_id=user_state.get("preview_message_id"),
                text=preview_text,
                parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
        except Exception as e:
            print(f"Error in showing preview: {e}")

    except Exception as e:
        await notify_owner_on_error(context.bot, e, source="method2_show_preview")

def build_method2_buttons(user_id):
    buttons = [
        [
            InlineKeyboardButton("✅ Send to Channel", callback_data="method2_yes"),
            InlineKeyboardButton("❌ Cancel Upload", callback_data="method2_no")
        ],
        [
            InlineKeyboardButton("✍️ Add Quote Style", callback_data="method2_quote"),
            InlineKeyboardButton("🔤 Add Mono Style", callback_data="method2_mono")
        ],
        [
            InlineKeyboardButton("📝 Edit Caption", callback_data="method2_edit"),
            InlineKeyboardButton("👁️ Preview Before Posting", callback_data="method2_preview")
        ],
        [
            InlineKeyboardButton("🧹 Clear all", callback_data="erase_all_session")
        ]
    ]

    return InlineKeyboardMarkup(buttons)

async def method2_back_fullmenu(user_id, context):
    try:
        state = USER_STATE.get(user_id, {})
        preview_message_id = state.get("preview_message_id")
        key = state.get("saved_key", "N/A")
    
        text = (
            f"<pre>"
            f"▌ 𝗦𝗘𝗦𝗦𝗜𝗢𝗡 𝗠𝗘𝗡𝗨 ▌\n"
            f"▶ Saved Key: {key}\n"
            f"▶ Choose what to do next with your APKs:\n"
            f"────────────────────"
            f"</pre>"
        )
    
        reply_markup = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("✅ Send to Channel", callback_data="method2_yes"),
                InlineKeyboardButton("❌ Cancel Upload", callback_data="method2_no")
            ],
            [
                InlineKeyboardButton("✍️ Add Quote Style", callback_data="method2_quote"),
                InlineKeyboardButton("🔤 Add Mono Style", callback_data="method2_mono")
            ],
            [
                InlineKeyboardButton("📝 Edit Caption", callback_data="method2_edit"),
                InlineKeyboardButton("👁️ Preview Before Posting", callback_data="method2_preview")
            ],
            [
                InlineKeyboardButton("🧹 Clear all", callback_data="erase_all_session")
            ]
        ])
    
        try:
            if preview_message_id:
                await context.bot.edit_message_text(
                    chat_id=user_id,
                    message_id=preview_message_id,
                    text=text,
                    parse_mode="HTML",
                    reply_markup=reply_markup
                )
            else:
                raise telegram.error.BadRequest("No preview_message_id")
    
        except telegram.error.BadRequest as e:
            if "message is not modified" in str(e).lower() or "message to edit not found" in str(e).lower():
                sent = await context.bot.send_message(
                    chat_id=user_id,
                    text=text,
                    parse_mode="HTML",
                    reply_markup=reply_markup
                )
                state["preview_message_id"] = sent.message_id
            else:
                raise

    except Exception as e:
        await notify_owner_on_error(context.bot, e, source="method2_back_fullmenu")

async def auto_recaption(user_id, context):
    try:
        state = USER_STATE.get(user_id, {})
        session = state.get("last_post_session", {})
    
        file_ids = session.get("file_ids")
        filenames = session.get("filenames", [])
        key = session.get("key")
        key_mode = session.get("key_mode", "normal")
        caption_template = session.get("caption_template", "")
        channel_id = session.get("channel_id")
        old_posts = session.get("post_message_ids", [])
        preview_message_id = state.get("preview_message_id")
    
        if not file_ids or not key or not caption_template or not channel_id:
            await context.bot.send_message(
                chat_id=user_id,
                text="⚠️ <b>Session data missing!</b> Cannot re-caption.",
                parse_mode="HTML"
            )
            return
    
        # Build media group with updated captions
        media = []
        for idx, file_id in enumerate(file_ids, start=1):
            is_last_apk = (idx == len(file_ids))
    
            if key_mode == "quote":
                caption = (
                    caption_template.replace("Key -", f"<blockquote>Key - <code>{key}</code></blockquote>")
                    if is_last_apk or len(file_ids) == 1
                    else f"<blockquote>Key - <code>{key}</code></blockquote>"
                )
            elif key_mode == "mono":
                caption = (
                    caption_template.replace("Key -", f"Key - <code>{key}</code>")
                    if is_last_apk or len(file_ids) == 1
                    else f"Key - <code>{key}</code>"
                )
            else:
                caption = (
                    caption_template.replace("Key -", f"Key - {key}")
                    if is_last_apk or len(file_ids) == 1
                    else f"Key - {key}"
                )
    
            media.append(InputMediaDocument(media=file_id, caption=caption, parse_mode="HTML"))
    
        # Send new media group
        new_posts = await context.bot.send_media_group(chat_id=channel_id, media=media)
    
        # Delete old channel messages
        for msg_id in old_posts:
            try:
                await context.bot.delete_message(chat_id=channel_id, message_id=msg_id)
            except:
                pass
    
        # Save new message IDs
        new_ids = [msg.message_id for msg in new_posts]
        last_msg = new_posts[-1]
        post_link = (
            f"https://t.me/{channel_id.strip('@')}/{last_msg.message_id}"
            if channel_id.startswith("@") else
            f"https://t.me/c/{channel_id.replace('-100', '')}/{last_msg.message_id}"
            if channel_id.startswith("-100") else
            "Unknown"
        )
    
        # Update state with new post info
        state["apk_posts"] = new_ids
        state["last_post_link"] = post_link
        state["last_post_session"]["post_message_ids"] = new_ids
    
        # Rebuild buttons
        buttons = [
            [InlineKeyboardButton("📄 Open Last Uploaded Post", url=post_link)],
            [InlineKeyboardButton("🗑️ Remove Uploaded Files", callback_data="delete_apk_post")],
            [InlineKeyboardButton("🧹 Clear This Session", callback_data="erase_all")],
            [InlineKeyboardButton("🔙 Back to Upload Options", callback_data="back_to_methods")]
        ]
    
        # Update preview message
        if preview_message_id:
            try:
                await context.bot.edit_message_text(
                    chat_id=user_id,
                    message_id=preview_message_id,
                    text="<b>𝗔𝗹𝗹 𝗔𝗣𝗞𝘀 𝗿𝗲𝗽𝗼𝘀𝘁𝗲𝗱 𝘄𝗶𝘁𝗵 𝘂𝗽𝗱𝗮𝘁𝗲𝗱 𝗸𝗲𝘆 𝗰𝗮𝗽𝘁𝗶𝗼𝗻 ☑️.</b>\n\nManage your posts below:",
                    parse_mode="HTML",
                    reply_markup=InlineKeyboardMarkup(buttons)
                )
            except Exception as e:
                print(f"Preview message update failed: {e}")
    
        # Quietly clear session state
        state.update({
            "session_files": [],
            "session_filenames": [],
            "saved_key": None,
            "waiting_key": False,
            "last_apk_time": None,
            "key_mode": "normal"
        })

    except Exception as e:
        await notify_owner_on_error(context.bot, e, source="auto_recaption")

async def auto_last_caption(user_id, context):
    try:
        state = USER_STATE.get(user_id, {})
        session = state.get("last_post_session", {})
    
        file_ids = session.get("file_ids", [])
        filenames = session.get("filenames", [])
        key = session.get("key")
        key_mode = session.get("key_mode", "normal")
        caption_template = session.get("caption_template", "")
        channel_id = session.get("channel_id")
        old_posts = session.get("post_message_ids", [])
        preview_message_id = state.get("preview_message_id")
    
        if not file_ids or not key or not caption_template or not channel_id:
            await context.bot.send_message(chat_id=user_id, text="⚠️ No session data found.")
            return
    
        # Delete old channel posts
        for msg_id in old_posts:
            try:
                await context.bot.delete_message(chat_id=channel_id, message_id=msg_id)
            except:
                pass
    
        # Build new media group with key only on last file
        media = []
        for idx, file_id in enumerate(file_ids, start=1):
            if idx == len(file_ids):  # last file only
                if key_mode == "quote":
                    caption = caption_template.replace("Key -", f"<blockquote>Key - <code>{key}</code></blockquote>")
                elif key_mode == "mono":
                    caption = caption_template.replace("Key -", f"Key - <code>{key}</code>")
                else:
                    caption = caption_template.replace("Key -", f"Key - {key}")
                media.append(InputMediaDocument(media=file_id, caption=caption, parse_mode="HTML"))
            else:
                media.append(InputMediaDocument(media=file_id))  # No caption
    
        # Send new media group
        new_posts = await context.bot.send_media_group(chat_id=channel_id, media=media)
    
        # Track new message IDs
        new_ids = [msg.message_id for msg in new_posts]
        last_msg = new_posts[-1]
        post_link = (
            f"https://t.me/{channel_id.strip('@')}/{last_msg.message_id}"
            if channel_id.startswith("@") else
            f"https://t.me/c/{channel_id.replace('-100', '')}/{last_msg.message_id}"
        )
    
        # Update state
        state["apk_posts"] = new_ids
        state["last_post_link"] = post_link
        state["last_post_session"]["post_message_ids"] = new_ids
    
        # Rebuild buttons
        buttons = [
            [InlineKeyboardButton("📄 Open Last Uploaded Post", url=post_link)],
            [InlineKeyboardButton("🗑️ Remove Uploaded Files", callback_data="delete_apk_post")],
            [InlineKeyboardButton("🧹 Clear This Session", callback_data="erase_all")],
            [InlineKeyboardButton("🔙 Back to Upload Options", callback_data="back_to_methods")]
        ]
    
        # Update preview message
        if preview_message_id:
            try:
                await context.bot.edit_message_text(
                    chat_id=user_id,
                    message_id=preview_message_id,
                    text="<b>𝗞𝗲𝘆 𝗮𝗽𝗽𝗹𝗶𝗲𝗱 𝘁𝗼 𝗹𝗮𝘀𝘁 𝗔𝗣𝗞 𝗼𝗻𝗹𝘆 📝.</b>\n\nManage your posts below:",
                    parse_mode="HTML",
                    reply_markup=InlineKeyboardMarkup(buttons)
                )
            except:
                pass
    
        # Session cleanup
        state.update({
            "session_files": [],
            "session_filenames": [],
            "saved_key": None,
            "waiting_key": False,
            "last_apk_time": None
        })

    except Exception as e:
        await notify_owner_on_error(context.bot, e, source="auto_last_caption")

async def last_caption_key(user_id, context):
    try:
        state = USER_STATE.get(user_id, {})
        session = state.get("last_post_session", {})
    
        file_ids = session.get("file_ids", [])
        channel_id = session.get("channel_id")
        key = session.get("key")
        key_mode = session.get("key_mode", "normal")
        old_posts = session.get("post_message_ids", [])
        preview_message_id = state.get("preview_message_id")
    
        if not file_ids or not key or not channel_id:
            await context.bot.send_message(chat_id=user_id, text="⚠️ No session data found.")
            return
    
        # Delete old posts
        for msg_id in old_posts:
            try:
                await context.bot.delete_message(chat_id=channel_id, message_id=msg_id)
            except:
                pass
    
        # Prepare media group with only key caption on last APK
        media = []
        for idx, file_id in enumerate(file_ids, start=1):
            if idx == len(file_ids):
                if key_mode == "quote":
                    caption = f"<blockquote>Key - <code>{key}</code></blockquote>"
                elif key_mode == "mono":
                    caption = f"Key - <code>{key}</code>"
                else:
                    caption = f"Key - {key}"
                media.append(InputMediaDocument(media=file_id, caption=caption, parse_mode="HTML"))
            else:
                media.append(InputMediaDocument(media=file_id))
    
        new_posts = await context.bot.send_media_group(chat_id=channel_id, media=media)
    
        # Update state with new post data
        new_ids = [msg.message_id for msg in new_posts]
        last_msg = new_posts[-1]
        post_link = (
            f"https://t.me/{channel_id.strip('@')}/{last_msg.message_id}"
            if channel_id.startswith("@") else
            f"https://t.me/c/{channel_id.replace('-100', '')}/{last_msg.message_id}"
        )
    
        state["apk_posts"] = new_ids
        state["last_post_link"] = post_link
        state["last_post_session"]["post_message_ids"] = new_ids
    
        # Rebuild buttons
        buttons = [
            [InlineKeyboardButton("📄 Open Last Uploaded Post", url=post_link)],
            [InlineKeyboardButton("🗑️ Remove Uploaded Files", callback_data="delete_apk_post")],
            [InlineKeyboardButton("🧹 Clear This Session", callback_data="erase_all")],
            [InlineKeyboardButton("🔙 Back to Upload Options", callback_data="back_to_methods")]
        ]
    
        # Update preview
        if preview_message_id:
            try:
                await context.bot.edit_message_text(
                    chat_id=user_id,
                    message_id=preview_message_id,
                    text="<b>𝗢𝗻𝗹𝘆 𝗸𝗲𝘆 𝗮𝗱𝗱𝗲𝗱 𝘁𝗼 𝗹𝗮𝘀𝘁 𝗔𝗣𝗞 ☑️.</b>\n\nManage your posts below:",
                    parse_mode="HTML",
                    reply_markup=InlineKeyboardMarkup(buttons)
                )
            except:
                pass
    
        # Clear temporary session values
        state.update({
            "session_files": [],
            "session_filenames": [],
            "saved_key": None,
            "waiting_key": False,
            "last_apk_time": None
        })

    except Exception as e:
        await notify_owner_on_error(context.bot, e, source="last_caption_key")

async def key_after_apks(user_id, context):
    try:
        state = USER_STATE.get(user_id, {})
        session = state.get("last_post_session", {})

        file_ids = session.get("file_ids", [])
        channel_id = session.get("channel_id")
        key = session.get("key")
        key_mode = session.get("key_mode", "normal")
        old_posts = session.get("post_message_ids", [])
        preview_message_id = state.get("preview_message_id")

        if not file_ids or not key or not channel_id:
            await context.bot.send_message(chat_id=user_id, text="⚠️ No session data found.")
            return

        # Delete previously posted messages
        for msg_id in old_posts:
            try:
                await context.bot.delete_message(chat_id=channel_id, message_id=msg_id)
            except:
                pass

        # Prepare new media group
        media = []
        for idx, file_id in enumerate(file_ids):
            if idx == len(file_ids) - 1:
                # LAST APK gets the key caption
                if key_mode == "quote":
                    caption = f"<blockquote><code>{key}</code></blockquote>"
                elif key_mode == "mono":
                    caption = f"<code>{key}</code>"
                else:
                    caption = f"{key}"

                media.append(InputMediaDocument(media=file_id, caption=caption, parse_mode="HTML"))
            else:
                media.append(InputMediaDocument(media=file_id))

        new_posts = await context.bot.send_media_group(chat_id=channel_id, media=media)

        # Update post info
        post_ids = [m.message_id for m in new_posts]
        last_msg = new_posts[-1]
        post_link = (
            f"https://t.me/{channel_id.strip('@')}/{last_msg.message_id}"
            if str(channel_id).startswith("@")
            else f"https://t.me/c/{str(channel_id).replace('-100', '')}/{last_msg.message_id}"
        )

        # Save state
        state["apk_posts"] = post_ids
        state["last_post_link"] = post_link
        session["post_message_ids"] = post_ids

        # Inline buttons
        buttons = [
            [InlineKeyboardButton("📄 Open Last Uploaded Post", url=post_link)],
            [InlineKeyboardButton("🗑️ Remove Uploaded Files", callback_data="delete_apk_post")],
            [InlineKeyboardButton("🧹 Clear This Session", callback_data="erase_all")],
            [InlineKeyboardButton("🔙 Back to Upload Options", callback_data="back_to_methods")]
        ]

        if preview_message_id:
            try:
                await context.bot.edit_message_text(
                    chat_id=user_id,
                    message_id=preview_message_id,
                    text="<b>𝗞𝗲𝘆 𝗢𝗻𝗹𝘆 𝘁𝗼 𝗹𝗮𝘀𝘁 𝗔𝗣𝗞, 𝗣𝗼𝘀𝘁𝗲𝗱 ☑️</b>\n\nManage your posts below:",
                    parse_mode="HTML",
                    reply_markup=InlineKeyboardMarkup(buttons)
                )
            except:
                pass

        # Reset session values
        state.update({
            "session_files": [],
            "session_filenames": [],
            "saved_key": None,
            "waiting_key": False,
            "last_apk_time": None
        })

    except Exception as e:
        await notify_owner_on_error(context.bot, e, source="key_after_apks")

async def caption_plus_key(user_id, context):
    try:
        state = USER_STATE.get(user_id, {})
        session = state.get("last_post_session", {})

        file_ids = session.get("file_ids", [])
        channel_id = session.get("channel_id")
        key = session.get("key")
        key_mode = session.get("key_mode", "normal")
        saved_caption = session.get("caption_template", "")
        old_posts = session.get("post_message_ids", [])
        preview_message_id = state.get("preview_message_id")

        if not file_ids or not key or not channel_id:
            await context.bot.send_message(chat_id=user_id, text="⚠️ No session data found.")
            return

        # Step 1: Delete old posts
        for msg_id in old_posts:
            try:
                await context.bot.delete_message(chat_id=channel_id, message_id=msg_id)
            except:
                pass

        # Step 2: Clean caption (remove "Key -")
        cleaned_caption = saved_caption.replace("Key -", "").strip()

        # Step 3: Build media group
        media = []
        for idx, file_id in enumerate(file_ids):
            if idx == len(file_ids) - 1:
                # Format key as per mode
                if key_mode == "quote":
                    tail = f"<blockquote><code>{key}</code></blockquote>"
                elif key_mode == "mono":
                    tail = f"<code>{key}</code>"
                else:
                    tail = f"{key}"

                final_caption = f"{tail}\n{cleaned_caption}"
                media.append(InputMediaDocument(media=file_id, caption=final_caption, parse_mode="HTML"))
            else:
                media.append(InputMediaDocument(media=file_id))

        new_posts = await context.bot.send_media_group(chat_id=channel_id, media=media)

        # Step 4: Update state
        new_ids = [msg.message_id for msg in new_posts]
        last_msg = new_posts[-1]
        post_link = (
            f"https://t.me/{channel_id.strip('@')}/{last_msg.message_id}"
            if channel_id.startswith("@") else
            f"https://t.me/c/{channel_id.replace('-100', '')}/{last_msg.message_id}"
        )

        state["apk_posts"] = new_ids
        state["last_post_link"] = post_link
        session["post_message_ids"] = new_ids

        # Step 5: Buttons
        buttons = [
            [InlineKeyboardButton("📄 Open Last Uploaded Post", url=post_link)],
            [InlineKeyboardButton("🗑️ Remove Uploaded Files", callback_data="delete_apk_post")],
            [InlineKeyboardButton("🧹 Clear This Session", callback_data="erase_all")],
            [InlineKeyboardButton("🔙 Back to Upload Options", callback_data="back_to_methods")]
        ]

        # Step 6: Preview update
        if preview_message_id:
            try:
                await context.bot.edit_message_text(
                    chat_id=user_id,
                    message_id=preview_message_id,
                    text="<b>Caption updated + Key added at Top ☑️</b>\n\nManage your posts below:",
                    parse_mode="HTML",
                    reply_markup=InlineKeyboardMarkup(buttons)
                )
            except:
                pass

        # Step 7: Clean session
        state.update({
            "session_files": [],
            "session_filenames": [],
            "saved_key": None,
            "waiting_key": False,
            "last_apk_time": None
        })

    except Exception as e:
        await notify_owner_on_error(context.bot, e, source="caption_plus_key")

def build_terminal_report(user_id: int, scope: str, label: str):
    state = USER_STATE.get(user_id, {})
    method1_apks = state.get(f"{scope}_method1_apks", 0)
    method1_keys = state.get(f"{scope}_method1_keys", 0)
    method2_apks = state.get(f"{scope}_method2_apks", 0)
    method2_keys = state.get(f"{scope}_method2_keys", 0)
    total_apks = method1_apks + method2_apks
    total_keys = method1_keys + method2_keys
    channel = USER_DATA.get(str(user_id), {}).get("channel", "—").strip("@")
    caption = "Yes" if USER_DATA.get(str(user_id), {}).get("caption") else "No"
    active = (time.time() - state.get("last_used_time", 0)) < 21600
    status = "✅ Active" if active else "⚪ Inactive"

    timestamp = datetime.now(ZoneInfo("Asia/Kolkata")).strftime("%d %b %Y, %I:%M %p")

    text = (
        f"<b>{label}</b>\n"
        f"<blockquote><b>"
        f"👤 ID: <code>{user_id}</code>\n"
        f"📡 Channel: <code>{channel}</code>\n"
        f"📝 Caption: {caption}\n"
        f"📶 Status: {status}\n\n"
        f"─────────────\n"
        f" Method 1:\n  • Apks: {method1_apks} • Keys: {method1_keys}\n\n"
        f" Method 2:\n  • Apks: {method2_apks} • Keys: {method2_keys}\n"
        f"─────────────\n"
        f"📊 Total: {total_apks} Apks, {total_keys} Keys\n\n"
        f"🕒 Generated: {timestamp}</b></blockquote>"
    )
    return text, CENTRAL_AUTHORITY_BTN

async def reset_stats(scope: str):
    for user_id in ALLOWED_USERS:
        if user_id not in USER_STATE:
            USER_STATE[user_id] = {}
        for method in ["method1", "method2"]:
            USER_STATE[user_id][f"{scope}_{method}_apks"] = 0
            USER_STATE[user_id][f"{scope}_{method}_keys"] = 0

async def schedule_stat_reports(application: Application):
    try:
        already_sent = set()
        while True:
            now = datetime.now(ZoneInfo("Asia/Kolkata"))
            tomorrow = now + timedelta(days=1)
            current_minute = f"{now.hour:02}:{now.minute:02}"

            async def send_scope(scope, label):
                for user_id in ALLOWED_USERS:
                    text, markup = build_terminal_report(user_id, scope, label)
                    try:
                        await application.bot.send_message(chat_id=user_id, text=text, parse_mode="HTML", reply_markup=markup)
                    except Exception as e:
                        await notify_owner_on_error(application.bot, e, source="send_stats")
                await reset_stats(scope)

            # 24 HOURS REPORT – Daily 10:00 AM
            if current_minute == "10:00" and "daily" not in already_sent:
                await send_scope("daily", "𝗗𝗔𝗜𝗟𝗬 𝗥𝗘𝗣𝗢𝗥𝗧")
                already_sent.add("daily")

            # 8 HOURS REPORT – 02:00 PM & 10:00 PM
            if current_minute in ["14:00", "22:00"] and current_minute not in already_sent:
                await send_scope("8hr", "𝟴 𝗛𝗢𝗨𝗥𝗦 𝗥𝗘𝗣𝗢𝗥𝗧")
                already_sent.add(current_minute)

            # WEEKLY REPORT – Sunday 10:00 AM
            if now.weekday() == 6 and current_minute == "10:00" and "weekly" not in already_sent:
                await send_scope("weekly", "𝗪𝗘𝗘𝗞𝗟𝗬 𝗥𝗘𝗣𝗢𝗥𝗧")
                already_sent.add("weekly")

            # MONTHLY REPORT – 1st of Month, 10:00 AM
            if current_minute == "10:00" and tomorrow.day == 1 and "monthly" not in already_sent:
                await send_scope("monthly", "𝗠𝗢𝗡𝗧𝗛𝗟𝗬 𝗥𝗘𝗣𝗢𝗥𝗧")
                already_sent.add("monthly")

            # Clear tracking set each minute
            if datetime.now().second < 5:
                already_sent.clear()

            await asyncio.sleep(55)

    except Exception as e:
        await notify_owner_on_error(application.bot, e, source="schedule_stat_reports")

async def test_8h(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id == OWNER_ID:
        for uid in ALLOWED_USERS:
            text, markup = build_terminal_report(uid, "8hr", "𝟴 𝗛𝗢𝗨𝗥𝗦 𝗥𝗘𝗣𝗢𝗥𝗧")
            await context.bot.send_message(chat_id=uid, text=text, parse_mode="HTML", reply_markup=markup)
        await reset_stats("8hr")

async def test_daily(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id == OWNER_ID:
        for uid in ALLOWED_USERS:
            text, markup = build_terminal_report(uid, "daily", "𝗗𝗔𝗜𝗟𝗬 𝗥𝗘𝗣𝗢𝗥𝗧")
            await context.bot.send_message(chat_id=uid, text=text, parse_mode="HTML", reply_markup=markup)
        await reset_stats("daily")

async def test_weekly(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id == OWNER_ID:
        for uid in ALLOWED_USERS:
            text, markup = build_terminal_report(uid, "weekly", "𝗪𝗘𝗘𝗞𝗟𝗬 𝗥𝗘𝗣𝗢𝗥𝗧")
            await context.bot.send_message(chat_id=uid, text=text, parse_mode="HTML", reply_markup=markup)
        await reset_stats("weekly")

async def test_monthly(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id == OWNER_ID:
        for uid in ALLOWED_USERS:
            text, markup = build_terminal_report(uid, "monthly", "𝗠𝗢𝗡𝗧𝗛𝗟𝗬 𝗥𝗘𝗣𝗢𝗥𝗧")
            await context.bot.send_message(chat_id=uid, text=text, parse_mode="HTML", reply_markup=markup)
        await reset_stats("monthly")

async def erase_all_session(user_id, context):
    try:
        state = USER_STATE.get(user_id, {})
    
        state["session_files"] = []
        state["session_filenames"] = []
        state["saved_key"] = None
        state["waiting_key"] = False
        state["key_prompt_sent"] = False
        state["last_apk_time"] = None
        state["progress_message_id"] = None
        state["countdown_msg_id"] = None
        state["quote_applied"] = False
        state["mono_applied"] = False
        state["key_mode"] = "normal"
        state["preview_message_id"] = None
        state["apk_posts"] = []
        state["last_post_link"] = None
        state["last_post_session"] = {}
    
        # Cancel countdown task if running
        countdown_task = state.get("countdown_task")
        if countdown_task and not countdown_task.done():
            countdown_task.cancel()
        state["countdown_task"] = None

    except Exception as e:
        await notify_owner_on_error(context.bot, e, source="erase_all_session")

async def settings_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        if update.effective_user.id != OWNER_ID:
            return
    
        keyboard = [
            [
                InlineKeyboardButton("➕ Add New User", callback_data="add_user"),
                InlineKeyboardButton("➖ Remove a User", callback_data="remove_user")
            ],
            [
                InlineKeyboardButton("👥 Show All Users", callback_data="view_users"),
                InlineKeyboardButton("🔧 Auto-Setup Settings", callback_data="view_autosetup")
            ],
            [
                InlineKeyboardButton("🔄 Create Backup", callback_data="backup_config")
            ],
            [
                InlineKeyboardButton("♻️ Reset Everything", callback_data="force_reset")
            ],
            [
                InlineKeyboardButton("🌟 Open Admin Channel", callback_data="bot_admin_link")
            ],
            [
                InlineKeyboardButton("🧬 Restore from Backup", callback_data="backup_restore")
            ],
            [
                InlineKeyboardButton("🧹 Reset Settings Panel", callback_data="reset_settings_panel")
            ],
            [
                InlineKeyboardButton("🔙 Return to Upload Menu", callback_data="back_to_methods")
            ]
        ]
        await update.message.reply_text(
            "🛠️ <b>Settings Panel</b>\nManage your bot below:",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )

    except Exception as e:
        await notify_owner_on_error(context.bot, e, source="settings_panel")

async def handle_settings_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        query = update.callback_query
        user_id = query.from_user.id
    
        if not is_authorized(user_id):
            await query.answer("🚫 Unauthorized", show_alert=True)
            return
    
        try:
            await query.answer()
        except:
            await query.message.reply_text("⏳ Session expired or invalid! ❌\nPlease restart using /start.")
            return
    
        data = query.data
    
        if data == "view_users":
            if not ALLOWED_USERS:
                await query.edit_message_text(
                    "❌ No allowed users found.",
                    parse_mode="HTML",
                    reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="settings_back")]])
                )
                return
    
            lines = [f"<b>🧾 Total Allowed Users:</b> {len(ALLOWED_USERS)}\n"]
    
            for index, uid in enumerate(ALLOWED_USERS, start=1):
                user_data = USER_DATA.get(str(uid), {})
    
                # Try to fetch fresh user info if missing
                if "first_name" not in user_data or "username" not in user_data:
                    try:
                        chat = await context.bot.get_chat(uid)
                        user_data["first_name"] = chat.first_name or "—"
                        user_data["username"] = chat.username or "—"
                        USER_DATA[str(uid)] = user_data
                        save_config()
                    except:
                        user_data.setdefault("first_name", "—")
                        user_data.setdefault("username", "—")
    
                name = user_data.get("first_name", "—")
                username = user_data.get("username", "—")
                channel = user_data.get("channel", "—")
    
                lines.append(
                    f"📌 <b>User {index}</b>\n"
                    f"├─ 👤 <b>Name:</b> {name}\n"
                    f"├─ 🧬 <b>Username:</b> {'@' + username if username and username != '—' else '—'}\n"
                    f"├─ 📡 <b>Channel:</b> {channel}\n"
                    f"└─ 🆔 <b>ID:</b> <code>{uid}</code>\n"
                    f"━━━━━━━━━━━━━━━━━━━━"
                )
    
            await query.edit_message_text(
                "\n".join(lines),
                parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="settings_back")]]),
                disable_web_page_preview=True
            )
    
        elif data == "view_autosetup":
            await query.edit_message_text(
                "<b>🔧 Select a setup to view details:</b>",
                parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("Auto Setup 1", callback_data="viewsetup1")],
                    [InlineKeyboardButton("Auto Setup 2", callback_data="viewsetup2")],
                    [InlineKeyboardButton("Auto Setup 3", callback_data="viewsetup3")],
                    [InlineKeyboardButton("Auto Setup 4", callback_data="viewsetup4")],
                    [InlineKeyboardButton("🔙 Back", callback_data="settings_back")]
                ])
            )
            return
    
        elif data.startswith("viewsetup"):
            setup_num = data[-1]
            s = AUTO_SETUP.get(f"setup{setup_num}", {})
    
            total_keys = s.get("completed_count", 0)
            total_apks = s.get("processed_count", total_keys)
            source = s.get("source_channel", "Not Set")
            dest = s.get("dest_channel", "Not Set")
            caption_ok = "✅" if s.get("dest_caption") else "❌"
            key_mode = s.get("key_mode", "auto").capitalize()
            style = s.get("style", "mono").capitalize()
            status = "✅ ON" if s.get("enabled") else "⛔ OFF"
    
            msg = (
                f"<pre>"
                f"┌──── AUTO {setup_num} SYSTEM DIAG ─────┐\n"
                f"│ SOURCE        >>  {source}\n"
                f"│ DESTINATION   >>  {dest}\n"
                f"│ CAPTION       >>  {caption_ok}\n"
                f"│ KEY_MODE      >>  {key_mode}\n"
                f"│ STYLE         >>  {style}\n"
                f"│ STATUS        >>  {status}\n"
                f"│ KEYS_SENT     >>  {total_keys}\n"
                f"│ TOTAL_APKS    >>  {total_apks} APK{'s' if total_apks != 1 else ''}\n"
                f"└──────── END OF REPORT ────────┘"
                f"</pre>"
            )
    
            await query.edit_message_text(
                text=msg,
                parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="view_autosetup")]])
            )
            return
    
        elif data == "backup_config" and user_id == OWNER_ID:
            await query.delete_message()
            await backup_config(context=context)
            return
    
        elif data == "force_reset":
            await query.edit_message_text(
                "⚠️ <b>Are you sure you want to reset all sessions?</b>",
                parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("✅ Yes", callback_data="confirm_reset"),
                     InlineKeyboardButton("❌ No", callback_data="settings_back")]
                ])
            )
            return
    
        elif data == "confirm_reset":
            # Step 1: Backup before resetting
            await backup_config(context=context)
        
            # Step 2: Reset all USER_STATE
            for user in USER_STATE:
                USER_STATE[user] = {}
        
            # Step 3: Clear Bot Admin Link in config
            config["bot_admin_link"] = ""
            global BOT_ADMIN_LINK
            BOT_ADMIN_LINK = ""
            save_config()
            save_state()
        
            # Step 4: Confirm to Owner
            await query.edit_message_text(
                "✅ Reset complete!\nAll data cleared and backup sent.",
                parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🔙 Back", callback_data="settings_back")]
                ])
            )
    
        elif data == "settings_back" or data == "cancel_restore":
            if user_id not in USER_STATE:
                USER_STATE[user_id] = {}
            
            USER_STATE[user_id].pop("pending_restore_file", None)
            USER_STATE[user_id].pop("awaiting_zip", None)
            USER_STATE[user_id].pop("zip_timeout", None)
        
            await query.edit_message_text(
                "🛠️ <b>Settings Panel</b>\nManage your bot below:",
                parse_mode="HTML",
                reply_markup = InlineKeyboardMarkup([
                    [
                        InlineKeyboardButton("➕ Add New User", callback_data="add_user"),
                        InlineKeyboardButton("➖ Remove a User", callback_data="remove_user")
                    ],
                    [
                        InlineKeyboardButton("👥 Show All Users", callback_data="view_users"),
                        InlineKeyboardButton("🔧 Auto-Setup Settings", callback_data="view_autosetup")
                    ],
                    [
                        InlineKeyboardButton("🔄 Create Backup", callback_data="backup_config")
                    ],
                    [
                        InlineKeyboardButton("♻️ Reset Everything", callback_data="force_reset")
                    ],
                    [
                        InlineKeyboardButton("🌟 Open Admin Channel", callback_data="bot_admin_link")
                    ],
                    [
                        InlineKeyboardButton("🧬 Restore from Backup", callback_data="backup_restore")
                    ],
                    [
                        InlineKeyboardButton("🧹 Reset Settings Panel", callback_data="reset_settings_panel")
                    ],
                    [
                        InlineKeyboardButton("🔙 Return to Upload Menu", callback_data="back_to_methods")
                    ]
                ])
            )
    
        elif data == "bot_admin_link" and user_id == OWNER_ID:
            USER_STATE[user_id]["awaiting_admin_link"] = True
            await query.edit_message_text("🔗 Send the new Bot Admin link (must start with https://)")
            return
    
        elif data == "backup_restore":
            USER_STATE.setdefault(user_id, {})
            USER_STATE[user_id]["awaiting_zip"] = True
            USER_STATE[user_id]["zip_timeout"] = time.time() + 20
        
            message = await query.edit_message_text(
                text="📁 <b>Please upload your backup ZIP file now.</b>\n"
                     "⏳ <b>[>-------------------] (0%)</b>",
                parse_mode="HTML"
            )
        
            USER_STATE[user_id]["zip_prompt_message_id"] = message.message_id
            chat_id = message.chat_id
        
            async def cancel_zip_restore():
                for elapsed in range(1, 21):
                    await asyncio.sleep(1)
                    state = USER_STATE.get(user_id, {})
                    if not state.get("awaiting_zip"):
                        return
        
                    arrows = ">" * elapsed
                    dashes = "-" * (20 - elapsed)
                    percent = int((elapsed / 20) * 100)
                    bar = arrows + dashes
        
                    try:
                        await context.bot.edit_message_text(
                            chat_id=chat_id,
                            message_id=message.message_id,
                            text=(
                                "📁 <b>Please upload your backup ZIP file now.</b>\n"
                                f"⏳ <b>[{bar}] ({percent}%)</b>"
                            ),
                            parse_mode="HTML"
                        )
                    except:
                        pass
        
                # Timeout
                state = USER_STATE.get(user_id, {})
                if state.get("awaiting_zip"):
                    state.pop("awaiting_zip", None)
                    state.pop("zip_timeout", None)
                    state.pop("pending_restore_file", None)
        
                    try:
                        await context.bot.delete_message(chat_id=chat_id, message_id=message.message_id)
                    except:
                        pass
        
                    await context.bot.send_message(
                        chat_id=user_id,
                        text="⏳ <b>Backup restore timed out.</b>\nPlease try again from the settings panel.",
                        parse_mode="HTML",
                        reply_markup=InlineKeyboardMarkup([
                            [
                                InlineKeyboardButton("➕ Add New User", callback_data="add_user"),
                                InlineKeyboardButton("➖ Remove a User", callback_data="remove_user")
                            ],
                            [
                                InlineKeyboardButton("👥 Show All Users", callback_data="view_users"),
                                InlineKeyboardButton("🔧 Auto-Setup Settings", callback_data="view_autosetup")
                            ],
                            [
                                InlineKeyboardButton("🔄 Create Backup", callback_data="backup_config")
                            ],
                            [
                                InlineKeyboardButton("♻️ Reset Everything", callback_data="force_reset")
                            ],
                            [
                                InlineKeyboardButton("🌟 Open Admin Channel", callback_data="bot_admin_link")
                            ],
                            [
                                InlineKeyboardButton("🧬 Restore from Backup", callback_data="backup_restore")
                            ],
                            [
                                InlineKeyboardButton("🧹 Reset Settings Panel", callback_data="reset_settings_panel")
                            ],
                            [
                                InlineKeyboardButton("🔙 Return to Upload Menu", callback_data="back_to_methods")
                            ]
                        ])
                    )
        
            context.application.create_task(cancel_zip_restore())
    
        elif data == "confirm_restore":
            doc_info = USER_STATE[user_id].get("pending_restore_file")
            if not doc_info:
                await query.answer("❌ No file to restore.", show_alert=True)
                return
        
            try:
                file = await context.bot.get_file(doc_info["file_id"])
                await handle_backup_restore_from_document(file, context, user_id, doc_info["file_name"])
            except Exception as e:
                await query.message.reply_text(f"❌ Failed to download backup.\nError: {e}")
        
        elif data == "reset_settings_panel":
            USER_STATE[user_id] = {}  # Clear all pending states
        
            await query.edit_message_text(
                "✅ Setting panel has been reset.\n\nYou're back to a clean slate!",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🔙 Back to Settings", callback_data="settings_back")]
                ])
            )
            return
        
        elif data == "add_user":
            USER_STATE.setdefault(user_id, {})["awaiting_add_user"] = True
            await query.edit_message_text(
                "🆔 <b>Send the Telegram User ID</b> to <u>add</u>:",
                parse_mode="HTML"
            )
            return
        
        elif data == "remove_user":
            USER_STATE.setdefault(user_id, {})["awaiting_remove_user"] = True
            await query.edit_message_text(
                "🆔 <b>Send the Telegram User ID</b> to <u>remove</u>:",
                parse_mode="HTML"
            )
            return

    except Exception as e:
        await notify_owner_on_error(context.bot, e, source="handle_settings_callback")

async def handle_backup_restore(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        user_id = update.effective_user.id
        if not is_authorized(user_id):
            return

        doc = update.message.document
        if not doc or not doc.file_name.endswith(".zip"):
            return  # Ignore silently if not a valid zip file

        state = USER_STATE.get(user_id)
        if not state or not state.get("awaiting_zip"):
            return

        timeout = state.get("zip_timeout", 0)
        if time.time() > timeout:
            return  # Restore session expired

        # Store serializable file info
        state["pending_restore_file"] = {
            "file_id": doc.file_id,
            "file_name": doc.file_name
        }
        state.pop("awaiting_zip", None)
        state.pop("zip_timeout", None)

        keyboard = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("✅ Confirm Restore", callback_data="confirm_restore"),
                InlineKeyboardButton("❌ Cancel", callback_data="cancel_restore")
            ],
            [
                InlineKeyboardButton("🔙 Back to Settings", callback_data="settings_back")
            ]
        ])

        await update.message.reply_text(
            "⚠️ Are you sure you want to restore this backup?\nIt will overwrite your current bot config.",
            reply_markup=keyboard
        )

    except Exception as e:
        await notify_owner_on_error(context.bot, e, source="handle_backup_restore")


async def handle_backup_restore_from_document(file, context, user_id, filename):
    try:
        zip_path = f"/tmp/{filename}"
        status_msg = await context.bot.send_message(
            user_id, "⏳ Restoring backup..."
        )

        try:
            # Step 1: Download the ZIP
            await file.download_to_drive(zip_path)

            # Step 2: Extract contents
            with zipfile.ZipFile(zip_path, "r") as zip_ref:
                zip_ref.extractall(".")

            # Step 3: Remove ZIP
            os.remove(zip_path)

            # Step 4: Reload config/state
            load_state()

            # Step 5: Success message with updated buttons
            success_keyboard = InlineKeyboardMarkup([
                [InlineKeyboardButton("🔁 Restart Bot on Railway", url="https://railway.app/dashboard")],
                [InlineKeyboardButton("🔙 Back to Settings", callback_data="settings_back")]
            ])

            await context.bot.edit_message_text(
                chat_id=user_id,
                message_id=status_msg.message_id,
                text="✅ <b>Backup Restored!</b>\nPlease restart the bot on Railway for full effect.",
                parse_mode="HTML",
                reply_markup=success_keyboard
            )

        except Exception as e:
            fail_keyboard = InlineKeyboardMarkup([
                [InlineKeyboardButton("🔄 Try Again", callback_data="backup_restore")],
                [InlineKeyboardButton("🔙 Back to Settings", callback_data="settings_back")]
            ])

            await context.bot.edit_message_text(
                chat_id=user_id,
                message_id=status_msg.message_id,
                text=f"❌ <b>Restore Failed</b>\n<code>{e}</code>",
                parse_mode="HTML",
                reply_markup=fail_keyboard
            )

    except Exception as e:
        await notify_owner_on_error(context.bot, e, source="handle_backup_restore_from_document")

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        global BOT_ACTIVE, USER_DATA, ALLOWED_USERS, BOT_ADMIN_LINK  # <-- FIXED LINE

        if not update.message or not update.message.text or not update.effective_user:
            return

        user = update.effective_user
        user_id = user.id
        raw_message_text = update.message.text.strip()
        message_text = raw_message_text.lower()
        
        # Register user
        if str(user_id) not in USER_DATA:
            USER_DATA[str(user_id)] = {
                "first_name": user.first_name,
                "username": user.username,
            }
            save_config()

        # Bot OFF logic
        if not BOT_ACTIVE and user_id != OWNER_ID:
            await update.message.reply_text("🚫 The bot is currently turned off by the admin.")
            return

        # Unauthorized user check
        if user_id != OWNER_ID and user_id not in ALLOWED_USERS:
            await update.message.reply_text("🚫 You are not authorized to interact.")
            return

        # --- Owner Broadcast Mode ---
        if user_id == OWNER_ID and BROADCAST_SESSION.get(user_id, {}).get("waiting_for_message"):
            msg = update.message

            # If buttons text given
            if raw_message_text and "|" in raw_message_text and "http" in raw_message_text:
                BROADCAST_SESSION[user_id]["buttons_raw"] = raw_message_text
                await msg.reply_text("✅ Buttons received. Ready to confirm.")
                return

            # If empty
            if not raw_message_text:
                await msg.reply_text("❌ Empty message cannot be broadcasted.")
                return

            BROADCAST_SESSION[user_id]["message"] = msg
            BROADCAST_SESSION[user_id]["waiting_for_message"] = False

            preview_keyboard = InlineKeyboardMarkup([
                [InlineKeyboardButton("✅ Confirm", callback_data="confirm_broadcast"),
                 InlineKeyboardButton("❌ Cancel", callback_data="cancel_broadcast")]
            ])

            safe_text = escape(raw_message_text[:4000])

            await context.bot.send_message(
                chat_id=user_id,
                text=f"<b>📨 Preview:</b>\n\n{safe_text}",
                parse_mode="HTML",
                reply_markup=preview_keyboard
            )
            return

        # BUTTON TEXT HANDLING
        if message_text == "ping":
            await ping(update, context)
            return
        elif message_text == "help":
            await help_command(update, context)
            return
        elif message_text == "rules":
            await rules(update, context)
            return
        elif message_text == "reset":
            await reset(update, context)
            return
        elif message_text == "userlist" and user_id == OWNER_ID:
            await userlist(update, context)
            return
        elif message_text == "viewsetup":
            await user_viewsetup(update, context)
            return
        elif message_text.lower() == "on" and user_id == OWNER_ID:
            BOT_ACTIVE = True
            save_config()
            await update.message.reply_text("✅ Bot is now active. Users can interact again.")
            return
        elif message_text.lower() == "off" and user_id == OWNER_ID:
            BOT_ACTIVE = False
            save_config()
            await update.message.reply_text("⛔ Bot is now inactive. User interaction is disabled.")
            return
        elif message_text == "settings" and user_id == OWNER_ID:
            await settings_panel(update, context)
            return
        elif message_text.lower() == "broadcast" and user_id == OWNER_ID:
            BROADCAST_SESSION[user_id] = {
                "waiting_for_message": True,
                "message": None,
                "buttons_raw": None
            }
            await update.message.reply_text(
                "<b>📣 BROADCAST MODE ACTIVE</b>\n"
                "━━━━━━━━━━━━━━━━━━━━\n"
                "📝 Send the message you want to broadcast (HTML supported).\n\n"
                "➕ To add buttons, send this format after the message:\n"
                "<code>Text | https://your-url.com</code>\n"
                "(One button per line)\n"
                "━━━━━━━━━━━━━━━━━━━━",
                parse_mode="HTML"
            )
            return
        elif message_text == "My Channel":
            user_channel = USER_DATA.get(str(user_id), {}).get("channel", "Not Set")
            formatted_channel = (user_channel[:26] + '…') if len(user_channel) > 28 else user_channel
            await update.message.reply_text(
                "<b>━━━━━━━━━━━━━━━━━━━━━━━━━━</b>\n"
                "<b>      📡 CHANNEL INFO       </b>\n"
                "<b>━━━━━━━━━━━━━━━━━━━━━━━━━━</b>\n"
                f"<b>📎 Current:</b> <code>{formatted_channel}</code>",
                parse_mode="HTML"
            )
            return
        elif message_text == "My Caption":
            user_caption = USER_DATA.get(str(user_id), {}).get("caption", "Not Set")
        
            await update.message.reply_text(
                "<b>━━━━━━━━━━━━━━━━━━━━━━━━━━</b>\n"
                "<b>     📝 CAPTION TEMPLATE     </b>\n"
                "<b>━━━━━━━━━━━━━━━━━━━━━━━━━━</b>\n\n"
                f"<code>{user_caption}</code>" if user_caption != "Not Set" else "<i>No caption set.</i>",
                parse_mode="HTML"
            )
            return
        elif message_text == "userstats" and user_id == OWNER_ID:
            from datetime import datetime
            from html import escape
            import time
            from zoneinfo import ZoneInfo  # For IST timezone

            lines = [
                "<b>📊 𝗨𝗦𝗘𝗥 𝗥𝗘𝗣𝗢𝗥𝗧</b>",
                "<b>━━━━━━━━━━━━━━━━━━━━━━━</b>"
            ]

            if not ALLOWED_USERS:
                lines.append("<b>⚠️ No authorized users found.</b>")
            else:
                for index, uid in enumerate(ALLOWED_USERS, start=1):
                    user = USER_DATA.get(str(uid), {})
                    state = USER_STATE.setdefault(uid, {})

                    # Init start_time if missing
                    if "start_time" not in state:
                        state["start_time"] = time.time()

                    # Fetch live user details if needed
                    if "first_name" not in user or "username" not in user:
                        try:
                            chat = await context.bot.get_chat(uid)
                            user["first_name"] = chat.first_name or "—"
                            user["username"] = chat.username or "—"
                            USER_DATA[str(uid)] = user
                            save_config()
                        except Exception:
                            user.setdefault("first_name", "—")
                            user.setdefault("username", "—")

                    # Format user display data
                    name = user.get("first_name", "—")
                    uname = user.get("username", "—")
                    uname_tag = f"@{uname}" if uname and uname != "—" else "—"

                    # Channel logic: clean display
                    raw_channel = str(user.get("channel") or "—")
                    if raw_channel.startswith("-100"):
                        channel_display = "Private ID"
                    elif raw_channel.startswith("@"):
                        channel_display = raw_channel.strip("@")
                    else:
                        channel_display = raw_channel.strip("@")

                    caption = user.get("caption")
                    caption_text = f"<pre>{escape(str(caption)[:150])}</pre>" if caption else "—"

                    start_ts = state.get("start_time", time.time())
                    ist_now = datetime.now(ZoneInfo("Asia/Kolkata"))
                    start_dt = datetime.fromtimestamp(start_ts, ZoneInfo("Asia/Kolkata"))
                    days_used = (ist_now - start_dt).days

                    # All-time counts
                    m1_apks = state.get("alltime_method1_apks", 0)
                    m1_keys = state.get("alltime_method1_keys", 0)
                    m2_apks = state.get("alltime_method2_apks", 0)
                    m2_keys = state.get("alltime_method2_keys", 0)
                    total_apks = m1_apks + m2_apks
                    total_keys = m1_keys + m2_keys

                    lines.extend([
                        f"\n<b>👤 USER {index}</b>",
                        "<blockquote>",
                        f"🆔 <b>ID:</b> <code>{uid}</code>",
                        f"👤 <b>Name:</b> {name}",
                        f"🔗 <b>Username:</b> {uname_tag}",
                        f"📡 <b>Channel:</b> @{channel_display}" if channel_display != "Private ID" else "📡 <b>Channel:</b> Private ID",
                        f"📝 <b>Caption:</b>\n{caption_text}",
                        f"⏳ <b>Using Since:</b> {days_used} days",
                        f"📦 <b>Method 1:</b> {m1_apks} APKs | {m1_keys} Keys",
                        f"🧪 <b>Method 2:</b> {m2_apks} APKs | {m2_keys} Keys",
                        f"🧮 <b>Total:</b> {total_apks} APKs | {total_keys} Keys",
                        "</blockquote>"
                    ])

            lines.append(f"\n<b>👥 Total Users:</b> {len(ALLOWED_USERS)}")
            lines.append(f"<b>📅 Generated:</b> {datetime.now(ZoneInfo('Asia/Kolkata')).strftime('%d %b %Y, %I:%M %p')}")

            reply_markup = InlineKeyboardMarkup([
                [InlineKeyboardButton("🚂 Railway Panel", url="https://railway.app/project/")]
            ])

            await update.message.reply_text(
                "\n".join(lines),
                parse_mode="HTML",
                disable_web_page_preview=True,
                reply_markup=reply_markup
            )
            return
        
        
        # STATE HANDLING
        state = USER_STATE.get(user_id)
        if not state:
            return
        
        # --- Handle ReplyKeyboard Method Selection via Text ---
        if raw_message_text == "METHOD 1":
            query = update  # mock object
            USER_STATE.setdefault(user_id, {})["current_method"] = "method1"
            USER_STATE[user_id]["status"] = "normal"
        
            user_data = USER_DATA.get(str(user_id), {})
            channel = user_data.get("channel")
            caption = user_data.get("caption")
        
            buttons = []
        
            if BOT_ADMIN_LINK:
                buttons.append([InlineKeyboardButton("🌟 Bot Admin", url=BOT_ADMIN_LINK)])
        
            buttons.append([InlineKeyboardButton("📡 Set Channel", callback_data="set_channel")])
            buttons.append([InlineKeyboardButton("📝 Set Caption", callback_data="set_caption")])
        
            if channel and caption:
                buttons.append([InlineKeyboardButton("📤 Send One APK", callback_data="send_apk_method1")])
        
            buttons.append([InlineKeyboardButton("🔙 Back to Methods", callback_data="back_to_methods")])
        
            await update.message.reply_text(
                "<b>╭─[ METHOD 1 SELECTED ]</b>\n"
                "<blockquote>"
                "│ ✅ Mode: Auto Key\n"
                "│ 📤 One APK per send\n"
                "│ ⚙️ Setup: Admin + Channel + Caption\n"
                "╰────────────────────────\n"
                "</blockquote>",
                parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup(buttons)
            )
            return
        
        if raw_message_text == "METHOD 2":
            USER_STATE.setdefault(user_id, {})["current_method"] = "method2"
            USER_STATE[user_id]["status"] = "normal"
        
            user_data = USER_DATA.get(str(user_id), {})
            channel = user_data.get("channel")
            caption = user_data.get("caption")
        
            buttons = []
        
            if BOT_ADMIN_LINK:
                buttons.append([InlineKeyboardButton("🌟 Bot Admin", url=BOT_ADMIN_LINK)])
        
            buttons.append([InlineKeyboardButton("📡 Set Channel", callback_data="set_channel")])
            buttons.append([InlineKeyboardButton("📝 Set Caption", callback_data="set_caption")])
        
            if channel and caption:
                buttons.append([InlineKeyboardButton("📤 Send 2–3 APKs", callback_data="send_apk_method2")])
        
            buttons.append([InlineKeyboardButton("🔙 Back to Methods", callback_data="back_to_methods")])
        
            await update.message.reply_text(
                "<b>╭─[ METHOD 2 SELECTED ]</b>\n"
                "<blockquote>"
                "│ ✅ Mode: Multi APK Upload\n"
                "│ 📤 Upload 2-3 APKs\n"
                "│ ⚙️ Setup: Channel + Caption\n"
                "╰────────────────────────\n"
                "</blockquote>",
                parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup(buttons)
            )
            return
    
        if state.get("status") == "waiting_new_caption":
            await method2_edit_caption(update, context)
            return
    
        # ========= Method 1 & 2 ========= #
    
        # Handle Channel Setting (used in Method 1 & 2)
        if state and state.get("status") == "waiting_channel":
            channel_id = message_text.strip()
        
            # Validate channel format
            if not (channel_id.startswith("@") or channel_id.startswith("-100")):
                await update.message.reply_text(
                    "<b>❌ Invalid Channel ID</b>\n"
                    "Use <code>@channelusername</code> or <code>-100xxxxxxxxxx</code>",
                    parse_mode="HTML"
                )
                return
        
            try:
                chat_info = await context.bot.get_chat(channel_id)
                admins = await context.bot.get_chat_administrators(chat_info.id)
        
                # Check bot is admin
                bot_admin = any(admin.user.id == context.bot.id and admin.status in ["administrator", "creator"] for admin in admins)
                if not bot_admin:
                    await update.message.reply_text(
                        "<b>🚫 Bot is not an admin!</b>\n"
                        "Please make the bot an admin to continue.",
                        parse_mode="HTML"
                    )
                    return
        
                # Check user is admin
                user_admin = any(admin.user.id == user_id and admin.status in ["administrator", "creator"] for admin in admins)
                if not user_admin:
                    await update.message.reply_text(
                        "<b>🚫 You are not an admin of this channel!</b>\n"
                        "Only channel admins can link the channel.",
                        parse_mode="HTML"
                    )
                    return
        
            except Exception as e:
                await update.message.reply_text(
                    f"<b>❌ Channel Not Found or Access Denied!</b>\n"
                    "Make sure the bot is added and has access.\n"
                    f"Error: {e}",
                    parse_mode="HTML"
                )
                return
        
            # Save channel
            USER_DATA[str(user_id)] = USER_DATA.get(str(user_id), {})
            USER_DATA[str(user_id)]["channel"] = channel_id
            save_config()
            USER_STATE[user_id]["status"] = "normal"
        
            channel_disp = channel_id if channel_id.startswith("@") else f"<code>{channel_id}</code>"
        
            keyboard = [
                [InlineKeyboardButton("⚡ Method 1", callback_data="method_1")],
                [InlineKeyboardButton("🚀 Method 2", callback_data="method_2")]
            ]
        
            await update.message.reply_text(
                "<b>✅ 𝗖𝗵𝗮𝗻𝗻𝗲𝗹 𝗟𝗶𝗻𝗸𝗲𝗱 𝗦𝘂𝗰𝗰𝗲𝘀𝘀𝗳𝘂𝗹𝗹𝘆!</b>\n\n"
                "<blockquote>"
                f"📡 <b>Linked Channel:</b> {channel_disp}\n"
                "🛡️ <b>Bot Status:</b> 𝗔𝗗𝗠𝗜𝗡 𝗖𝗢𝗡𝗙𝗜𝗥𝗠𝗘𝗗\n"
                "🔄 <b>Channel Access:</b> 𝚅𝚎𝚛𝚒𝚏𝚒𝚎𝚍\n"
                "━━━━━━━━━━━━━━━━━━━━━"
                "</blockquote>",
                parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
            return
    
        # Handle Styled Caption Setup (raw HTML allowed)
        if state.get("status") == "waiting_caption":
            caption = update.message.text.strip()

            if "Key -" not in caption:
                await update.message.reply_text(
                    "<b>❗ Invalid Caption</b>\n"
                    "It must include: <code>Key -</code>",
                    parse_mode="HTML"
                )
                return

            USER_DATA[str(user_id)] = USER_DATA.get(str(user_id), {})
            USER_DATA[str(user_id)]["caption"] = caption
            save_config()
            USER_STATE[user_id]["status"] = "normal"

            keyboard = [
                [InlineKeyboardButton("⚡ Method 1", callback_data="method_1")],
                [InlineKeyboardButton("🚀 Method 2", callback_data="method_2")]
            ]

            await update.message.reply_text(
                "<b>✅ 𝗖𝗮𝗽𝘁𝗶𝗼𝗻 𝗦𝗮𝘃𝗲𝗱 𝗦𝘂𝗰𝗰𝗲𝘀𝘀𝗳𝘂𝗹𝗹𝘆!</b>\n\n"
                "<blockquote>"
                "📝 <b>𝗖𝘂𝗿𝗿𝗲𝗻𝘁 𝗖𝗮𝗽𝘁𝗶𝗼𝗻 𝗣𝗿𝗲𝘃𝗶𝗲𝘄:</b>\n\n"
                f"{caption}\n"
                "━━━━━━━━━━━━━━━━━━━━━"
                "</blockquote>",
                parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
            return
        
        # ========= Method 3 (Auto 1, 2, 3) ========= #
            
        elif state.get("status", "").startswith("waiting_source"):
            setup_num = state["status"][-1]
            text = update.message.text.strip()
        
            if not (text.startswith("@") or text.startswith("-100")):
                await update.message.reply_text("❌ Invalid Source Channel ID.\nMust start with @username or -100...")
                return
        
            try:
                if text.startswith("@"):
                    chat = await context.bot.get_chat(text)
                    resolved_id = str(chat.id)
                    AUTO_SETUP[f"setup{setup_num}"]["source_channel"] = resolved_id
                else:
                    AUTO_SETUP[f"setup{setup_num}"]["source_channel"] = text
            except Exception as e:
                await update.message.reply_text(f"❌ Failed to resolve channel: {e}")
                return
        
            USER_STATE[user_id]["status"] = "normal"
            save_config()
        
            keyboard = [
                [InlineKeyboardButton("📡 Set Source", callback_data=f"setsource{setup_num}"),
                 InlineKeyboardButton("🎯 Set Destination", callback_data=f"setdest{setup_num}")],
                [InlineKeyboardButton("✍️ Set Caption", callback_data=f"setdestcaption{setup_num}")],
                [InlineKeyboardButton("🤖 Automated", callback_data=f"automated{setup_num}"),
                 InlineKeyboardButton("🧠 Key Manual", callback_data=f"manual{setup_num}")],
                [InlineKeyboardButton("📌 Quote Key", callback_data=f"quote{setup_num}"),
                 InlineKeyboardButton("🔤 Mono Key", callback_data=f"mono{setup_num}")],
                [InlineKeyboardButton("✅ On", callback_data=f"on{setup_num}"),
                 InlineKeyboardButton("⛔ Off", callback_data=f"off{setup_num}")],
                [InlineKeyboardButton("👁️ View Setup", callback_data=f"viewsetup{setup_num}"),
                 InlineKeyboardButton("🧹 Reset Setup", callback_data=f"resetsetup{setup_num}")],
                [InlineKeyboardButton("🔙 Back to Auto Menu", callback_data="method_3")]
            ]
        
            await update.message.reply_text(
                f"✅ Source Channel saved for Auto {setup_num}!\n\nChoose your next action:",
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode="HTML"
            )
            return
        
        # ------------------------------
        
        elif state.get("status", "").startswith("waiting_dest"):
            setup_num = state["status"][-1]
            text = update.message.text.strip()
        
            if not (text.startswith("@") or text.startswith("-100")):
                await update.message.reply_text("❌ Invalid Destination Channel ID.\nMust start with @username or -100...")
                return
        
            try:
                if text.startswith("@"):
                    chat = await context.bot.get_chat(text)
                    resolved_id = str(chat.id)
                    AUTO_SETUP[f"setup{setup_num}"]["dest_channel"] = resolved_id
                else:
                    AUTO_SETUP[f"setup{setup_num}"]["dest_channel"] = text
            except Exception as e:
                await update.message.reply_text(f"❌ Failed to resolve channel: {e}")
                return
        
            USER_STATE[user_id]["status"] = "normal"
            save_config()
        
            keyboard = [
                [InlineKeyboardButton("📡 Set Source", callback_data=f"setsource{setup_num}"),
                 InlineKeyboardButton("🎯 Set Destination", callback_data=f"setdest{setup_num}")],
                [InlineKeyboardButton("✍️ Set Caption", callback_data=f"setdestcaption{setup_num}")],
                [InlineKeyboardButton("🤖 Automated", callback_data=f"automated{setup_num}"),
                 InlineKeyboardButton("🧠 Key Manual", callback_data=f"manual{setup_num}")],
                [InlineKeyboardButton("📌 Quote Key", callback_data=f"quote{setup_num}"),
                 InlineKeyboardButton("🔤 Mono Key", callback_data=f"mono{setup_num}")],
                [InlineKeyboardButton("✅ On", callback_data=f"on{setup_num}"),
                 InlineKeyboardButton("⛔ Off", callback_data=f"off{setup_num}")],
                [InlineKeyboardButton("👁️ View Setup", callback_data=f"viewsetup{setup_num}"),
                 InlineKeyboardButton("🧹 Reset Setup", callback_data=f"resetsetup{setup_num}")],
                [InlineKeyboardButton("🔙 Back to Auto Menu", callback_data="method_3")]
            ]
        
            await update.message.reply_text(
                f"✅ Destination Channel saved for Auto {setup_num}!\n\nChoose your next action:",
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode="HTML"
            )
            return
        
        # ------------------------------
        
        elif state.get("status", "").startswith("waiting_caption"):
            setup_num = state["status"][-1]
            text = update.message.text.strip()
        
            if "Key -" not in text:
                await update.message.reply_text("❌ Destination Caption must include 'Key -' placeholder.")
                return
        
            AUTO_SETUP[f"setup{setup_num}"]["dest_caption"] = text
            USER_STATE[user_id]["status"] = "normal"
            save_config()
        
            keyboard = [
                [InlineKeyboardButton("📡 Set Source", callback_data=f"setsource{setup_num}"),
                 InlineKeyboardButton("🎯 Set Destination", callback_data=f"setdest{setup_num}")],
                [InlineKeyboardButton("✍️ Set Caption", callback_data=f"setdestcaption{setup_num}")],
                [InlineKeyboardButton("🤖 Automated", callback_data=f"automated{setup_num}"),
                 InlineKeyboardButton("🧠 Key Manual", callback_data=f"manual{setup_num}")],
                [InlineKeyboardButton("📌 Quote Key", callback_data=f"quote{setup_num}"),
                 InlineKeyboardButton("🔤 Mono Key", callback_data=f"mono{setup_num}")],
                [InlineKeyboardButton("✅ On", callback_data=f"on{setup_num}"),
                 InlineKeyboardButton("⛔ Off", callback_data=f"off{setup_num}")],
                [InlineKeyboardButton("👁️ View Setup", callback_data=f"viewsetup{setup_num}"),
                 InlineKeyboardButton("🧹 Reset Setup", callback_data=f"resetsetup{setup_num}")],
                [InlineKeyboardButton("🔙 Back to Auto Menu", callback_data="method_3")]
            ]
        
            await update.message.reply_text(
                f"✅ Destination Caption saved for Auto {setup_num}!\n\nChoose your next action:",
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode="HTML"
            )
            return
        
        # Inside your text handler
        if state.get("waiting_key") and state.get("current_method") == "method1":
            key = update.message.text.strip()
            file_id = state.get("file_id")
            saved_caption = USER_DATA.get(str(user_id), {}).get("caption", "")
            channel_id = USER_DATA.get(str(user_id), {}).get("channel", "")
        
            if not key or not file_id or not saved_caption or not channel_id:
                await update.message.reply_text("❌ Missing data. Please restart Method 1.")
                return
        
            final_caption = saved_caption.replace("Key -", f"Key - <code>{key}</code>")
            
            USER_STATE[user_id]["waiting_key"] = False
            USER_STATE[user_id]["file_id"] = None
            USER_STATE[user_id]["pending_apk"] = {
                "file_id": file_id,
                "caption": final_caption,
                "channel": channel_id,
                "confirm_message_id": update.message.message_id
            }
        
            await ask_to_share(update, context)
            return
        
        # Method 2 Key Handler — FINAL & STABLE
        if state.get("current_method") == "method2":
        
            # Step 0: Accept key only if either waiting_key is True or countdown running
            waiting = state.get("waiting_key", False)
            countdown_active = (
                state.get("countdown_task") and not state["countdown_task"].done()
            )
            if not (waiting or countdown_active):
                return  # Ignore if neither countdown nor waiting_key is active
        
            # Step 1: Ignore if key already saved
            if state.get("saved_key"):
                return
        
            # Step 2: Grab key text and session files
            key = update.message.text.strip()
            session_files = state.get("session_files", [])
        
            # Step 3: Ignore if key is empty
            if not key:
                return
        
            # Step 4: Validate key length
            if len(key) < 4 or len(key) > 30:
                await update.message.reply_text("❗ Invalid key. Please enter a valid key.")
                return
        
            # Step 5: Abort if no APKs exist
            if not session_files:
                return
        
            # Step 6: Stop countdown if it's running
            task = state.get("countdown_task")
            if task and not task.done():
                task.cancel()
            state["countdown_task"] = None
        
            # Step 7: Delete countdown message if exists
            if state.get("countdown_msg_id"):
                try:
                    await context.bot.delete_message(
                        chat_id=user_id,
                        message_id=state["countdown_msg_id"]
                    )
                except:
                    pass
                state["countdown_msg_id"] = None
        
            # Step 8: Save key and reset session flags
            state["saved_key"] = key
            state["waiting_key"] = False
            state["key_prompt_sent"] = True
            state["quote_applied"] = False
            state["mono_applied"] = False
            state["progress_message_id"] = None
        
            # Step 9: Show post-key control panel
            keyboard = [
                [
                    InlineKeyboardButton("✅ Send to Channel", callback_data="method2_yes"),
                    InlineKeyboardButton("❌ Cancel Upload", callback_data="method2_no")
                ],
                [
                    InlineKeyboardButton("✍️ Add Quote Style", callback_data="method2_quote"),
                    InlineKeyboardButton("🔤 Add Mono Style", callback_data="method2_mono")
                ],
                [
                    InlineKeyboardButton("📝 Edit Caption", callback_data="method2_edit"),
                    InlineKeyboardButton("👁️ Preview Before Posting", callback_data="method2_preview")
                ],
                [
                    InlineKeyboardButton("🧹 Clear all", callback_data="erase_all_session")
                ]
            ]
        
            sent = await update.message.reply_text(
                text=(
                    f"<pre>"
                    f"▌ KEY RECEIVED ▌\n"
                    f"▶ Your Key: {key}\n"
                    f"▶ Choose what to do next with your APKs:\n"
                    f"────────────────────"
                    f"</pre>"
                ),
                parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
        
            # Step 10: Save preview panel message ID
            state["preview_message_id"] = sent.message_id
            return

        if USER_STATE.get(user_id, {}).get("awaiting_admin_link"):
            link = update.message.text.strip()

            USER_STATE.setdefault(user_id, {})

            if link.startswith("https://"):
                BOT_ADMIN_LINK = link  # now this is allowed
                config["bot_admin_link"] = link
                save_config()
                USER_STATE[user_id]["awaiting_admin_link"] = False

                await update.message.reply_text(
                    "✅ Bot Admin link updated!",
                    reply_markup=InlineKeyboardMarkup([
                        [InlineKeyboardButton("🔙 Back to Settings", callback_data="settings_back")]
                    ])
                )
            else:
                await update.message.reply_text("❌ Invalid link. It must start with https://")
            return
        
        # === Handle Add/Remove User Input from Settings Panel ===
        if user_id == OWNER_ID:
            # Always initialize USER_STATE entry for owner
            state = USER_STATE.setdefault(user_id, {})
            
            # Handle Add User
            if state.get("awaiting_add_user", False):
                try:
                    target_id = int(update.message.text.strip())
                    ALLOWED_USERS.add(target_id)
        
                    # Attempt to fetch and store user info
                    try:
                        user = await context.bot.get_chat(target_id)
                        USER_DATA[str(target_id)] = {
                            "first_name": user.first_name or "—",
                            "username": user.username or "—",
                            "channel": USER_DATA.get(str(target_id), {}).get("channel", "—"),
                            "first_seen": int(time.time())  # Optional: track join time
                        }
                    except Exception as e:
                        print(f"[!] Failed to fetch user info: {e}")
                        USER_DATA[str(target_id)] = {
                            "first_name": "—",
                            "username": "—",
                            "channel": "—",
                            "first_seen": int(time.time())
                        }
        
                    save_config()
                    state["awaiting_add_user"] = False  # Reset flag
                    await update.message.reply_text(
                        f"✅ User `{target_id}` added successfully!",
                        parse_mode="Markdown",
                        reply_markup=InlineKeyboardMarkup([
                            [InlineKeyboardButton("🔙 Back to Settings", callback_data="settings_back")]
                        ])
                    )
                except Exception as e:
                    print(f"[!] Error while adding user: {e}")
                    await update.message.reply_text(
                        f"❌ Error while adding user:\n<code>{e}</code>",
                        parse_mode="HTML"
                    )
                return  # Let the callback handle back navigation
        
            # Handle Remove User
            if state.get("awaiting_remove_user", False):
                try:
                    target_id = int(update.message.text.strip())
                    ALLOWED_USERS.discard(target_id)
                    USER_DATA.pop(str(target_id), None)
                    save_config()
                    state["awaiting_remove_user"] = False  # Reset flag
                    await update.message.reply_text(
                        f"🚫 User `{target_id}` removed successfully!",
                        parse_mode="Markdown",
                        reply_markup=InlineKeyboardMarkup([
                            [InlineKeyboardButton("🔙 Back to Settings", callback_data="settings_back")]
                        ])
                    )
                except Exception as e:
                    print(f"[!] Error while removing user: {e}")
                    await update.message.reply_text(
                        f"❌ Error while removing user:\n<code>{e}</code>",
                        parse_mode="HTML"
                    )
                return  # Let the callback handle back navigation
        
    except Exception as e:
        await notify_owner_on_error(context.bot, e, source="handle_text")

async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        query = update.callback_query
        user_id = query.from_user.id
        data = query.data

        # Immediately answer callback to avoid Telegram timeout
        try:
            await query.answer()
        except:
            await query.message.reply_text("⏳ Session expired or invalid. ❌")
            return

        # Anti-spam cooldown
        now = time.time()
        if not hasattr(context, "user_cooldowns"):
            context.user_cooldowns = {}
        if user_id in context.user_cooldowns and now - context.user_cooldowns[user_id] < 1:
            await query.answer("⌛ Wait a second...", show_alert=False)
            return
        context.user_cooldowns[user_id] = now

        # ✅ Confirm Broadcast
        if data == "confirm_broadcast":
            await send_broadcast(update, context)
            return

        # ❌ Cancel Broadcast
        if data == "cancel_broadcast":
            BROADCAST_SESSION.pop(user_id, None)
            try:
                await query.message.delete()
            except:
                await query.edit_message_text("❌ Broadcast Cancelled.", parse_mode="HTML")
            return

        # ⚠️ Unknown Callback
        await query.answer("⚠️ Unknown action.", show_alert=True)

        # Optional: Session check (if callback is from normal user flow)
        if user_id not in USER_STATE:
            await query.edit_message_text(
                "⏳ Session expired or invalid! ❌\nPlease restart using /start.",
                parse_mode="Markdown"
            )
            return
    
        # --- define auto keyboard generator here ---
        def get_auto_keyboard(setup_num):
            keyboard = [
                [InlineKeyboardButton("📡 Set Source", callback_data=f"setsource{setup_num}"),
                 InlineKeyboardButton("🎯 Set Destination", callback_data=f"setdest{setup_num}")],
                [InlineKeyboardButton("✍️ Set Caption", callback_data=f"setdestcaption{setup_num}")]
            ]
        
            # Only show key mode buttons for Auto 1–3
            if setup_num in ("1", "2", "3"):
                keyboard.append([
                    InlineKeyboardButton("🤖 Automated", callback_data=f"automated{setup_num}"),
                    InlineKeyboardButton("🧠 Key Manual", callback_data=f"manual{setup_num}")
                ])
        
            # Key style buttons (shown for all autos)
            keyboard.append([
                InlineKeyboardButton("📌 Quote Key", callback_data=f"quote{setup_num}"),
                InlineKeyboardButton("🔤 Mono Key", callback_data=f"mono{setup_num}")
            ])
        
            # On/Off toggle
            keyboard.append([
                InlineKeyboardButton("✅ On", callback_data=f"on{setup_num}"),
                InlineKeyboardButton("⛔ Off", callback_data=f"off{setup_num}")
            ])
        
            # View/Reset + back button
            keyboard.append([
                InlineKeyboardButton("👁️ View Setup", callback_data=f"viewsetup{setup_num}"),
                InlineKeyboardButton("🧹 Reset Setup", callback_data=f"resetsetup{setup_num}")
            ])
        
            keyboard.append([
                InlineKeyboardButton("🔙 Back to Methods", callback_data="back_to_methods")
            ])
        
            return InlineKeyboardMarkup(keyboard)
    
        # --- Handling Auto Setup Buttons ---
        if data == "method_3":
            keyboard = [
                [InlineKeyboardButton("⚙️ Auto 1", callback_data="auto1_menu"),
                 InlineKeyboardButton("⚙️ Auto 2", callback_data="auto2_menu")],
                [InlineKeyboardButton("⚙️ Auto 3", callback_data="auto3_menu"),
                 InlineKeyboardButton("⚙️ Auto 4", callback_data="auto4_menu")],
                [InlineKeyboardButton("🔙 Back to Methods", callback_data="back_to_methods")]
            ]
            await query.edit_message_text(
                "🛠 <b>Method 3 Activated!</b>\nChoose a setup to configure:",
                parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
            return

        if data == "back_to_methods":
            user = query.from_user
            user_id = user.id
            user_key = str(user_id)  # Moved this up before using it
    
            # Get or set first_seen timestamp
            first_seen = USER_DATA.get(user_key, {}).get("first_seen")
            if not first_seen:
                first_seen = int(time.time())
                USER_DATA[user_key] = USER_DATA.get(user_key, {})
                USER_DATA[user_key]["first_seen"] = first_seen
                save_config()
    
            now = int(time.time())
            days_count = (now - first_seen) // 86400
    
            india_tz = ZoneInfo("Asia/Kolkata")
    
            keyboard = [
                [InlineKeyboardButton("⚡ Method 1", callback_data="method_1")],
                [InlineKeyboardButton("🚀 Method 2", callback_data="method_2")]
            ]
            if user_id == OWNER_ID:
                keyboard.append([InlineKeyboardButton("🛠 Method 3", callback_data="method_3")])
    
            await query.edit_message_text(
                text=(
                    "<b>𝗖𝗘𝗢 𝗣𝗔𝗡𝗘𝗟 🏆</b>\n"
                    "<blockquote>"
                    "<b>━━━━━━━━━━━━━━━━━━━━━━━━\n"
                    f"• 👤 Name     : {user.first_name or 'User'}\n"
                    f"• 🆔 User ID  : <a href=\"tg://user?id={user_id}\">{user_id}</a>\n"
                    f"• ⏱️ Days     : {days_count} Days\n"
                    "• ✅ Access   : Authorized ✓\n"
                    "• ⚙️ System   : Online ✓\n\n"
                    "      <b>𝗨𝗽𝗹𝗼𝗮𝗱 𝗠𝗲𝘁𝗵𝗼𝗱𝘀</b>\n"
                    "➡ Method 1 - 𝚄𝚙𝚕𝚘𝚊𝚍 𝟷/𝟷 𝙰𝚙𝚔\n"
                    "➡ Method 2 - 𝚄𝚙𝚕𝚘𝚊𝚍 𝟹/𝟹 𝚊𝚙𝚔𝚜\n"
                    "━━━━━━━━━━━━━━━━━━━━━━━━</b>"
                    "</blockquote>\n"
                    "<i>NOTE: You can switch methods anytime. Logs are monitored.</i>"
                ),
                parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup(keyboard),
                disable_web_page_preview=True
            )
    
        if data.startswith("auto") and data.endswith("_menu"):
            setup_num = data[4]
            await query.edit_message_text(
                text=f"⚙️ <b>Auto {setup_num} Config</b>\nSelect an option to configure:",
                parse_mode="HTML",
                reply_markup=get_auto_keyboard(setup_num)
            )
            return
    
        if data.startswith("setsource"):
            setup_num = data[-1]
            USER_STATE[user_id]["status"] = f"waiting_source{setup_num}"
            await query.edit_message_text(f"📡 Send Source Channel ID for Auto {setup_num}", parse_mode="HTML")
            return
    
        if data.startswith("setdest") and not data.startswith("setdestcaption"):
            setup_num = data[-1]
            USER_STATE[user_id]["status"] = f"waiting_dest{setup_num}"
            await query.edit_message_text(f"🎯 Send Destination Channel ID for Auto {setup_num}", parse_mode="HTML")
            return
    
        if data.startswith("setdestcaption"):
            setup_num = data[-1]
            USER_STATE[user_id]["status"] = f"waiting_caption{setup_num}"
            await query.edit_message_text(f"✍️ Send Caption (must include 'Key -') for Auto {setup_num}", parse_mode="HTML")
            return
    
        if data.startswith("automated"):
            setup_num = data[-1]
            AUTO_SETUP[f"setup{setup_num}"]["key_mode"] = "auto"
            save_config()
            await query.edit_message_text(
                text=f"✅ Auto {setup_num} set to <b>Automated Key Mode</b>.\n\nChoose next action:",
                parse_mode="HTML",
                reply_markup=get_auto_keyboard(setup_num)
            )
            return
    
        if data.startswith("manual"):
            setup_num = data[-1]
            AUTO_SETUP[f"setup{setup_num}"]["key_mode"] = "manual"
            save_config()
            await query.edit_message_text(
                text=f"✅ Auto {setup_num} set to <b>Manual Key Mode</b>.\n\nChoose next action:",
                parse_mode="HTML",
                reply_markup=get_auto_keyboard(setup_num)
            )
            return
    
        if data.startswith("quote"):
            setup_num = data[-1]
            AUTO_SETUP[f"setup{setup_num}"]["style"] = "quote"
            save_config()
            await query.edit_message_text(
                text=f"✅ Auto {setup_num} set to <b>Quote Key Style</b>.\n\nChoose next action:",
                parse_mode="HTML",
                reply_markup=get_auto_keyboard(setup_num)
            )
            return
    
        if data.startswith("mono"):
            setup_num = data[-1]
            AUTO_SETUP[f"setup{setup_num}"]["style"] = "mono"
            save_config()
            await query.edit_message_text(
                text=f"✅ Auto {setup_num} set to <b>Mono Key Style</b>.\n\nChoose next action:",
                parse_mode="HTML",
                reply_markup=get_auto_keyboard(setup_num)
            )
            return
    
        if data.startswith("on"):
            setup_num = data[-1]
            AUTO_SETUP[f"setup{setup_num}"]["enabled"] = True
            save_config()
            await query.edit_message_text(
                text=f"✅ Auto {setup_num} has been <b>Turned ON</b>.\n\nChoose next action:",
                parse_mode="HTML",
                reply_markup=get_auto_keyboard(setup_num)
            )
            return
    
        if data.startswith("off"):
            setup_num = data[-1]
            AUTO_SETUP[f"setup{setup_num}"]["enabled"] = False
            save_config()
            await query.edit_message_text(
                text=f"⛔ Auto {setup_num} has been <b>Turned OFF</b>.\n\nChoose next action:",
                parse_mode="HTML",
                reply_markup=get_auto_keyboard(setup_num)
            )
            return
        
        if data == "auto4_menu":
            keyboard = [
                [InlineKeyboardButton("📡 Set Source", callback_data="setsource4"),
                 InlineKeyboardButton("🎯 Set Destination", callback_data="setdest4")],
                [InlineKeyboardButton("✍️ Set Caption", callback_data="setdestcaption4")],
                [InlineKeyboardButton("🤖 Automated", callback_data="automated4"),
                 InlineKeyboardButton("🧠 Key Manual", callback_data="manual4")],
                [InlineKeyboardButton("📌 Quote Key", callback_data="quote4"),
                 InlineKeyboardButton("🔤 Mono Key", callback_data="mono4")],
                [InlineKeyboardButton("✅ On", callback_data="on4"),
                 InlineKeyboardButton("⛔ Off", callback_data="off4")],
                [InlineKeyboardButton("👁️ View Setup", callback_data="viewsetup4"),
                 InlineKeyboardButton("🧹 Reset Setup", callback_data="resetsetup4")],
                [InlineKeyboardButton("🔙 Back to Auto Menu", callback_data="method_3")]
            ]
            await query.edit_message_text(
                text="⚙️ <b>Auto 4 Config</b>\nSelect an option to configure:",
                parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
            return
        
        if data.startswith("viewsetup"):
            setup_num = data[-1]
            s = AUTO_SETUP.get(f"setup{setup_num}", {})
        
            total_keys = s.get("completed_count", 0)
            total_apks = s.get("processed_count", total_keys)  # fallback
            source = s.get("source_channel", "Not Set")
            dest = s.get("dest_channel", "Not Set")
            caption_ok = "✅" if s.get("dest_caption") else "❌"
            key_mode = s.get("key_mode", "auto").capitalize()
            style = s.get("style", "mono").capitalize()
            status = "✅ ON" if s.get("enabled") else "⛔ OFF"
        
            msg = (
                f"<pre>"
                f"┌──── AUTO {setup_num} SYSTEM DIAG ─────┐\n"
                f"│ SOURCE        >>  {source}\n"
                f"│ DESTINATION   >>  {dest}\n"
                f"│ CAPTION       >>  {caption_ok}\n"
                f"│ KEY_MODE      >>  {key_mode}\n"
                f"│ STYLE         >>  {style}\n"
                f"│ STATUS        >>  {status}\n"
                f"│ KEYS_SENT     >>  {total_keys}\n"
                f"│ TOTAL_APKS    >>  {total_apks} APK{'s' if total_apks != 1 else ''}\n"
                f"└──────── END OF REPORT ────────┘"
                f"</pre>"
            )
        
            await query.edit_message_text(
                text=msg,
                parse_mode="HTML",
                reply_markup=get_auto_keyboard(setup_num)
            )
            return
    
        if data.startswith("resetsetup"):
            setup_num = data[-1]
            AUTO_SETUP[f"setup{setup_num}"] = {
                "source_channel": "",
                "dest_channel": "",
                "dest_caption": "",
                "key_mode": "auto",
                "style": "mono",
                "enabled": False,
                "completed_count": 0,
                "processed_count": 0,
                "last_key": ""
            }
            save_config()
        
            msg = (
                f"<pre>"
                f"┌──── AUTO {setup_num} SYSTEM RESET ─────┐\n"
                f"│ STATUS       >>  RESET COMPLETE        │\n"
                f"│ ALL VALUES   >>  CLEARED               │\n"
                f"│ MODE         >>  AUTO                  │\n"
                f"│ STYLE        >>  MONO                  │\n"
                f"└───────RESET DONE──────────┘"
                f"</pre>"
            )
        
            await query.edit_message_text(
                text=msg,
                parse_mode="HTML",
                reply_markup=get_auto_keyboard(setup_num)
            )
            return
    
        # --- Check user session ---
        if user_id not in USER_STATE:
            await query.edit_message_text(
                "⏳ *Session expired or invalid!* ❌\nPlease restart using /start.",
                parse_mode="Markdown"
            )
            return
    
        state = USER_STATE[user_id]
        channel_id = USER_DATA.get(str(user_id), {}).get("channel")
    
        # --- Set Channel or Caption ---
        if data == "set_channel":
            USER_STATE[user_id]["status"] = "waiting_channel"
        
            keyboard = []
            if BOT_ADMIN_LINK:
                keyboard.append([InlineKeyboardButton("👨‍💻 Bot Admin", url=BOT_ADMIN_LINK)])
        
            await query.edit_message_text(
                "📡 <b>Please send your Channel ID now!</b>\n"
                "Example: <code>@yourchannel</code> or <code>-100xxxxxxxxxx</code>\n\n"
                "⚠️ Make sure the bot is added as ADMIN in that channel!",
                parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup(keyboard) if keyboard else None
            )
            return
    
        if data == "set_caption":
            USER_STATE[user_id]["status"] = "waiting_caption"
            await query.edit_message_text(
                "📝 *Please send your Caption now!* Must contain: `Key -`",
                parse_mode="Markdown"
            )
            return
    
        # --- Method 1 Selected ---
        if data == "method_1":
            USER_STATE.setdefault(user_id, {})["current_method"] = "method1"
            USER_STATE[user_id]["status"] = "normal"
        
            user_data = USER_DATA.get(str(user_id), {})
            channel = user_data.get("channel", "❌ Not Set")
            caption = user_data.get("caption", "❌ Not Set")
        
            text = (
                "<b>⚙️ 𝐌𝐄𝐓𝐇𝐎𝐃 𝟏 𝐒𝐄𝐋𝐄𝐂𝐓𝐄𝐃</b>\n"
                "<blockquote>━━━━━━━━━━━━━━━━━━━━━━\n\n"
                "<b>𝗬𝗼𝘂𝗿 𝗖𝗵𝗮𝗻𝗻𝗲𝗹 📡</b>\n"
                f"{channel}\n\n"
                "<b>𝗬𝗼𝘂𝗿 𝗖𝗮𝗽𝘁𝗶𝗼𝗻 📝</b>\n\n"
                f"{caption}\n"
                "━━━━━━━━━━━━━━━━━━━━━━</blockquote>\n"
                "<b>🧠 Details:</b>\n"
                "<i>• Auto-Key detection from your APK</i>\n"
                "<i>• Channel & Caption required</i>"
            )
        
            await query.edit_message_text(
                text=text,
                parse_mode="HTML",
                reply_markup=generate_method_keyboard(user_id)
            )
            return
        
        # --- Method 2 Selected ---
        elif data == "method_2":
            USER_STATE.setdefault(user_id, {})["current_method"] = "method2"
            USER_STATE[user_id]["status"] = "normal"
        
            user_data = USER_DATA.get(str(user_id), {})
            channel = user_data.get("channel", "❌ Not Set")
            caption = user_data.get("caption", "❌ Not Set")
        
            text = (
                "<b>⚙️ 𝐌𝐄𝐓𝐇𝐎𝐃 𝟐 𝐒𝐄𝐋𝐄𝐂𝐓𝐄𝐃</b>\n"
                "<blockquote>━━━━━━━━━━━━━━━━━━━━━━\n\n"
                "<b>𝗬𝗼𝘂𝗿 𝗖𝗵𝗮𝗻𝗻𝗲𝗹 📡</b>\n"
                f"{channel}\n\n"
                "<b>𝗬𝗼𝘂𝗿 𝗖𝗮𝗽𝘁𝗶𝗼𝗻 📝</b>\n\n"
                f"{caption}\n"
                "━━━━━━━━━━━━━━━━━━━━━━</blockquote>\n"
                "<b>🧠 Details:</b>\n"
                "• Upload 2–3 APKs in batch\n"
                "• Channel & Caption required"
            )
        
            await query.edit_message_text(
                text=text,
                parse_mode="HTML",
                reply_markup=generate_method_keyboard(user_id)
            )
            return

        elif data == "reset_channel":
            old_channel = USER_DATA.get(str(user_id), {}).get("channel", "N/A")
            USER_DATA[str(user_id)]["channel"] = None
            save_config()
            await query.edit_message_text(
                f"<b>𝗬𝗼𝘂𝗿 𝗖𝗵𝗮𝗻𝗻𝗲𝗹 𝗥𝗲𝘀𝗲𝘁 𝗗𝗼𝗻𝗲 ✅!</b>\n\n<blockquote>𝗬𝗼𝘂𝗿 𝗣𝗿𝗲𝘃𝗶𝗼𝘂𝘀 𝗖𝗵𝗮𝗻𝗻𝗲𝗹 𝗛𝗲𝗿𝗲 📈\n\n<code>{old_channel}</code></blockquote>",
                parse_mode="HTML",
                reply_markup=generate_method_keyboard(user_id)
            )
            return
        
        elif data == "reset_caption":
            old_caption = USER_DATA.get(str(user_id), {}).get("caption", "N/A")
            USER_DATA[str(user_id)]["caption"] = None
            save_config()
            await query.edit_message_text(
                f"<b>𝗬𝗼𝘂𝗿 𝗖𝗮𝗽𝘁𝗶𝗼𝗻 𝗥𝗲𝘀𝗲𝘁 𝗗𝗼𝗻𝗲 👋🏼!</b>\n\n<blockquote>𝗬𝗼𝘂𝗿 𝗣𝗿𝗲𝘃𝗶𝗼𝘂𝘀 𝗖𝗮𝗽𝘁𝗶𝗼𝗻 𝗛𝗲𝗿𝗲 📈\n\n<code>{old_caption}</code></blockquote>",
                parse_mode="HTML",
                reply_markup=generate_method_keyboard(user_id)
            )
            return

        if data == "share_yes":
            pending = USER_STATE.get(user_id, {}).pop("pending_apk", None)
            if not pending:
                await query.answer("❌ No APK to send.", show_alert=True)
                return
        
            try:
                result = await context.bot.send_document(
                    chat_id=pending["channel"],
                    document=pending["file_id"],
                    caption=pending["caption"],
                    parse_mode="HTML"
                )
        
                # Update method1 stats
                update_user_stats(user_id, method="method1", apks=1, keys=1)
                save_state()
        
                # Save last post info for deletion
                USER_STATE[user_id]["last_post"] = {
                    "channel": pending["channel"],
                    "msg_id": result.message_id
                }
        
                # Build post link
                channel_id_str = str(pending["channel"])
                if channel_id_str.startswith("-100"):
                    post_link = f"https://t.me/c/{channel_id_str[4:]}/{result.message_id}"
                else:
                    post_link = f"https://t.me/{channel_id_str.strip('@')}/{result.message_id}"
        
                # Confirmation UI
                keyboard = [
                    [InlineKeyboardButton("🔗 View Post", url=post_link)],
                    [InlineKeyboardButton("🗑️ Delete Apk", callback_data="delete_last")]
                ]
                await query.edit_message_text(
                    "<b>𝐏𝐨𝐬𝐭𝐞𝐝 𝐘𝐨𝐮𝐫 𝐂𝐡𝐚𝐧𝐧𝐞𝐥 🔖</b>",
                    parse_mode="HTML",
                    reply_markup=InlineKeyboardMarkup(keyboard)
                )
        
            except Exception as e:
                await query.answer("❌ Failed to post APK!", show_alert=True)
                await notify_owner_on_error(context.bot, e, source="share_yes_posting")
        
        elif data == "share_no":
            USER_STATE.get(user_id, {}).pop("pending_apk", None)
            await query.edit_message_text("❌ APK send cancelled.")
            return
        
        elif data == "delete_last":
            last = USER_STATE.get(user_id, {}).get("last_post")
            if last:
                try:
                    await context.bot.delete_message(chat_id=last["channel"], message_id=last["msg_id"])
                    await query.edit_message_text("🗑️ <b>Last post deleted!</b>", parse_mode="HTML")
                except Exception as e:
                    await query.answer("❌ Failed to delete post!", show_alert=True)
                    await notify_owner_on_error(context.bot, e, source="delete_last")
            else:
                await query.answer("⚠️ No post to delete.", show_alert=True)
        
        if data == "method2_yes":
            await method2_send_to_channel(user_id, context)
            return
    
        if data == "method2_no":
            USER_STATE[user_id]["session_files"] = []
            USER_STATE[user_id]["session_filenames"] = []
            await query.edit_message_text("❌ *Session canceled!*", parse_mode="Markdown")
            return
    
        if data == "method2_quote":
            USER_STATE[user_id]["key_mode"] = "quote"
            await method2_convert_quote(user_id, context)
            return
        
        if data == "method2_mono":
            USER_STATE[user_id]["key_mode"] = "mono"
            await method2_convert_mono(user_id, context)
            return
    
        if data == "method2_edit":
            USER_STATE[user_id]["status"] = "waiting_new_caption"
            await query.edit_message_text(
                "📝 *Send new Caption now!* (Must include `Key -`)",
                parse_mode="Markdown"
            )
            return
    
        if data == "method2_preview":
            await method2_show_preview(user_id, context)
            return
        
        if data == "auto_recaption":
            await auto_recaption(user_id, context)
            return
        
        if data == "auto_last_caption":
            await auto_last_caption(user_id, context)
            return
        
        if data == "last_caption_key":
            await last_caption_key(user_id, context)
            return

        if data == "key_after_apks":
            await key_after_apks(user_id, context)
            return
        
        if data == "caption_plus_key":
            await caption_plus_key(user_id, context)
            return
        
        if query.data == "fresh_session":
            await erase_all_session(user_id, context)
            await query.edit_message_text("✅ Session reset. Please send APKs again.")
        
        if data == "erase_all":
            await erase_all_session(user_id, context)
            await query.edit_message_text(
                text="🧹 <b>Session Erased!</b>\nYou can now send new APKs.",
                parse_mode="HTML"
            )
            return
        
        if data == "erase_all_session":
            user_id = update.callback_query.from_user.id
    
            # Run full session cleanup
            await erase_all_session(user_id, context)
    
            # Send confirmation
            try:
                await update.callback_query.edit_message_text(
                    "🧹 <b>Your session has been erased!</b>",
                    parse_mode="HTML"
                )
            except:
                await context.bot.send_message(
                    chat_id=user_id,
                    text="🧹 <b>Your session has been erased!</b>",
                    parse_mode="HTML"
                )

        if data == "back_to_manage_post":
            buttons = [
                [InlineKeyboardButton("📄 Open Last Uploaded Post", url=USER_STATE[user_id]["last_post_link"])],
                [InlineKeyboardButton("🗑️ Remove Uploaded Files", callback_data="delete_apk_post")],
                [InlineKeyboardButton("🧹 Clear This Session", callback_data="erase_all")],
                [InlineKeyboardButton("🔙 Back to Upload Options", callback_data="back_to_methods")]
            ]
        
            await context.bot.edit_message_text(
                chat_id=user_id,
                message_id=USER_STATE[user_id]["preview_message_id"],
                text="<b>✅ 𝗠𝟮 - 𝗦𝗘𝗦𝗦𝗜𝗢𝗡 𝗠𝗘𝗡𝗨</b>",
                parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup(buttons)
            )
            return

        if data == "back_to_manage_post":
            buttons = [
                [InlineKeyboardButton("📄 Open Last Uploaded Post", url=USER_STATE[user_id]["last_post_link"])],
                [InlineKeyboardButton("🗑️ Remove Uploaded Files", callback_data="delete_apk_post")],
                [InlineKeyboardButton("🧹 Clear This Session", callback_data="erase_all")],
                [InlineKeyboardButton("🔙 Back to Upload Options", callback_data="back_to_methods")]
            ]
        
            await context.bot.edit_message_text(
                chat_id=user_id,
                message_id=USER_STATE[user_id]["preview_message_id"],
                text="<b>✅ 𝗠𝟮 - 𝗦𝗘𝗦𝗦𝗜𝗢𝗡 𝗠𝗘𝗡𝗨</b>",
                parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup(buttons)
            )
            return

        if data == "delete_apk_post":
            apk_posts = USER_STATE.get(user_id, {}).get("apk_posts", [])
            filenames = USER_STATE.get(user_id, {}).get("last_post_session", {}).get("filenames", [])
            preview_id = USER_STATE.get(user_id, {}).get("preview_message_id")
        
            if not preview_id:
                await context.bot.send_message(chat_id=user_id, text="⚠️ Preview message not found.")
                return
        
            if not apk_posts or not filenames:
                await context.bot.send_message(chat_id=user_id, text="⚠️ No uploaded APKs to delete.")
                return
        
            from html import escape
            keyboard = []
            for idx, name in enumerate(filenames):
                short_name = name if len(name) <= 20 else f"{name[:17]}..."
                short_name = escape(short_name)
                keyboard.append([InlineKeyboardButton(f"🗑️ Delete {short_name}", callback_data=f"delete_apk_{idx+1}")])
        
            keyboard.append([InlineKeyboardButton("🔙 Back", callback_data="back_to_manage_post")])
        
            try:
                await context.bot.edit_message_text(
                    chat_id=user_id,
                    message_id=preview_id,
                    text="🗂 <b>Select the APK to delete by name:</b>",
                    parse_mode="HTML",
                    reply_markup=InlineKeyboardMarkup(keyboard)
                )
            except BadRequest as e:
                if "message to edit not found" in str(e).lower():
                    USER_STATE[user_id]["preview_message_id"] = None  # clean state
                    await context.bot.send_message(
                        chat_id=user_id,
                        text="⚠️ The previous preview message could not be edited (it may have been deleted).\nStarting fresh..."
                    )
                else:
                    raise
        
        
        elif data.startswith("delete_apk_"):
            apk_number = int(data.split("_")[-1])
            state = USER_STATE.setdefault(user_id, {})
            session = state.setdefault("last_post_session", {})
            apk_posts = state.get("apk_posts", [])
            filenames = session.get("filenames", [])
            channel_id = USER_DATA.get(str(user_id), {}).get("channel")
        
            if not apk_posts or not filenames or apk_number > len(apk_posts):
                await query.edit_message_text("⚠️ No uploaded APKs to delete.")
                return
        
            msg_id = apk_posts[apk_number - 1]
            filename = filenames[apk_number - 1]
        
            try:
                await context.bot.delete_message(chat_id=channel_id, message_id=msg_id)
            except Exception as e:
                print(f"[Delete Failed] {e}")
        
            # Remove specific item
            apk_posts[apk_number - 1] = None
            filenames[apk_number - 1] = None
        
            apk_posts = [m for m in apk_posts if m]
            filenames = [f for f in filenames if f]
        
            state["apk_posts"] = apk_posts
            session["filenames"] = filenames
        
            if not apk_posts:
                # Collect deleted names before clearing
                deleted_names = [name for name in session.get("filenames", []) if name]
            
                # Reset session
                state.update({
                    "session_files": [],
                    "session_filenames": [],
                    "saved_key": None,
                    "apk_posts": [],
                    "last_apk_time": None,
                    "waiting_key": False,
                    "preview_message_id": None
                })
                session.clear()
            
                # Build formatted deleted file list
                name_list = "\n".join([f"• 🗑️ <code>{name}</code>" for name in deleted_names]) or "—"
            
                await query.edit_message_text(
                    text=(
                        "<b>✅ ALL APKs DELETED SUCCESSFULLY!</b>\n"
                        "<blockquote>\n"
                        "🧾 <b>Files Removed:</b>\n"
                        f"{name_list}\n"
                        "━━━━━━━━━━━━━━━━━━━\n"
                        "🧹 Session has been reset.\n"
                        "You can now upload new APKs freely.\n"
                        "</blockquote>"
                    ),
                    parse_mode="HTML",
                    reply_markup=InlineKeyboardMarkup([
                        [InlineKeyboardButton("Clear Cache 🔖", callback_data="erase_all_session")]
                    ])
                )
                return
        
            # Updated delete menu
            from html import escape
            keyboard = []
            for idx, name in enumerate(filenames):
                if not name:
                    continue
                short = name if len(name) <= 20 else f"{name[:17]}..."
                short = escape(short)
                keyboard.append([InlineKeyboardButton(f"🗑️ Delete {short}", callback_data=f"delete_apk_{idx+1}")])
            keyboard.append([InlineKeyboardButton("🔙 Back", callback_data="back_to_manage_post")])
        
            await query.edit_message_text(
                text=(
                    "✅ <b>APK Deleted:</b> <code>{filename}</code>\n"
                    "<blockquote>"
                    "🗂 <b>Select another APK below to delete:</b>\n"
                    "Tap the filename button to remove it from the channel.\n"
                    "</blockquote>"
                ).format(filename=filename),
                parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
            return
        
        if data == "method2_back_fullmenu":
            preview_message_id = USER_STATE.get(user_id, {}).get("preview_message_id")
            key = USER_STATE.get(user_id, {}).get("saved_key", "")
            session_files = USER_STATE.get(user_id, {}).get("session_files", [])
        
            if not preview_message_id or not key or not session_files:
                await query.edit_message_text(
                    text="⚠️ *Session expired or not found!*",
                    parse_mode="Markdown"
                )
                return
        
            try:
                text = (
                    "<pre>=== METHOD 2 MENU ===</pre>\n\n"
                    "Choose what you want to do next:"
                )
            
                await context.bot.edit_message_text(
                    chat_id=user_id,
                    message_id=preview_message_id,
                    text=text,
                    parse_mode="HTML",
                    reply_markup=build_method2_buttons(user_id)
                )
            
            except Exception as e:
                print(f"Error going back to Full Menu: {e}")
    
        if data.startswith("auto") and data.endswith("_menu"):
            setup_num = data[4]  # auto1 → "1", auto2 → "2", auto3 → "3"
        
            keyboard = [
                [
                    InlineKeyboardButton("📡 Set Source", callback_data=f"setsource{setup_num}"),
                    InlineKeyboardButton("🎯 Set Destination", callback_data=f"setdest{setup_num}")
                ],
                [
                    InlineKeyboardButton("✍️ Set Caption", callback_data=f"setdestcaption{setup_num}")
                ],
                [
                    InlineKeyboardButton("🤖 Automated", callback_data=f"automated{setup_num}"),
                    InlineKeyboardButton("🧠 Key Manual", callback_data=f"manual{setup_num}")
                ],
                [
                    InlineKeyboardButton("📌 Quote Key", callback_data=f"quote{setup_num}"),
                    InlineKeyboardButton("🔤 Mono Key", callback_data=f"mono{setup_num}")
                ],
                [
                    InlineKeyboardButton("✅ On", callback_data=f"on{setup_num}"),
                    InlineKeyboardButton("⛔ Off", callback_data=f"off{setup_num}")
                ],
                [
                    InlineKeyboardButton("👁️ View Setup", callback_data=f"viewsetup{setup_num}"),
                    InlineKeyboardButton("🧹 Reset Setup", callback_data=f"resetsetup{setup_num}")
                ],
                [
                    InlineKeyboardButton("🔙 Back to Auto Menu", callback_data="method_3")
                ]
            ]
        
            await query.edit_message_text(
                text=f"⚙️ <b>Auto {setup_num} Config</b>\nSelect an option to configure:",
                parse_mode="HTML",  
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
            return
        
        if query.data == "method2_confirm_apks":
            task = state.get("countdown_task")
            if task and not task.done():
                task.cancel()
        
            if state.get("countdown_msg_id"):
                try:
                    await context.bot.delete_message(chat_id=user_id, message_id=state["countdown_msg_id"])
                except:
                    pass
                state["countdown_msg_id"] = None
        
            state["waiting_key"] = True
            state["countdown_task"] = None
        
            await context.bot.send_message(
                chat_id=user_id,
                text=(
                    "<pre>"
                    "▌ 𝐌𝐄𝐓𝐇𝐎𝐃 𝟐 𝐒𝐘𝐒𝐓𝐄𝐌 ▌\n"
                    "▶ Send your Key Now\n"
                    "▶ Used for all Mods , Loaders\n"
                    "────────────────────"
                    "</pre>"
                ),
                parse_mode="HTML"
            )
        
        elif query.data == "method2_cancel_session":
            task = state.get("countdown_task")
            if task and not task.done():
                task.cancel()
    
            if state.get("countdown_msg_id"):
                try:
                    await context.bot.delete_message(chat_id=user_id, message_id=state["countdown_msg_id"])
                except:
                    pass
                state["countdown_msg_id"] = None
    
            state.update({
                "session_files": [],
                "session_filenames": [],
                "saved_key": None,
                "waiting_key": False,
                "key_prompt_sent": False,
                "countdown_task": None,
                "progress_message_id": None,
                "last_apk_time": None,
                "quote_applied": False,
                "mono_applied": False,
                "key_mode": "normal",
                "preview_message_id": None,
                "apk_posts": [],
                "last_post_link": None,
                "last_post_session": {}
            })
    
            await context.bot.send_message(
                chat_id=user_id,
                text="❌ <b>Session cancelled. All APKs cleared.</b>",
                parse_mode="HTML"
            )

    except Exception as e:
        await notify_owner_on_error(context.bot, e, source="handle_callback")

async def send_broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        user_id = update.effective_user.id
        session = BROADCAST_SESSION.get(user_id)

        if not session or "message" not in session:
            await update.callback_query.edit_message_text(
                "⚠️ No message found to broadcast.",
                parse_mode="Markdown"
            )
            return

        msg = session["message"]
        buttons_raw = session.get("buttons_raw")
        keyboard = parse_buttons_grid_2x2(buttons_raw) if buttons_raw else None

        user_ids = [int(uid) for uid in USER_DATA.keys() if int(uid) != OWNER_ID]
        total = len(user_ids)
        sent = 0
        failed = 0
        sent_users = []
        failed_users = []

        # Delete the preview message before starting broadcast
        try:
            await update.callback_query.message.delete()
        except:
            pass

        # Loop through users and send
        for uid in user_ids:
            user_info = USER_DATA.get(str(uid), {})
            uname = user_info.get("username", "—")

            try:
                if msg.text:
                    await context.bot.send_message(
                        chat_id=uid, text=msg.text, parse_mode="HTML", reply_markup=keyboard
                    )
                elif msg.photo:
                    await context.bot.send_photo(
                        chat_id=uid, photo=msg.photo[-1].file_id,
                        caption=msg.caption, parse_mode="HTML", reply_markup=keyboard
                    )
                elif msg.document:
                    await context.bot.send_document(
                        chat_id=uid, document=msg.document.file_id,
                        caption=msg.caption, parse_mode="HTML", reply_markup=keyboard
                    )
                elif msg.video:
                    await context.bot.send_video(
                        chat_id=uid, video=msg.video.file_id,
                        caption=msg.caption, parse_mode="HTML", reply_markup=keyboard
                    )
                else:
                    continue

                sent += 1
                sent_users.append(
                    f"👤 User: {uid}\n"
                    f"├─ 🧬 Username: @{uname if uname != '—' else 'N/A'}\n"
                    f"└─ 🩺 Status: ✅ Active"
                )

            except Forbidden:
                failed += 1
                failed_users.append(
                    f"👤 User: {uid}\n"
                    f"├─ 🧬 Username: @{uname if uname != '—' else 'N/A'}\n"
                    f"└─ 🩺 Status: ❌ Blocked"
                )
            except Exception:
                failed += 1
                failed_users.append(
                    f"👤 User: {uid}\n"
                    f"├─ 🧬 Username: @{uname if uname != '—' else 'N/A'}\n"
                    f"└─ 🩺 Status: ⚠️ Error"
                )

            await asyncio.sleep(0.05)  # Throttle delay to prevent Timeouts

        # Summary report
        now = datetime.now(ZoneInfo("Asia/Kolkata"))
        date_str = now.strftime("%d-%m-%Y")
        time_str = now.strftime("%I:%M %p")

        summary = (
            "<pre>█ SYSTEM STATUS █\n"
            f"✔ SENT    : {sent}\n"
            f"✖ FAILED  : {failed}\n"
            f"☰ TOTAL   : {sent + failed}\n"
            f"⏱ TIME    : {time_str}\n"
            f"📅 DATE    : {date_str}\n"
            "</pre>"
            "<code>✔ SYNC COMPLETE — NO ERRORS</code>\n\n"
        )

        if sent_users:
            summary += "━━━━━━━━━━━━━━━━━━━━━━━━\n✅ DELIVERED USERS\n"
            for user in sent_users[:5]:
                summary += f"<blockquote>{user}</blockquote>\n"
            if len(sent_users) > 5:
                summary += f"<i>...and {len(sent_users) - 5} more.</i>\n"

        if failed_users:
            summary += "━━━━━━━━━━━━━━━━━━━━━━━━\n❌ FAILED USERS\n"
            for user in failed_users[:5]:
                summary += f"<blockquote>{user}</blockquote>\n"
            if len(failed_users) > 5:
                summary += f"<i>...and {len(failed_users) - 5} more.</i>\n"

        summary += "━━━━━━━━━━━━━━━━━━━━━━━━"

        await context.bot.send_message(
            chat_id=OWNER_ID,
            text=summary,
            parse_mode="HTML",
            disable_web_page_preview=True
        )

        # Cleanup session
        BROADCAST_SESSION.pop(user_id, None)

    except Exception as e:
        await notify_owner_on_error(context.bot, e, source="send_broadcast")

async def auto_handle_channel_post(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        if not update.channel_post:
            return
    
        message = update.channel_post
        chat_id = str(message.chat.id)
        source_username = f"@{message.chat.username}" if message.chat.username else None
        doc = message.document
        caption = message.caption or ""
    
        print(f"✅ Received channel post from {source_username or chat_id}")
    
        if not doc:
            print("❌ No document attached.")
            return
    
        if not doc.file_name.endswith(".apk"):
            print("❌ Not an APK file. Ignoring.")
            return
    
        file_size = doc.file_size
        file_size_mb = file_size / (1024 * 1024)
    
        matched_setup = None
        setup_number = None
    
        # Match Setup 1, 2, 3
        for i in range(1, 4):
            setup = AUTO_SETUP.get(f"setup{i}")
            if not setup or not setup.get("source_channel"):
                continue
    
            src = setup["source_channel"]
    
            if src.startswith("@") and source_username and src.lower() == source_username.lower():
                matched_setup = setup
                setup_number = i
                break
            elif src == chat_id:
                matched_setup = setup
                setup_number = i
                break
    
        if not matched_setup:
            await context.bot.send_message(
                chat_id=OWNER_ID,
                text="⚠️ *Alert!*\n➔ *No matching Auto Setup found for this APK!*\n⛔ *Processing Declined.*",
                parse_mode="Markdown"
            )
            print("❌ No matching setup found. Message sent to owner.")
            return
    
        if not matched_setup.get("enabled", False):
            await context.bot.send_message(
                chat_id=OWNER_ID,
                text=f"⚠️ *Alert!*\n➔ *Auto {setup_number} is currently OFF!*\n⛔ *Processing Declined.*",
                parse_mode="Markdown"
            )
            print(f"❌ Auto {setup_number} is OFF. Message sent to owner.")
            return
    
        print(f"✅ Matched to Setup {setup_number}")
    
        # Size filter
        if setup_number == 1 and not (1 <= file_size_mb <= 50):
            await context.bot.send_message(
                chat_id=OWNER_ID,
                text=f"⚠️ *Alert!*\n➔ *APK Size not matched for Auto {setup_number}*\n⛔ *Processing Declined.*",
                parse_mode="Markdown"
            )
            print("❌ Size not matched. Message sent to owner.")
            return
    
        if setup_number == 2 and not (80 <= file_size_mb <= 2048):
            await context.bot.send_message(
                chat_id=OWNER_ID,
                text=f"⚠️ *Alert!*\n➔ *APK Size not matched for Auto {setup_number}*\n⛔ *Processing Declined.*",
                parse_mode="Markdown"
            )
            print("❌ Size not matched. Message sent to owner.")
            return
    
        # Save for later deletion check
        source_chat_id = message.chat_id
        message_id = message.message_id
    
        # Initial waiting message with full bar
        countdown_msg = await context.bot.send_message(
            chat_id=OWNER_ID,
            text=f"⏳ *Auto {setup_number} - Waiting...*\n`[▰▰▰▰▰▰▰▰▰▰▱▱▱▱▱▱▱▱▱▱] (0/20)`",
            parse_mode="Markdown"
        )
    
        # Countdown loop with progress bar
        for elapsed in range(1, 21):
            await asyncio.sleep(1)
    
            # Visual bar
            filled = "▰" * elapsed
            empty = "▱" * (20 - elapsed)
            bar = filled + empty
    
            try:
                await context.bot.edit_message_text(
                    chat_id=OWNER_ID,
                    message_id=countdown_msg.message_id,
                    text=f"⏳ *Auto {setup_number} - Waiting...*\n`[{bar}] ({elapsed}/20)`",
                    parse_mode="Markdown"
                )
            except:
                pass
    
        # Check if source message still exists
        try:
            await context.bot.forward_message(chat_id=OWNER_ID, from_chat_id=source_chat_id, message_id=message_id)
            print("✅ Message exists after 20s.")
        except Exception as e:
            await context.bot.edit_message_text(
                chat_id=OWNER_ID,
                message_id=countdown_msg.message_id,
                text=f"❌ *Auto {setup_number} Declined*\n➔ *Message Deleted during 20s wait.*",
                parse_mode="Markdown"
            )
            print("❌ Message deleted during delay. Skipped.")
            return
    
        # Now Extract Key
        key_mode = matched_setup.get("key_mode", "auto")
        style = matched_setup.get("style", "mono")
        dest_caption = matched_setup.get("dest_caption", "")
        dest_channel = matched_setup.get("dest_channel", "")
    
        key = None
    
        if key_mode == "auto":
            # Step 1: Try "Key -" pattern in caption text
            match = re.search(r'Key\s*-\s*(\S+)', caption)
            if match:
                key = match.group(1)
        
            # Step 2: If not found, check for 'code' style entity (One Tap Copy)
            if not key and message.caption_entities:
                for entity in message.caption_entities:
                    if entity.type == "code":
                        offset = entity.offset
                        length = entity.length
                        key = caption[offset:offset + length]
                        break  # Stop after first match
        
        elif key_mode == "manual":
            match = re.search(r'Key\s*-\s*(\S+)', caption)
            if match:
                key = match.group(1)
    
        if not key:
            await context.bot.edit_message_text(
                chat_id=OWNER_ID,
                message_id=countdown_msg.message_id,
                text=f"❌ *Auto {setup_number} Declined*\n➔ *Key not extracted.*",
                parse_mode="Markdown"
            )
            print("❌ Key missing. Skipped.")
            return
    
        # Prepare Destination Caption
        if "Key -" not in dest_caption:
            dest_caption += "\nKey -"
    
        if style == "quote":
            final_caption = dest_caption.replace("Key -", f"<blockquote>Key - <code>{key}</code></blockquote>")
        else:  # mono
            final_caption = dest_caption.replace("Key -", f"Key - <code>{key}</code>")
    
        # Send document
        try:
            sent_msg = await context.bot.send_document(
                chat_id=dest_channel,
                document=doc.file_id,
                caption=final_caption,
                parse_mode="HTML",
                disable_notification=True
            )
    
            matched_setup["completed_count"] += 1
            save_config()
    
            # Post link generator
            if str(dest_channel).startswith("@"):
                post_link = f"https://t.me/{dest_channel.strip('@')}/{sent_msg.message_id}"
            elif str(dest_channel).startswith("-100"):
                post_link = f"https://t.me/c/{str(dest_channel)[4:]}/{sent_msg.message_id}"
            else:
                post_link = "Unknown"
    
            def escape(text):
                return re.sub(r'([_\*~`>\#+\-=|{}.!])', r'\\\1', str(text))
    
            source_name = source_username if source_username else chat_id
            source = escape(source_name)
            dest = escape(dest_channel)
            key_escape = escape(key)
            post_link_escape = escape(post_link)
    
            # Final success message
            await context.bot.edit_message_text(
                chat_id=OWNER_ID,
                message_id=countdown_msg.message_id,
                text=(
                    f"✅ *Auto {setup_number} Completed*\n"
                    f"├─ 👤 Source : {source}\n"
                    f"├─ 🎯 Destination : {dest}\n"
                    f"├─ 📡 Key : `{key_escape}`\n"
                    f"└─ 🔗 Post Link : [Click Here]({post_link_escape})"
                ),
                parse_mode="MarkdownV2",
                disable_web_page_preview=True
            )
    
            print("✅ Successfully forwarded and notified owner.")
    
        except Exception as e:
            error_message = traceback.format_exc()
            await context.bot.edit_message_text(
                chat_id=OWNER_ID,
                message_id=countdown_msg.message_id,
                text=f"❌ *Error Sending APK!*\n\n`{error_message}`",
                parse_mode="MarkdownV2"
            )
            print("❌ Error while sending document:\n", error_message)

    except Exception as e:
        await notify_owner_on_error(context.bot, e, source="auto_handle_channel_post")

async def auto4_message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        message = update.effective_message
        doc = message.document
    
        if not doc or not doc.file_name.lower().endswith(".apk"):
            return
    
        chat_id = str(update.effective_chat.id)
        source_channel = str(AUTO_SETUP["setup4"].get("source_channel"))
    
        if chat_id != source_channel or not AUTO_SETUP["setup4"].get("enabled", False):
            return
    
        caption = message.caption or ""
    
        AUTO4_STATE["pending_apks"].append({
            "file_id": doc.file_id,
            "caption": caption,
            "message_id": message.message_id,
            "chat_id": chat_id,
            "timestamp": time.time(),
            "caption_entities": message.caption_entities and [e.to_dict() for e in message.caption_entities]
        })
    
        if not AUTO4_STATE["timer"]:
            AUTO4_STATE["waiting_since"] = time.time()
            AUTO4_STATE["timer"] = asyncio.create_task(process_auto4_delayed(context))

    except Exception as e:
        await notify_owner_on_error(context.bot, e, source="auto4_message_handler")

async def process_auto4_delayed(context: ContextTypes.DEFAULT_TYPE):
    try:
        countdown_msg = await context.bot.send_message(
            OWNER_ID,
            "<b>⏳ Auto 4 - Waiting...</b>\n"
            "<code>[▰▰▰▰▰▰▰▰▰▰▱▱▱▱▱▱▱▱▱▱] (0/20)</code>",
            parse_mode="HTML"
        )

        for elapsed in range(1, 21):
            await asyncio.sleep(1)

            filled = "▰" * elapsed
            empty = "▱" * (20 - elapsed)
            bar = filled + empty

            try:
                await context.bot.edit_message_text(
                    chat_id=OWNER_ID,
                    message_id=countdown_msg.message_id,
                    text=(
                        "<b>⏳ Auto 4 - Waiting...</b>\n"
                        f"<code>[{bar}] ({elapsed}/20)</code>"
                    ),
                    parse_mode="HTML"
                )
            except Exception:
                pass

        await asyncio.sleep(1)

        source_channel = AUTO_SETUP["setup4"]["source_channel"]
        valid_apks = []

        for apk in AUTO4_STATE["pending_apks"]:
            try:
                await context.bot.forward_message(
                    chat_id=OWNER_ID,
                    from_chat_id=source_channel,
                    message_id=apk["message_id"]
                )
                valid_apks.append(apk)
            except Exception:
                pass

        if not valid_apks:
            await context.bot.edit_message_text(
                chat_id=OWNER_ID,
                message_id=countdown_msg.message_id,
                text="❌ <b>Auto 4: All APKs deleted. Declined.</b>",
                parse_mode="HTML"
            )
            return

        key = None
        setup_type = "Setup 1" if len(valid_apks) == 1 else "Setup 2"

        # Key extraction
        await asyncio.sleep(3 if setup_type == "Setup 2" else 0)
        for apk in (valid_apks[::-1] if setup_type == "Setup 2" else valid_apks):
            caption = apk["caption"]
            match = re.search(r'Key\s*-\s*(\S+)', caption)
            if match:
                key = match.group(1)
                break
            if "caption_entities" in apk:
                for entity in apk["caption_entities"]:
                    if entity["type"] == "code":
                        offset = entity["offset"]
                        length = entity["length"]
                        key = caption[offset:offset + length]
                        break
            if key:
                break

        if key:
            await send_auto4_apks(valid_apks, key, context, countdown_msg, setup_type)
        else:
            await context.bot.edit_message_text(
                chat_id=OWNER_ID,
                message_id=countdown_msg.message_id,
                text=f"❌ <b>Auto 4 {setup_type}: No key found in any APK.</b>",
                parse_mode="HTML"
            )

    except Exception as e:
        await notify_owner_on_error(context.bot, e, source="process_auto4_delayed")
        
    finally:
        AUTO4_STATE.update({
            "pending_apks": [],
            "timer": None,
            "setup_mode": 1,
            "waiting_since": None
        })
    
async def send_auto4_apks(apks, key, context: ContextTypes.DEFAULT_TYPE, countdown_msg, setup_type):
    try:
        dest_channel = AUTO_SETUP["setup4"].get("dest_channel")
        caption_template = AUTO_SETUP["setup4"].get("dest_caption")
        style = AUTO_SETUP["setup4"].get("style", "mono")
        source_channel = AUTO_SETUP["setup4"].get("source_channel")
    
        if not dest_channel or not caption_template:
            await context.bot.edit_message_text(
                chat_id=OWNER_ID,
                message_id=countdown_msg.message_id,
                text="❌ <b>Auto4: Destination channel or caption missing.</b>",
                parse_mode="HTML"
            )
            return
    
        post_link = "Unavailable"
        success_count = 0
    
        for apk in apks:
            if style == "quote":
                caption_final = f"<blockquote>Key - <code>{key}</code></blockquote>"
            else:
                caption_final = caption_template.replace("Key -", f"Key - <code>{key}</code>")
    
            try:
                msg = await context.bot.send_document(
                    chat_id=dest_channel,
                    document=apk["file_id"],
                    caption=caption_final,
                    parse_mode="HTML"
                )
                if post_link == "Unavailable":
                    post_link = f"https://t.me/c/{str(dest_channel).lstrip('-100')}/{msg.message_id}"
                success_count += 1
            except Exception as e:
                await context.bot.send_message(OWNER_ID, f"❌ Failed to send APK: <code>{e}</code>", parse_mode="HTML")
    
        AUTO_SETUP["setup4"]["completed_count"] += 1
        save_config()
    
        summary = (
            f"✅ <b>Auto 4 Completed</b>\n"
            f"├─ 👤 Source : <code>{source_channel}</code>\n"
            f"├─ 🎯 Destination : <code>{dest_channel}</code>\n"
            f"├─ 📡 Key : <code>{key}</code>\n"
            f"└─ 🔗 Post Link : <a href='{post_link}'>Click Here</a>"
        )
        
        await context.bot.edit_message_text(
            chat_id=OWNER_ID,
            message_id=countdown_msg.message_id,
            text=summary,
            parse_mode="HTML",
            disable_web_page_preview=True
        )

    except Exception as e:
        await notify_owner_on_error(context.bot, e, source="send_auto4_apks")

async def unified_auto_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = str(update.effective_chat.id)

    # AUTO 4
    setup4 = AUTO_SETUP.get("setup4", {})
    if setup4.get("enabled") and chat_id == str(setup4.get("source_channel", "")):
        await auto4_message_handler(update, context)
        return

    # AUTO 1–3
    for i in range(1, 4):
        setup = AUTO_SETUP.get(f"setup{i}", {})
        if setup.get("enabled") and chat_id == str(setup.get("source_channel", "")):
            await auto_handle_channel_post(update, context)
            return

    print(f"[AUTO] Skipped: {chat_id} not in any setup")

async def notify_owner_on_error(bot, exception: Exception, source: str = "Unknown"):
    global LAST_ERROR_TIME
    now = time.time()

    if now - LAST_ERROR_TIME < ERROR_COOLDOWN:
        return  # Avoid spamming alerts

    LAST_ERROR_TIME = now

    tb_full = "".join(traceback.format_exception(type(exception), exception, exception.__traceback__))
    tb_trimmed = "\n".join(tb_full.strip().splitlines()[-25:])  # last 25 lines of traceback

    msg = (
        f"⚠️ <b>[BOT ERROR]</b>\n"
        f"<b>📍 Source:</b> <code>{source}</code>\n"
        f"<b>📌 Error:</b> <code>{str(exception)}</code>\n"
        f"<b>🕒 Time:</b> <code>{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</code>\n\n"
        f"<b>📄 Traceback:</b>\n<pre>{tb_trimmed}</pre>"
    )

    try:
        await bot.send_message(chat_id=OWNER_ID, text=msg, parse_mode="HTML", disable_web_page_preview=True)
    except Exception as notify_error:
        print(f"[Notify Error] Owner ku msg anupala: {notify_error}")
        try:
            await bot.send_message(chat_id=OWNER_ID, text="⚠️ Bot crashed, but traceback could not be delivered.", parse_mode="HTML")
        except:
            pass

async def post_init(app: Application):
    asyncio.create_task(autosave_task())
    asyncio.create_task(schedule_stat_reports(app))

def main():
    print("[BOT] Starting application...")

    if not BOT_TOKEN:
        raise ValueError("BOT_TOKEN is not set. Please check your configuration.")

    app = Application.builder().token(BOT_TOKEN).post_init(post_init).build()

    # --- COMMAND HANDLERS ---
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("ping", ping))
    app.add_handler(CommandHandler("rules", rules))

    app.add_handler(CommandHandler("setchannelid", set_channel_id))
    app.add_handler(CommandHandler("setcaption", set_caption))
    app.add_handler(CommandHandler("resetcaption", reset_caption))
    app.add_handler(CommandHandler("resetchannelid", reset_channel))
    app.add_handler(CommandHandler("reset", reset))

    app.add_handler(CommandHandler("adduser", add_user))
    app.add_handler(CommandHandler("removeuser", remove_user))
    app.add_handler(CommandHandler("userlist", userlist))
    
    app.add_handler(CommandHandler("test8h", test_8h))
    app.add_handler(CommandHandler("testday", test_daily))
    app.add_handler(CommandHandler("testweek", test_weekly))
    app.add_handler(CommandHandler("testmonth", test_monthly))
    
    # --- CALLBACK QUERY HANDLERS ---
    app.add_handler(CallbackQueryHandler(
        handle_settings_callback,
        pattern=r"^(view_users|view_autosetup|viewsetup[1-4]|backup_config|force_reset|confirm_reset|settings_back|bot_admin_link|backup_restore|cancel_restore|confirm_restore|add_user|remove_user|reset_settings_panel)$"
    ))
    app.add_handler(CallbackQueryHandler(handle_callback))

    # --- MESSAGE HANDLERS ---

    # ZIP restore for owner
    app.add_handler(MessageHandler(
        filters.Document.FileExtension("zip") & filters.User(user_id=OWNER_ID),
        handle_backup_restore
    ))

    # Forwarded APKs from channels
    app.add_handler(MessageHandler(
        filters.ChatType.CHANNEL & filters.Document.ALL,
        unified_auto_handler
    ))

    # Manual uploads
    app.add_handler(MessageHandler(
        filters.ChatType.PRIVATE & filters.Document.ALL,
        handle_document
    ))

    # General text fallback
    app.add_handler(MessageHandler(
        filters.TEXT & (~filters.COMMAND),
        handle_text
    ))

    # --- RUN THE BOT ---
    app.run_polling()

# --- RESTART LOGIC ON CRASH ---
if __name__ == "__main__":
    while True:
        try:
            main()
        except Exception as e:
            error_head = "[MAIN LOOP]"
            print(f"[CRITICAL ERROR] Restarting Bot...\n{e}\n")
            try:
                from telegram import Bot
                bot = Bot(BOT_TOKEN)
                asyncio.run(notify_owner_on_error(bot, e, source=error_head))
            except Exception as notify_error:
                print(f"[Notify Error] Owner ku alert anupala: {notify_error}")
            print("[SYSTEM] Restarting bot in 5 seconds...")
            time.sleep(5)
            os.execl(sys.executable, sys.executable, *sys.argv)