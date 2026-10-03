Import logging
import random
import sqlite3
import os
from telegram import Update, ReplyKeyboardMarkup, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder, 
    CommandHandler, 
    MessageHandler, 
    CallbackQueryHandler,
    ContextTypes, 
    filters,
    ConversationHandler
)

TOKEN = os.getenv("BOT_TOKEN", "8945063907:AAHnGo3KeNbWPEBBZeZZKbvX7EdbrFjzc4k")
ADMIN_ID = 6499765776 
CHANNEL_USERNAME = "@gmailbuyerpayment"

DEFAULT_SELL_PRICE = 25.0  # ጂሜይል ለሚሸጡ
DEFAULT_CREATE_PRICE = 30.0 # ጂሜይል ለሚከፍቱ
REFERRAL_BONUS = 3.0

START_BANNER_URL = "https://i.ibb.co/3ykG5M0/gmail-bot-profile.jpg"
HOLD_BANNER_URL = "https://i.ibb.co/7RcxWJ0/gmail-bot-hold.jpg"

WAITING_FOR_GMAIL, WAITING_FOR_PASSWORD = range(2)
SELECT_WITHDRAW_METHOD, ENTER_WITHDRAW_DETAILS, ENTER_WITHDRAW_AMOUNT = range(2, 5)
WAITING_FOR_REJECT_REASON = 5
WAITING_FOR_ADMIN_CREDENTIALS = 6

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)

# ==================== DATABASE SETUP ====================
def get_db_connection():
    conn = sqlite3.connect('bot_data.db', timeout=10)
    conn.execute('PRAGMA journal_mode=WAL;')
    return conn

def init_db():
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            balance REAL DEFAULT 0.0,
            lang TEXT DEFAULT 'am',
            referred_by INTEGER DEFAULT NULL,
            ref_reward_given INTEGER DEFAULT 0,
            is_banned INTEGER DEFAULT 0
        )
    ''')
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS tasks (
            task_id TEXT PRIMARY KEY,
            user_id INTEGER,
            gmail TEXT,
            status TEXT DEFAULT 'Pending'
        )
    ''')
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS submitted_gmails (
            gmail TEXT PRIMARY KEY,
            user_id INTEGER,
            status TEXT
        )
    ''')
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT
        )
    ''')
    cursor.execute("INSERT OR IGNORE INTO settings (key, value) VALUES ('sell_price', ?)", (str(DEFAULT_SELL_PRICE),))
    cursor.execute("INSERT OR IGNORE INTO settings (key, value) VALUES ('create_price', ?)", (str(DEFAULT_CREATE_PRICE),))
    cursor.execute("INSERT OR IGNORE INTO settings (key, value) VALUES ('is_paused', '0')")
    conn.commit()
    conn.close()

def get_sell_price():
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT value FROM settings WHERE key = 'sell_price'")
    row = cursor.fetchone()
    conn.close()
    return float(row[0]) if row else DEFAULT_SELL_PRICE

def get_create_price():
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT value FROM settings WHERE key = 'create_price'")
    row = cursor.fetchone()
    conn.close()
    return float(row[0]) if row else DEFAULT_CREATE_PRICE

def set_price_db(key, price):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("UPDATE settings SET value = ? WHERE key = ?", (str(price), key))
    conn.commit()
    conn.close()

def get_is_paused():
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT value FROM settings WHERE key = 'is_paused'")
    row = cursor.fetchone()
    conn.close()
    return row[0] == '1' if row else False

def set_is_paused_db(paused):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("UPDATE settings SET value = ? WHERE key = 'is_paused'", ('1' if paused else '0',))
    conn.commit()
    conn.close()

def get_user(user_id):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('SELECT balance, lang, referred_by, ref_reward_given, is_banned FROM users WHERE user_id = ?', (user_id,))
    row = cursor.fetchone()
    conn.close()
    if row:
        return {'balance': row[0], 'lang': row[1], 'referred_by': row[2], 'ref_reward_given': bool(row[3]), 'is_banned': bool(row[4])}
    return None

def create_or_update_user(user_id, balance=0.0, lang='am', referred_by=None):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('''
        INSERT INTO users (user_id, balance, lang, referred_by) 
        VALUES (?, ?, ?, ?)
        ON CONFLICT(user_id) DO UPDATE SET lang=excluded.lang
    ''', (user_id, balance, lang, referred_by))
    conn.commit()
    conn.close()

def ban_unban_user(user_id, ban=True):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('UPDATE users SET is_banned = ? WHERE user_id = ?', (1 if ban else 0, user_id))
    conn.commit()
    conn.close()

def update_balance(user_id, amount_to_add):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('UPDATE users SET balance = balance + ? WHERE user_id = ?', (amount_to_add, user_id))
    conn.commit()
    conn.close()

def add_task(task_id, user_id, gmail):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('INSERT INTO tasks (task_id, user_id, gmail) VALUES (?, ?, ?)', (task_id, user_id, gmail))
    cursor.execute('INSERT OR REPLACE INTO submitted_gmails (gmail, user_id, status) VALUES (?, ?, ?)', (gmail.lower(), user_id, 'Pending'))
    conn.commit()
    conn.close()

def update_task_status(task_id, status):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('UPDATE tasks SET status = ? WHERE task_id = ?', (status, task_id))
    cursor.execute('SELECT gmail FROM tasks WHERE task_id = ?', (task_id,))
    row = cursor.fetchone()
    if row:
        gmail_val = row[0].lower()
        cursor.execute('UPDATE submitted_gmails SET status = ? WHERE gmail = ?', (status, gmail_val))
    conn.commit()
    conn.close()

def check_gmail_exists(gmail):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('SELECT status FROM submitted_gmails WHERE gmail = ?', (gmail.lower(),))
    row = cursor.fetchone()
    conn.close()
    return row[0] if row else None

def get_user_tasks(user_id):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('SELECT task_id, gmail, status FROM tasks WHERE user_id = ? ORDER BY rowid DESC LIMIT 5', (user_id,))
    rows = cursor.fetchall()
    conn.close()
    return rows

def get_all_users():
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('SELECT user_id FROM users')
    rows = cursor.fetchall()
    conn.close()
    return [r[0] for r in rows]

def set_language(user_id, lang):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('UPDATE users SET lang = ? WHERE user_id = ?', (lang, user_id))
    conn.commit()
    conn.close()

def mark_ref_reward_given(user_id):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('UPDATE users SET ref_reward_given = 1 WHERE user_id = ?', (user_id,))
    conn.commit()
    conn.close()

def get_referral_count(user_id):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('SELECT COUNT(*) FROM users WHERE referred_by = ?', (user_id,))
    count = cursor.fetchone()[0]
    conn.close()
    return count

init_db()

# ==================== TEXTS ====================
TEXTS = {
    'am': {
        'main_menu': [
            ["📧 ጂሜይል ሰራ/ሽያጭ", "📊 የኔ ስራዎች"],
            ["💳 ገንዘብ ማውጣት", "🔗 ይጋብዙና ያተርፉ"],
            ["👤 ፕሮፋይል", "🌐 ቋንቋ"],
            ["📞 እርዳታ"]
        ],
        'service_menu': [
            ["📧 ጂሜይል ለመሸጥ", "🛠 ጂሜይል ለመክፈት"],
            ["🔙 ወደ ኋላ"]
        ],
        'back_btn': "🔙 ወደ ኋላ",
        'welcome': (
            "✳️ **Task Opened! ጂሜይል በመሸጥ እና በመክፈት ገንዘብ መስራት ይጀምሩ** 🤌\n\n"
            "✅ **ጂሜይል ሲሸጡ:** `{sell_price:.2f} ETB`\n"
            "✅ **ጂሜይል ሲከፍቱ:** `{create_price:.2f} ETB` ይከፍላል!\n"
            "✅ **የሪፈራል ቦነስ:** ሰዎችን ሲጋበዙ `3.00 ETB` ያገኛሉ!\n\n"
            "✳️ **ዋና ዋና ህጎች፦**\n"
            "• Recovery Phone/Email የሌለው መሆን አለበት\n"
            "• 2-Step Verification መጥፋት አለበት\n\n"
            "✅ **ክፍያ፦** በ Telebirr እና USDT ፈጣን ክፍያ\n\n"
            "👉 **አገልግሎት ለመምረጥ ከታች '📧 ጂሜይል ሰራ/ሽያጭ' የሚለውን ይጫኑ!**\n\n"
            "📌 **የክፍያ ማረጋገጫ ቻናል:** @gmailbuyerpayment\n"
            "🎧 **እርዳታ ለማግኘት:** @Gmailbuyersupport"
        ),
        'force_join': (
            "⚠️ *ቦቱን ለመጠቀም በቅድሚያ የክፍያ ማረጋገጫ ቻናላችንን ይቀላቀሉ!*\n\n"
            "ከታች ያለውን **'📢 ቻናሉን የተቀላቀሉ'** የሚለውን ተጭነው ቻናሉን ከተቀላቀሉ በኋላ **'✅ ቼክ አድርግ'** የሚለውን ይጫኑ።"
        ),
        'choose_service_msg': "ጌታዬ እባክዎን ከታች ካሉት አማራጮች የሚፈልጉትን ይምረጡ፦",
        'sell_req': (
            "✳ **ጂሜይል ለመሸጥ የሚከተሉትን መስፈርቶች ያሟሉ፦**\n\n"
            "1️⃣ **Recovery Phone/Email** የሌለው መሆን አለበት።\n"
            "2️⃣ **2-Step Verification** የሌለው (የጠፋ) መሆን አለበት።\n"
            "3️⃣ አዲስ የተከፈተ ወይም የስራ አካውንት መሆን ይችላል።\n\n"
            "✍️ *እባክዎን አሁን የ Gmail አድራሻዎን ያስገቡ (በ @gmail.com የሚያበቃ)፦*"
        ),
        'invalid_gmail': "❌ *እባክዎን ትክክለኛ በ @gmail.com የሚያበቃ የ Gmail አድራሻ ያስገቡ!*",
        'gmail_already_submitted': "❌ *ይህ ጂሜይል ከዚህ ቀደም ተልኳል ወይም ተሸጧል! (Already Used/Sold) ሌላ ጂሜይል ያስገቡ።*",
        'invalid_password': "❌ *የተሳሳተ ፓስወርድ!*\nፓስወርዱ ቢያንስ 8 ፊደላት መሆን አለበት እንዲሁም ምንም አይነት ክፍተት (space) መያዝ የለበትም።",
        'ask_pass': "✅ **Gmail ተቀብለናል!**\n\n🔑 *አሁን ደግሞ የዚሁን Gmail ፓስወርድ (Password) ያስገቡ፦*",
        'sell_done_caption': (
            "⏳ **ጂሜይልዎ በስኬት ተቀብለናል! (HOLD)** ⏳\n\n"
            "🆔 **Task ID:** `#{task_id}`\n"
            "💵 **የሚከፈልበት መጠን:** `{price:.2f} ETB`\n"
            "-----------------------------------\n"
            "📌 **ሁኔታ፦ Hold (በመጠበቅ ላይ)**\n"
            "አካውንትዎ በአስተዳዳሪው ታይቶ እስከሚጸድቅ ድረስ በ **Hold** ላይ ይቆያል።\n\n"
            "⏱ **የማጽደቂያ ጊዜ፦** አብዛኛውን ጊዜ እስከ **3 days** ሊወስድ ይችላል።"
        ),
        'referral_info': (
            "🔗 **የእርስዎ የጋበዣ ሊንክ (Referral Link):**\n"
            "`https://t.me/{bot_username}?start={user_id}`\n\n"
            "🎁 **የቦነስ መመሪያ፦**\n"
            "በእርስዎ ሊንክ የገባ ሰው 1 ጂሜይል ሸጦ ሲጸድቅለት **{bonus:.2f} ETB** ቦነስ ወዲያውኑ ወደ ባላንስዎ ይገባል!\n\n"
            "👥 **እስካሁን የጋበዟቸው ሰዎች ብዛት፦** `{ref_count}`"
        ),
        'withdraw_no_bal': (
            "💳 **ገንዘብ ማውጫ (Withdraw)**\n\n"
            "• **የእርስዎ ባላንስ:** `{bal:.2f} ETB`\n\n"
            "⚠ *በቂ ባላንስ የለዎትም! ገንዘብ ለማውጣት ባላንስዎ ከ 0.00 ETB በላይ መሆን አለበት።*"
        ),
        'withdraw_select': "💳 **ገንዘብ ማውጫ (Withdraw)**\n\nእባክዎን ገንዘብ መቀበል የሚፈልጉበትን መንገድ ይምረጡ፦",
        'ask_telebirr': "📱 *እባክዎን የ Telebirr ስልክ ቁጥርዎን ያስገቡ፦*",
        'ask_usdt': "🔗 *እባክዎን የ USDT (BEP20) Wallet አድራሻዎን ያስገቡ፦*",
        'ask_amount': "💵 *ማውጣት የሚፈልጉትን የገንዘብ መጠን (Amount) ያስገቡ፦*",
        'invalid_amount': "❌ *እባክዎን ትክክለኛ የቁጥር መጠን ያስገቡ!*",
        'exceed_amount': "❌ *ማስገባት የሚችሉት ከባላንስዎ ({bal} ETB) እኩል ወይም በታች ብቻ ነው!*",
        'withdraw_done': (
            "✅ **የገንዘብ ማውጣት ጥያቄዎ በትክክል ተልኳል!**\n\n"
            "• **የተመረጠው መንገድ:** `{method}`\n"
            "• **መረጃ:** `{details}`\n"
            "• **የተጠየቀው መጠን:** `{amount} ETB`\n\n"
            "⏱ ጥያቄዎ ተቀብለናል፤ በቅርብ ጊዜ ገቢ ይደረጋል!"
        ),
        'profile': "👤 **የእርስዎ ፕሮፋይል (Profile)**\n\n• **ስም:** {name}\n• **ID:** `{id}`\n• **የአሁኑ ባላንስ:** `*{bal:.2f} ETB*`",
        'support': "🎧 **የእርዳታ ማዕከል (Support Team)**\n\nለማንኛውም ጥያቄ ወይም መረጃ በቴሌግራም ያግኙን፦\n👉 @Gmailbuyersupport",
        'lang_changed': "✅ **ቋንቋ ወደ አማርኛ በስኬት ተቀይሯል።**",
        'cancel': "ሂደቱ ተቋርጧል።",
        'choose_opt': "እባክዎን ከታች ካሉት አማራጭ ቁልፎች አንዱን ይምረጡ።",
        'banned_msg': "⛔ *አካውንትዎ በህግ ጥሰት ምክንያት ታግዷል (Banned)!*",
        'paused_msg': "⚠️ *ለጊዜው አዳዲስ ጂሜይሎችን መቀበል አቁመናል! እባክዎን በኋላ ላይ ይሞክሩ።*"
    },
    'en': {
        'main_menu': [
            ["📧 Gmail Services", "📊 My Tasks"],
            ["💳 Withdraw", "🔗 Invite & Earn"],
            ["👤 Profile", "🌐 Language"],
            ["📞 Support Team"]
        ],
        'service_menu': [
            ["📧 Sell Gmail", "🛠 Create Gmail"],
            ["🔙 Back"]
        ],
        'back_btn': "🔙 Back",
        'welcome': (
            "✳️ **Task Opened! Earn by selling and creating Gmail** 🤌\n\n"
            "✅ **Sell Gmail:** `{sell_price:.2f} ETB`\n"
            "✅ **Create Gmail:** `{create_price:.2f} ETB`\n"
            "✅ **Referral Bonus:** Earn `3.00 ETB` per invited user!\n\n"
            "✳️ **Main Rules:**\n"
            "• Must NOT have Recovery Phone/Email\n"
            "• 2-Step Verification must be OFF\n\n"
            "✅ **Payouts:** Fast payouts via Telebirr & USDT\n\n"
            "👉 **Click '📧 Gmail Services' below to select!**\n\n"
            "📌 **Payment Proofs:** @gmailbuyerpayment\n"
            "🎧 **Support:** @Gmailbuyersupport"
        ),
        'force_join': (
            "⚠ *To use this bot, you must join our Payment Proof channel first!*\n\n"
            "Click **'📢 Join Channel'** below and then click **'✅ Check'**."
        ),
        'choose_service_msg': "Please choose an option below:",
        'sell_req': (
            "✳️ **Requirements to Sell Gmail:**\n\n"
            "1️⃣ Must **NOT** have Recovery Phone or Recovery Email.\n"
            "2️⃣ Must **NOT** have 2-Step Verification enabled.\n"
            "3️⃣ New or clean accounts are accepted.\n\n"
            "✍️ *Please enter your Gmail address (must end with @gmail.com):*"
        ),
        'invalid_gmail': "❌ *Please enter a valid Gmail address ending with @gmail.com!*",
        'gmail_already_submitted': "❌ *This Gmail has already been submitted or sold! Please enter a different one.*",
        'invalid_password': "❌ *Invalid Password!*\nPassword must be at least 8 characters long and contain no spaces.",
        'ask_pass': "✅ **Gmail Received!**\n\n🔑 *Now please enter the Password for this Gmail:*",
        'sell_done_caption': (
            "⏳ **Gmail Received & Placed on Hold!** ⏳\n\n"
            "🆔 **Task ID:** `#{task_id}`\n"
            "💵 **Estimated Payment:** `{price:.2f} ETB`\n"
            "-----------------------------------\n"
            "📌 **Status: Hold / Pending**\n"
            "Your account is held in queue until reviewed by our admin.\n\n"
            "⏱ **Approval Time:** Usually takes up to **3 days**."
        ),
        'referral_info': (
            "🔗 **Your Referral Link:**\n"
            "`https://t.me/{bot_username}?start={user_id}`\n\n"
            "🎁 **Bonus Details:**\n"
            "You earn **{bonus:.2f} ETB** as soon as your invited user sells 1 Gmail account and gets approved!\n\n"
            "👥 **Total Referred Users:** `{ref_count}`"
        ),
        'withdraw_no_bal': (
            "💳 **Withdraw**\n\n"
            "• **Your Balance:** `{bal:.2f} ETB`\n\n"
            "⚠️ *Insufficient balance! Your balance must be greater than 0.00 ETB to withdraw.*"
        ),
        'withdraw_select': "💳 **Withdraw**\n\nPlease select your preferred withdrawal method:",
        'ask_telebirr': "📱 *Please enter your Telebirr Phone Number:*",
        'ask_usdt': "🔗 *Please enter your USDT (BEP20) Wallet Address:*",
        'ask_amount': "💵 *Enter the amount you wish to withdraw:*",
        'invalid_amount': "❌ *Please enter a valid number!*",
        'exceed_amount': "❌ *You cannot withdraw more than your current balance ({bal} ETB)!*",
        'withdraw_done': (
            "✅ **Withdrawal Request Submitted!**\n\n"
            "• **Method:** `{method}`\n"
            "• **Details:** `{details}`\n"
            "• **Amount:** `{amount} ETB`\n\n"
            "⏱ Your request is being processed!"
        ),
        'profile': "👤 **Your Profile**\n\n• **Name:** {name}\n• **ID:** `{id}`\n• **Current Balance:** `*{bal:.2f} ETB*`",
        'support': "🎧 **Support Team**\n\nFor any questions or support, contact us on Telegram:\n👉 @Gmailbuyersupport",
        'lang_changed': "✅ **Language has been changed to English.**",
        'cancel': "Process cancelled.",
        'choose_opt': "Please choose an option from the menu below.",
        'banned_msg': "⛔ *Your account has been banned for policy violation!*",
        'paused_msg': "⚠️ *We are temporarily not accepting new Gmails! Please try again later.*"
    }
}

LANG_KEYBOARD = [["🇪🇹 አማርኛ", "🇬🇧 English"], ["🔙 ወደ ኋላ"]]
WITHDRAW_METHODS_KEYBOARD = [["🇪🇹 ETB (Telebirr)", "🪙 USDT (BEP20)"], ["🔙 ወደ ኋላ"]]

def get_lang(user_id):
    u = get_user(user_id)
    return u['lang'] if u else 'am'

async def check_channel_join(bot, user_id):
    try:
        member = await bot.get_chat_member(chat_id=CHANNEL_USERNAME, user_id=user_id)
        return member.status in ['member', 'administrator', 'creator']
    except Exception:
        return False

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user_info = get_user(user_id)

    if user_info and user_info['is_banned']:
        await update.message.reply_text(TEXTS['am']['banned_msg'], parse_mode="Markdown")
        return

    referred_by = None
    if context.args and len(context.args) > 0:
        try:
            inviter = int(context.args[0])
            if inviter != user_id:
                referred_by = inviter
        except ValueError:
            pass

    if not user_info:
        create_or_update_user(user_id, balance=0.0, lang='am', referred_by=referred_by)
    
    lang = get_lang(user_id)

    is_joined = await check_channel_join(context.bot, user_id)
    if not is_joined:
        join_buttons = [
            [InlineKeyboardButton("📢 ቻናሉን የተቀላቀሉ / Join Channel", url=f"https://t.me/{CHANNEL_USERNAME.replace('@', '')}")],
            [InlineKeyboardButton("✅ ቼክ አድርግ / Check", callback_data="check_join_status")]
        ]
        await update.message.reply_text(
            TEXTS[lang]['force_join'],
            reply_markup=InlineKeyboardMarkup(join_buttons),
            parse_mode="Markdown"
        )
        return

    sell_p = get_sell_price()
    create_p = get_create_price()
    reply_markup = ReplyKeyboardMarkup(TEXTS[lang]['main_menu'], resize_keyboard=True)
    welcome_text = TEXTS[lang]['welcome'].format(sell_price=sell_p, create_price=create_p)

    try:
        await update.message.reply_photo(
            photo=START_BANNER_URL,
            caption=welcome_text,
            reply_markup=reply_markup,
            parse_mode="Markdown"
        )
    except Exception:
        await update.message.reply_text(welcome_text, reply_markup=reply_markup, parse_mode="Markdown")

async def check_join_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    lang = get_lang(user_id)

    is_joined = await check_channel_join(context.bot, user_id)
    if is_joined:
        await query.message.delete()
        sell_p = get_sell_price()
        create_p = get_create_price()
        reply_markup = ReplyKeyboardMarkup(TEXTS[lang]['main_menu'], resize_keyboard=True)
        welcome_text = TEXTS[lang]['welcome'].format(sell_price=sell_p, create_price=create_p)

        try:
            await context.bot.send_photo(
                chat_id=user_id,
                photo=START_BANNER_URL,
                caption=welcome_text,
                reply_markup=reply_markup,
                parse_mode="Markdown"
            )
        except Exception:
            await context.bot.send_message(
                chat_id=user_id,
                text=welcome_text,
                reply_markup=reply_markup,
                parse_mode="Markdown"
            )
    else:
        await query.message.reply_text("❌ *እባክዎን በቅድሚያ ቻናሉን ይቀላቀሉ!*", parse_mode="Markdown")

# ==================== 🛠 ሰራ/ሽያጭ ንዑስ ማውጫ ====================
async def show_service_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user_info = get_user(user_id)

    if user_info and user_info['is_banned']:
        await update.message.reply_text(TEXTS['am']['banned_msg'], parse_mode="Markdown")
        return

    lang = get_lang(user_id)
    reply_markup = ReplyKeyboardMarkup(TEXTS[lang]['service_menu'], resize_keyboard=True)
    await update.message.reply_text(TEXTS[lang]['choose_service_msg'], reply_markup=reply_markup, parse_mode="Markdown")

# ==================== 💡 ጂሜይል መክፈቻ ስርአት (እውነተኛ ኮፒ እና ዴን በተን ጋር) ====================
async def ask_create_gmail_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user_info = get_user(user_id)

    if user_info and user_info['is_banned']:
        await update.message.reply_text(TEXTS['am']['banned_msg'], parse_mode="Markdown")
        return

    lang = get_lang(user_id)
    keyboard = [
        [InlineKeyboardButton("✅ አዎ፣ መክፈት እፈልጋለሁ (Confirm)", callback_data="confirm_create_gmail")],
        [InlineKeyboardButton("❌ ተወው (Cancel)", callback_data="cancel_create_gmail")]
    ]
    
    msg_text = (
        "⚠️ **እርግጠኛ ነዎት ጂሜይል መክፈት ይፈልጋሉ?**\n\n"
        "አዝራሩን ሲጫኑ ጥያቄዎ ለአስተዳዳሪው ይላካል፤ አስተዳዳሪውም መረጃውን ይልክልዎታል።" if lang == 'am' 
        else "⚠️ **Are you sure you want to create a Gmail account?**\n\nClicking confirm will notify the admin to send you credentials."
    )
    
    await update.message.reply_text(msg_text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

async def handle_create_gmail_callbacks(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    user = query.from_user
    lang = get_lang(user_id)

    if query.data == "cancel_create_gmail":
        await query.edit_message_text("❌ ሂደቱ ተሰርዟል።" if lang == 'am' else "❌ Process cancelled.")
        return

    if query.data == "confirm_create_gmail":
        await query.edit_message_text(
            "✅ **ጥያቄዎ ለአስተዳዳሪው ተልኳል!**\n\nእባክዎን አስተዳዳሪው ኢሜል እና ፓስወርድ እስኪልክልዎ ድረስ በትዕግስት ይጠብቁ..." if lang == 'am'
            else "✅ **Your request has been sent to the admin!**\n\nPlease wait while the admin sends you credentials..."
        )

        admin_buttons = [
            [InlineKeyboardButton("📨 ጂሜይል እና ፓስወርድ ለመላክ (ጫን)", callback_data=f"sendcred_{user_id}")]
        ]
        admin_msg = (
            "🔔 **አዲስ የጂሜይል መክፈቻ ጥያቄ!**\n\n"
            f"👤 **ተጠቃሚ:** {user.first_name} (@{user.username})\n"
            f"🆔 **User ID:** `{user.id}`\n\n"
            "👉 እባክዎን ተጠቃሚው ዘንድ ኢሜል እና ፓስወርድ ለመላክ ከታች ያለውን አዝራር ይጫኑ!"
        )
        try:
            await context.bot.send_message(chat_id=ADMIN_ID, text=admin_msg, reply_markup=InlineKeyboardMarkup(admin_buttons), parse_mode="Markdown")
        except Exception as e:
            logging.error(f"ለአድሚን የመክፈቻ ጥያቄ መላክ አልተቻለም: {e}")

async def start_admin_send_credentials(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if query.from_user.id != ADMIN_ID:
        return ConversationHandler.END

    target_user_id = int(query.data.split("_")[1])
    context.user_data['credential_target_id'] = target_user_id

    await query.message.reply_text(
        f"✍️ **ለተጠቃሚ ID: `{target_user_id}` የሚላከውን የ Gmail እና Password መረጃ እዚህ ላክ (ምሳሌ፦ `email: test@gmail.com pass: 12345678`):**",
        parse_mode="Markdown"
    )
    return WAITING_FOR_ADMIN_CREDENTIALS

async def receive_admin_credentials(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return ConversationHandler.END

    target_user_id = context.user_data.get('credential_target_id')
    raw_text = update.message.text or ""

    if not target_user_id:
        await update.message.reply_text("⚠️ የተጠቃሚው መረጃ ጠፍቷል። እባክዎን እንደገና ከአዝራሩ ይጀምሩ።")
        return ConversationHandler.END

    email_val = ""
    pass_val = ""
    lines = raw_text.split("\n")
    for line in lines:
        if "email" in line.lower() or "@gmail.com" in line.lower():
            parts = line.split(":")
            if len(parts) > 1:
                email_val = parts[1].strip()
        if "pass" in line.lower() or "password" in line.lower():
            parts = line.split(":")
            if len(parts) > 1:
                pass_val = parts[1].strip()

    if not email_val:
        email_val = raw_text
    if not pass_val:
        pass_val = raw_text

    user_lang = get_lang(target_user_id)

    formatted_message = (
        "📌 **ከታች በተሰጠው መረጃ መሰረት ጂሜይል አካውንት ይክፈቱ:**\n\n"
        f"📧 **Email:** `{email_val}`\n"
        f"🔑 **Password:** `{pass_val}`\n\n"
        "🔒 **እባክዎን የተሰጠውን መረጃ በትክክል ይጠቀሙ፣ ካልሆነ ክፍያ አይፈጸምም።**\n\n"
        "👇 *ጂሜይሉን ከፍተው ሲጨርሱ ከታች ያለውን 'ጨርሻለሁ' የሚለውን በተን ይጫኑ:*"
        if user_lang == 'am' else
        "📌 **Register a Gmail account using the specified data below:**\n\n"
        f"📧 **Email:** `{email_val}`\n"
        f"🔑 **Password:** `{pass_val}`\n\n"
        "🔒 **Be sure to use the specified data, otherwise the account will not be paid.**\n\n"
        "👇 *Once you finish creating the Gmail, click the button below:*"
    )

    credentials_keyboard = [
        [
            InlineKeyboardButton("📋 Copy Email", callback_data=f"copymail_{email_val}"),
            InlineKeyboardButton("📋 Copy Password", callback_data=f"copypass_{pass_val}")
        ],
        [
            InlineKeyboardButton("✅ Done (ጨርሻለሁ)", callback_data=f"gmail_done_{target_user_id}")
        ]
    ]

    try:
        await context.bot.send_message(
            chat_id=target_user_id, 
            text=formatted_message, 
            reply_markup=InlineKeyboardMarkup(credentials_keyboard), 
            parse_mode="Markdown"
        )
        await update.message.reply_text("✅ **መረጃው በኮፒ ፖፕ-አፕ አዝራሮች እና ከ'Done' በተን ጋር ለተጠቃሚው በስኬት ተልኳል!**", parse_mode="Markdown")
    except Exception as e:
        await update.message.reply_text(f"❌ መላክ አልተቻለም: {e}")

    return ConversationHandler.END

async def handle_copy_callbacks(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    data = query.data
    if data.startswith("copymail_"):
        mail_to_copy = data.replace("copymail_", "")
        await query.answer(f"📋 Email Copied Successfully: {mail_to_copy}", show_alert=True)
    elif data.startswith("copypass_"):
        pass_to_copy = data.replace("copypass_", "")
        await query.answer(f"📋 Password Copied Successfully: {pass_to_copy}", show_alert=True)

async def handle_gmail_done_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer("✅ ጂሜይሉ መከፈቱ ተረጋግጧል!")
    
    user_id = query.from_user.id
    user = query.from_user
    user_lang = get_lang(user_id)

    if user_lang == 'en':
        success_text = (
            "✅ **Task Completed Successfully!**\n\n"
            "⏳ **Your created Gmail is now on HOLD.**\n"
            "Payment will reach your balance within **3 days** after admin verification. Thank you! 🙏"
        )
    else:
        success_text = (
            "✅ **ስራውን በስኬት አጠናቀዋል!**\n\n"
            "⏳ **ጂሜይሎቹ ሆልድ (Hold) ላይ ናቸው።**\n"
            "በሶስት ቀን ውስጥ አስተዳዳሪው አረጋግጦ ክፍያውን ወደ ባላንስዎ ይጨምረዋል። እናመሰግናለን! 🙏"
        )

    try:
        await query.edit_message_text(text=success_text, reply_markup=None, parse_mode="Markdown")
    except Exception as e:
        logging.error(f"Done edit error: {e}")

    try:
        admin_buttons = [
            [
                InlineKeyboardButton("👍 Approve (አፕሩቭ)", callback_data=f"mgmail_app_{user_id}"),
            ],
            [
                InlineKeyboardButton("❌ Wrong Password", callback_data=f"mgmail_rej_{user_id}_Wrong Password"),
                InlineKeyboardButton("❌ Can't Log In", callback_data=f"mgmail_rej_{user_id}_We Cant Login")
            ],
            [
                InlineKeyboardButton("❌ Not Created", callback_data=f"mgmail_rej_{user_id}_Gmail Not Created")
            ]
        ]
        admin_notif = (
            f"🔔 **ተጠቃሚ @{user.username} (`{user_id}`) ጂሜይል መክፈቱን በ 'Done' አረጋግጧል!**\n\n"
            "እባክዎን አካውንቱን አረጋግጠው ከታች ያሉትን አዝራሮች በመጠቀም ይወስኑ:"
        )
        await context.bot.send_message(chat_id=ADMIN_ID, text=admin_notif, reply_markup=InlineKeyboardMarkup(admin_buttons), parse_mode="Markdown")
    except Exception as e:
        logging.error(f"Admin done notif error: {e}")

async def handle_created_gmail_admin_decision(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    data = query.data
    if query.from_user.id != ADMIN_ID:
        return

    parts = data.split("_")
    action = parts[1]
    target_user_id = int(parts[2])

    if action == "app":
        await query.answer("✅ ጂሜይሉ ጸድቋል!")
        create_price = get_create_price()
        update_balance(target_user_id, create_price)

        try:
            await query.edit_message_text(text=query.message.text + "\n\n✅ **ሁኔታ፦** ጸድቋል (Approved) እና 30 ብር ክፍያ ተጨምሯል!", reply_markup=None, parse_mode="Markdown")
        except Exception:
            pass

        try:
            user_lang = get_lang(target_user_id)
            user_msg = (
                f"🎉 **Congratulations! Your created Gmail has been Approved!**\n\n"
                f"• **{create_price:.2f} ETB** has been added to your balance."
                if user_lang == 'en' else
                f"🎉 **እንኳን ደስ አለዎት! የከፈቱት ጂሜይል ጸድቋል!**\n\n"
                f"• **{create_price:.2f} ETB** ወደ ዋና ባላንስዎ ተጨምሯል።"
            )
            await context.bot.send_message(chat_id=target_user_id, text=user_msg, parse_mode="Markdown")
        except Exception:
            pass

        try:
            proof_msg = (
                f"🎉 **NEW CREATED GMAIL APPROVED!** 🎉\n\n"
                f"💰 **Paid Amount:** `{create_price:.2f} ETB`\n"
                f"✅ **Status:** Verified & Approved\n"
                f"-----------------------------------\n"
                f"🤖 **Bot:** @{(await context.bot.get_me()).username}"
            )
            await context.bot.send_message(chat_id=CHANNEL_USERNAME, text=proof_msg, parse_mode="Markdown")
        except Exception:
            pass

        target_user = get_user(target_user_id)
        if target_user and target_user['referred_by'] and not target_user['ref_reward_given']:
            inviter_id = target_user['referred_by']
            update_balance(inviter_id, REFERRAL_BONUS)
            mark_ref_reward_given(target_user_id)
            try:
                await context.bot.send_message(chat_id=inviter_id, text=f"💰 **የ {REFERRAL_BONUS:.2f} ETB ቦነስ አግኝተዋል!** (የጋበዙት ሰው የከፈተው ጂሜይል ጸድቋል)", parse_mode="Markdown")
            except Exception:
                pass

    elif action == "rej":
        reason = "_".join(parts[3:])
        await query.answer(f"❌ ውድቅ ተደርጓል: {reason}")

        try:
            await query.edit_message_text(text=query.message.text + f"\n\n❌ **ሁኔታ፦** ውድቅ ተደርጓል (ምክንያት: {reason})", reply_markup=None, parse_mode="Markdown")
        except Exception:
            pass

        try:
            user_lang = get_lang(target_user_id)
            user_msg = (
                f"❌ **Your created Gmail task was Rejected.**\nReason: {reason}"
                if user_lang == 'en' else
                f"❌ **የከፈቱት ጂሜይል ውድቅ ተደርጓል።**\nምክንያት: {reason}"
            )
            await context.bot.send_message(chat_id=target_user_id, text=user_msg, parse_mode="Markdown")
        except Exception:
            pass

async def admin_control_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return
    
    is_paused = get_is_paused()
    status_text = "⏸ ለአሁኑ ስራዎች ተዘግተዋል (Paused)" if is_paused else "🟢 ስራዎች በክፍት ላይ ናቸው (Open)"
    
    keyboard = [
        [InlineKeyboardButton("🟢 Task Open አድርግ", callback_data="admin_task_open"),
         InlineKeyboardButton("🔴 Task Close አድርግ", callback_data="admin_task_close")]
    ]
    await update.message.reply_text(
        f"🛠 **የአድሚን መቆጣጠሪያ ፓነል (Admin Panel)**\n\n• የቦቱ ሁኔታ: {status_text}",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown"
    )

async def handle_admin_control_callbacks(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if query.from_user.id != ADMIN_ID:
        return

    if query.data == "admin_task_open":
        set_is_paused_db(False)
        await query.edit_message_text("✅ **ስራዎች (Tasks) ተከፍተዋል! (Open)**", parse_mode="Markdown")
    elif query.data == "admin_task_close":
        set_is_paused_db(True)
        await query.edit_message_text("🛑 **ስራዎች (Tasks) ተዘግተዋል! (Closed)**", parse_mode="Markdown")

async def ban_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID: return
    if context.args:
        try:
            target_id = int(context.args[0])
            ban_unban_user(target_id, ban=True)
            await update.message.reply_text(f"✅ ተጠቃሚ `{target_id}` በስኬት ታግዷል (Banned)!", parse_mode="Markdown")
        except ValueError:
            await update.message.reply_text("⚠️️ እባክዎን ትክክለኛ ID ያስገቡ።")

async def unban_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID: return
    if context.args:
        try:
            target_id = int(context.args[0])
            ban_unban_user(target_id, ban=False)
            await update.message.reply_text(f"✅ የተጠቃሚ `{target_id}` እገዳ ተነስቷል!", parse_mode="Markdown")
        except ValueError:
            await update.message.reply_text("⚠ እባክዎን ትክክለኛ ID ያስገቡ።")

async def set_sell_price_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID: return
    if context.args:
        try:
            new_p = float(context.args[0])
            set_price_db('sell_price', new_p)
            await update.message.reply_text(f"✅ የጂሜይል ሽያጭ ዋጋ ወደ `{new_p:.2f} ETB` ተቀይሯል!", parse_mode="Markdown")
        except ValueError:
            await update.message.reply_text("⚠️ እባክዎን ትክክለኛ የቁጥር መጠን ያስገቡ።")

async def set_create_price_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID: return
    if context.args:
        try:
            new_p = float(context.args[0])
            set_price_db('create_price', new_p)
            await update.message.reply_text(f"✅ የጂሜይል መክፈቻ ዋጋ ወደ `{new_p:.2f} ETB` ተቀይሯል!", parse_mode="Markdown")
        except ValueError:
            await update.message.reply_text("⚠️️ እባክዎን ትክክለኛ የቁጥር መጠን ያስገቡ።")

async def broadcast_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID: return
    msg_text = " ".join(context.args)
    if not msg_text:
        await update.message.reply_text("⚠️ እባክዎን የሚላከውን መልእክት ያስገቡ።")
        return
    users = get_all_users()
    count = 0
    for uid in users:
        try:
            await context.bot.send_message(chat_id=uid, text=msg_text)
            count += 1
        except Exception: pass
    await update.message.reply_text(f"✅ መልእክቱ ለ {count} ተጠቃሚዎች ተልኳል።")

async def stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID: return
    users = get_all_users()
    await update.message.reply_text(f"📊 **የቦቱ ስታቲስቲክስ፦**\n\n• አጠቃላይ ተጠቃሚዎች: {len(users)}\n• የሽያጭ ዋጋ: {get_sell_price()} ETB\n• የመክፈቻ ዋጋ: {get_create_price()} ETB")

async def handle_direct_approve(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer("✅ በስኬት ጽድቋል!")

    data_parts = query.data.split("_")
    target_user_id = int(data_parts[1])
    task_id = data_parts[2]

    sell_price = get_sell_price()
    update_balance(target_user_id, sell_price)
    update_task_status(task_id, 'Approved')

    try:
        new_text = query.message.text + f"\n\n✅ **ተሰርቷል፦** Task #{task_id} ጽድቋል (Approved) እና 25 ብር ተጨምሯል!"
        await query.edit_message_text(text=new_text, reply_markup=None, parse_mode="Markdown")
    except Exception as e:
        logging.error(f"Edit msg error: {e}")

    try:
        user_lang = get_lang(target_user_id)
        if user_lang == 'en':
            user_msg = f"🎉 **Task #{task_id} Approved!**\n\n• **{sell_price:.2f} ETB** has been added to your main balance."
        else:
            user_msg = f"🎉 **Task #{task_id} ጽድቋል!**\n\n• **{sell_price:.2f} ETB** ወደ ዋና ባላንስዎ ተጨምሯል።"
        await context.bot.send_message(chat_id=target_user_id, text=user_msg, parse_mode="Markdown")
    except Exception as e:
        logging.error(f"Send user msg error: {e}")

    try:
        proof_msg = (
            f"🎉 **NEW APPROVED GMAIL!** 🎉\n\n"
            f"🆔 **Task ID:** `#{task_id}`\n"
            f"💰 **Paid Amount:** `{sell_price:.2f} ETB`\n"
            f"✅ **Status:** Verified & Approved\n"
            f"-----------------------------------\n"
            f"🤖 **Bot:** @{(await context.bot.get_me()).username}"
        )
        await context.bot.send_message(chat_id=CHANNEL_USERNAME, text=proof_msg, parse_mode="Markdown")
    except Exception as e:
        logging.error(f"ወደ ቻናል መላክ አልተቻለም: {e}")

    target_user = get_user(target_user_id)
    if target_user and target_user['referred_by'] and not target_user['ref_reward_given']:
        inviter_id = target_user['referred_by']
        update_balance(inviter_id, REFERRAL_BONUS)
        mark_ref_reward_given(target_user_id)
        
        inviter_lang = get_lang(inviter_id)
        if inviter_lang == 'en':
            ref_msg = f"💰 **You earned {REFERRAL_BONUS:.2f} ETB!**\nYour referred user's task (#{task_id}) was approved!"
        else:
            ref_msg = f"💰 **የ {REFERRAL_BONUS:.2f} ETB ቦነስ አግኝተዋል!**\nየጋበዙት ሰው ያስገባው አካውንት (#{task_id}) ስለጸደቀ ቦነሱ ገቢ ሆኗል!"

        try:
            await context.bot.send_message(chat_id=inviter_id, text=ref_msg, parse_mode="Markdown")
        except Exception as e:
            logging.error(f"Send referral msg error: {e}")

async def start_admin_reject(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if query.from_user.id != ADMIN_ID: return ConversationHandler.END

    data_parts = query.data.split("_")
    context.user_data['reject_target_id'] = int(data_parts[1])
    context.user_data['reject_task_id'] = data_parts[2]
    context.user_data['reject_message_id'] = query.message.message_id
    
    keyboard = [
        [InlineKeyboardButton("❌ Wrong Password (የተሳሳተ ፓስወርድ)", callback_data="rej_reason_Wrong Password")],
        [InlineKeyboardButton("❌ We Can't Log In (ሎጊን አልተቻለም)", callback_data="rej_reason_We Cant Login")],
        [InlineKeyboardButton("❌ Gmail Not Created", callback_data="rej_reason_Gmail Not Created")]
    ]
    await context.bot.send_message(
        chat_id=ADMIN_ID, 
        text=f"⚠ ለ Task #{data_parts[2]} ውድቅ የተደረገበትን ምክንያት ይምረጡ፦", 
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
    return WAITING_FOR_REJECT_REASON

async def receive_reject_reason_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if query.from_user.id != ADMIN_ID: return ConversationHandler.END

    reason = query.data.replace("rej_reason_", "")
    target_user_id = context.user_data.get('reject_target_id')
    task_id = context.user_data.get('reject_task_id')
    orig_msg_id = context.user_data.get('reject_message_id')

    update_task_status(task_id, 'Rejected')
    await query.edit_message_text(text=f"✅ Task #{task_id} ውድቅ ተደርጓል (ምክንያት: {reason})።")

    if orig_msg_id:
        try:
            new_admin_text = f"❌ **Task #{task_id} ውድቅ ተደርጓል**\nምክንያት: {reason}"
            await context.bot.edit_message_text(
                chat_id=ADMIN_ID,
                message_id=orig_msg_id,
                text=new_admin_text,
                reply_markup=None,
                parse_mode="Markdown"
            )
        except Exception as e:
            logging.error(f"Admin msg edit error: {e}")

    try:
        user_lang = get_lang(target_user_id)
        if user_lang == 'en':
            user_msg = f"❌ **Task #{task_id} Rejected.**\nReason: {reason}"
        else:
            user_msg = f"❌ **Task #{task_id} ውድቅ ተደርጓል።**\nምክንያት: {reason}"
        await context.bot.send_message(chat_id=target_user_id, text=user_msg, parse_mode="Markdown")
    except Exception as e:
        logging.error(f"ለተጠቃሚ መላክ አልተቻለም: {e}")

    return ConversationHandler.END

async def handle_withdraw_paid(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer("✅ ክፍያ መረጋገጡ ተልኳል!")

    data_parts = query.data.split("_")
    target_user_id = int(data_parts[1])
    amount = data_parts[2]

    try:
        new_text = query.message.text + f"\n\n✅ **ሁኔታ፦** ክፍያው ተፈጽሟል (Paid)!"
        await query.edit_message_text(text=new_text, reply_markup=None, parse_mode="Markdown")
    except Exception as e:
        logging.error(f"Admin withdraw edit error: {e}")

    try:
        user_lang = get_lang(target_user_id)
        if user_lang == 'en':
            user_msg = f"🎉 **Withdrawal Successful!**\n\nYour withdrawal request of **{amount} ETB** has been successfully paid and transferred to your account."
        else:
            user_msg = f"🎉 **የገንዘብ ማውጣት ጥያቄዎ ተሳክቷል!**\n\nየጠየቁት **{amount} ETB** ክፍያ ተፈጽሞ ወደ መለያዎ ገቢ ተደርጓል። እናመሰግናለን! 🙏"
        
        await context.bot.send_message(chat_id=target_user_id, text=user_msg, parse_mode="Markdown")
    except Exception as e:
        logging.error(f"Send withdraw success msg error: {e}")

async def start_sell_gmail(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user_info = get_user(user_id)

    if user_info and user_info['is_banned']:
        await update.message.reply_text(TEXTS['am']['banned_msg'], parse_mode="Markdown")
        return ConversationHandler.END

    if get_is_paused():
        lang = get_lang(user_id)
        await update.message.reply_text(TEXTS[lang]['paused_msg'], parse_mode="Markdown")
        return ConversationHandler.END

    lang = get_lang(user_id)
    markup = ReplyKeyboardMarkup([[TEXTS[lang]['back_btn']]], resize_keyboard=True)
    await update.message.reply_text(TEXTS[lang]['sell_req'], reply_markup=markup, parse_mode="Markdown")
    return WAITING_FOR_GMAIL

async def receive_gmail(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    lang = get_lang(user_id)
    text = update.message.text

    if text in ["🔙 ወደ ኋላ", "🔙 Back"]:
        return await cancel_to_main(update, context)

    email = text.strip()
    if not email.lower().endswith("@gmail.com") or " " in email:
        await update.message.reply_text(TEXTS[lang]['invalid_gmail'], parse_mode="Markdown")
        return WAITING_FOR_GMAIL

    existing_status = check_gmail_exists(email)
    if existing_status:
        await update.message.reply_text(TEXTS[lang]['gmail_already_submitted'], parse_mode="Markdown")
        return WAITING_FOR_GMAIL

    context.user_data['gmail'] = email
    markup = ReplyKeyboardMarkup([[TEXTS[lang]['back_btn']]], resize_keyboard=True)
    await update.message.reply_text(TEXTS[lang]['ask_pass'], reply_markup=markup, parse_mode="Markdown")
    return WAITING_FOR_PASSWORD

async def receive_password(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    lang = get_lang(user_id)
    text = update.message.text

    if text in ["🔙 ወደ ኋላ", "🔙 Back"]:
        return await cancel_to_main(update, context)

    gmail = context.user_data.get('gmail')
    password = text.strip()

    if len(password) < 8 or " " in password:
        await update.message.reply_text(TEXTS[lang]['invalid_password'], parse_mode="Markdown")
        return WAITING_FOR_PASSWORD

    user = update.message.from_user
    task_id = f"G{random.randint(100000, 999999)}"
    sell_price = get_sell_price()

    add_task(task_id, user_id, gmail)

    buttons = [
        [
            InlineKeyboardButton("👍 Approve (ፅድቋል)", callback_data=f"a_{user.id}_{task_id}"),
            InlineKeyboardButton("😞 Reject (ውድቅ)", callback_data=f"r_{user.id}_{task_id}")
        ]
    ]
    admin_msg = (
        f"📥 **አዲስ ጂሜይል መጥቷል (ሽያጭ)! (Task #{task_id})**\n\n"
        f"👤 **ላኪ:** {user.first_name} (@{user.username})\n"
        f"🆔 **User ID:** `{user.id}`\n\n"
        f"📧 **Gmail:** `{gmail}`\n"
        f"🔑 **Password:** `{password}`"
    )
    try:
        await context.bot.send_message(chat_id=ADMIN_ID, text=admin_msg, reply_markup=InlineKeyboardMarkup(buttons), parse_mode="Markdown")
    except Exception as e:
        logging.error(f"ለአድሚን መላክ አልተቻለም: {e}")

    caption = TEXTS[lang]['sell_done_caption'].format(task_id=task_id, price=sell_price)
    reply_markup_main = ReplyKeyboardMarkup(TEXTS[lang]['main_menu'], resize_keyboard=True)
    try:
        await update.message.reply_photo(
            photo=HOLD_BANNER_URL,
            caption=caption,
            parse_mode="Markdown"
        )
        await update.message.reply_text(TEXTS[lang]['choose_opt'], reply_markup=reply_markup_main)
    except Exception:
        await update.message.reply_text(caption, parse_mode="Markdown", reply_markup=reply_markup_main)

    return ConversationHandler.END

async def start_withdraw(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user_info = get_user(user_id)

    if user_info and user_info['is_banned']:
        await update.message.reply_text(TEXTS['am']['banned_msg'], parse_mode="Markdown")
        return ConversationHandler.END

    lang = get_lang(user_id)
    user_balance = user_info['balance'] if user_info else 0.0

    if user_balance <= 0.0:
        msg = TEXTS[lang]['withdraw_no_bal'].format(bal=user_balance)
        await update.message.reply_text(msg, parse_mode="Markdown")
        return ConversationHandler.END

    reply_markup = ReplyKeyboardMarkup(WITHDRAW_METHODS_KEYBOARD, resize_keyboard=True)
    await update.message.reply_text(TEXTS[lang]['withdraw_select'], reply_markup=reply_markup, parse_mode="Markdown")
    return SELECT_WITHDRAW_METHOD

async def select_withdraw_method(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    lang = get_lang(user_id)
    method = update.message.text

    if method in ["🔙 ወደ ኋላ", "🔙 Back"]:
        return await cancel_to_main(update, context)

    context.user_data['withdraw_method'] = method

    markup = ReplyKeyboardMarkup([[TEXTS[lang]['back_btn']]], resize_keyboard=True)
    if method in ["🇪🇹 ETB (Telebirr)", "Telebirr"]:
        await update.message.reply_text(TEXTS[lang]['ask_telebirr'], reply_markup=markup, parse_mode="Markdown")
        return ENTER_WITHDRAW_DETAILS
    elif method in ["🪙 USDT (BEP20)", "USDT (BEP20)"]:
        await update.message.reply_text(TEXTS[lang]['ask_usdt'], reply_markup=markup, parse_mode="Markdown")
        return ENTER_WITHDRAW_DETAILS
    else:
        await update.message.reply_text(TEXTS[lang]['choose_opt'])
        return SELECT_WITHDRAW_METHOD

async def enter_withdraw_details(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    lang = get_lang(user_id)
    text = update.message.text

    if text in ["🔙 ወደ ኋላ", "🔙 Back"]:
        return await cancel_to_main(update, context)

    context.user_data['withdraw_details'] = text
    markup = ReplyKeyboardMarkup([[TEXTS[lang]['back_btn']]], resize_keyboard=True)
    await update.message.reply_text(TEXTS[lang]['ask_amount'], reply_markup=markup, parse_mode="Markdown")
    return ENTER_WITHDRAW_AMOUNT

async def enter_withdraw_amount(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    lang = get_lang(user_id)
    text = update.message.text

    if text in ["🔙 ወደ ኋላ", "🔙 Back"]:
        return await cancel_to_main(update, context)

    try:
        amount = float(text)
    except ValueError:
        await update.message.reply_text(TEXTS[lang]['invalid_amount'], parse_mode="Markdown")
        return ENTER_WITHDRAW_AMOUNT

    user_data = get_user(user_id)
    user_balance = user_data['balance'] if user_data else 0.0

    if amount > user_balance or amount <= 0:
        await update.message.reply_text(TEXTS[lang]['exceed_amount'].format(bal=user_balance), parse_mode="Markdown")
        return ENTER_WITHDRAW_AMOUNT

    update_balance(user_id, -amount)
    method = context.user_data.get('withdraw_method')
    details = context.user_data.get('withdraw_details')
    user = update.message.from_user

    buttons = [
        [InlineKeyboardButton("✅ ክፍያ ፈጽሜአለሁ (Mark as Paid)", callback_data=f"wpay_{user.id}_{amount}")]
    ]

    admin_withdraw_msg = (
        "💸 **አዲስ የገንዘብ ማውጣት ጥያቄ!**\n\n"
        f"👤 **ተጠቃሚ:** {user.first_name} (@{user.username})\n"
        f"🆔 **User ID:** `{user.id}`\n"
        f"💳 **መንገድ:** {method}\n"
        f"📌 **አድራሻ/ስልክ:** `{details}`\n"
        f"💵 **መጠን:** `{amount} ETB`"
    )
    try:
        await context.bot.send_message(
            chat_id=ADMIN_ID, 
            text=admin_withdraw_msg, 
            reply_markup=InlineKeyboardMarkup(buttons), 
            parse_mode="Markdown"
        )
    except Exception as e:
        logging.error(f"ለአድሚን መላክ አልተቻለም: {e}")

    reply_markup = ReplyKeyboardMarkup(TEXTS[lang]['main_menu'], resize_keyboard=True)
    success_msg = TEXTS[lang]['withdraw_done'].format(method=method, details=details, amount=amount)
    await update.message.reply_text(success_msg, reply_markup=reply_markup, parse_mode="Markdown")
    return ConversationHandler.END

async def cancel_to_main(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    lang = get_lang(user_id)
    reply_markup = ReplyKeyboardMarkup(TEXTS[lang]['main_menu'], resize_keyboard=True)
    await update.message.reply_text("🔙 ወደ ዋናው ማውጫ ተመለሰ።", reply_markup=reply_markup)
    return ConversationHandler.END

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lang = get_lang(update.effective_user.id)
    reply_markup = ReplyKeyboardMarkup(TEXTS[lang]['main_menu'], resize_keyboard=True)
    await update.message.reply_text(TEXTS[lang]['cancel'], reply_markup=reply_markup)
    return ConversationHandler.END

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    user = update.message.from_user
    user_id = user.id

    user_info = get_user(user_id)
    if user_info and user_info['is_banned']:
        await update.message.reply_text(TEXTS['am']['banned_msg'], parse_mode="Markdown")
        return

    lang = get_lang(user_id)
    user_balance = user_info['balance'] if user_info else 0.0

    if text in ["🌐 Language", "🌐 ቋንቋ"]:
        reply_markup = ReplyKeyboardMarkup(LANG_KEYBOARD, resize_keyboard=True, one_time_keyboard=True)
        await update.message.reply_text("እባክዎ ቋንቋ ይምረጡ / Please select your language:", reply_markup=reply_markup)

    elif text == "🇪🇹 አማርኛ":
        set_language(user_id, 'am')
        reply_markup = ReplyKeyboardMarkup(TEXTS['am']['main_menu'], resize_keyboard=True)
        await update.message.reply_text(TEXTS['am']['lang_changed'], reply_markup=reply_markup, parse_mode="Markdown")

    elif text == "🇬🇧 English":
        set_language(user_id, 'en')
        reply_markup = ReplyKeyboardMarkup(TEXTS['en']['main_menu'], resize_keyboard=True)
        await update.message.reply_text(TEXTS['en']['lang_changed'], reply_markup=reply_markup, parse_mode="Markdown")

    elif text in ["🔙 ወደ ኋላ", "🔙 Back"]:
        reply_markup = ReplyKeyboardMarkup(TEXTS[lang]['main_menu'], resize_keyboard=True)
        await update.message.reply_text("🔙 ወደ ዋናው ማውጫ ተመለሰ።", reply_markup=reply_markup)

    elif text in ["👤 Profile", "👤 ፕሮፋይል"]:
        msg = TEXTS[lang]['profile'].format(name=user.first_name, id=user.id, bal=user_balance)
        await update.message.reply_text(msg, parse_mode="Markdown")

    elif text in ["📊 የኔ ስራዎች", "📊 My Tasks"]:
        tasks = get_user_tasks(user_id)
        if not tasks:
            await update.message.reply_text("የላኳቸው ስራዎች እስካሁን የሉም።" if lang == 'am' else "No submitted tasks yet.")
        else:
            msg = "📊 **የቅርብ ጊዜ ስራዎችዎ (Your Tasks):**\n\n"
            for t_id, g, st in tasks:
                icon = "⏳" if st == "Pending" else ("✅" if st == "Approved" else "❌")
                msg += f"• Task #{t_id} (`{g}`): {icon} *{st}*\n"
            await update.message.reply_text(msg, parse_mode="Markdown")

    elif text in ["🔗 ይጋብዙና ያተርፉ", "🔗 Invite & Earn"]:
        bot_info = await context.bot.get_me()
        ref_count = get_referral_count(user_id)
        msg = TEXTS[lang]['referral_info'].format(
            bot_username=bot_info.username, 
            user_id=user_id, 
            bonus=REFERRAL_BONUS, 
            ref_count=ref_count
        )
        await update.message.reply_text(msg, parse_mode="Markdown")

    elif text in ["📞 Support Team", "📞 እርዳታ"]:
        await update.message.reply_text(TEXTS[lang]['support'], parse_mode="Markdown")

    else:
        reply_markup = ReplyKeyboardMarkup(TEXTS[lang]['main_menu'], resize_keyboard=True)
        await update.message.reply_text(TEXTS[lang]['choose_opt'], reply_markup=reply_markup)

if __name__ == '__main__':
    app = ApplicationBuilder().token(TOKEN).build()

    menu_buttons_filter = filters.Regex("^(📧 Gmail Services|📧 ጂሜይል ሰራ/ሽያጭ|📊 My Tasks|📊 የኔ ስራዎች|👤 Profile|👤 ፕሮፋይል|💳 Withdraw|💳 ገንዘብ ማውጣት|🔗 Invite & Earn|🔗 ይጋብዙና ያተርፉ|🌐 Language|🌐 ቋንቋ|📞 Support Team|📞 እርዳታ)$")

    sell_gmail_handler = ConversationHandler(
        entry_points=[MessageHandler(filters.Regex("^(📧 Sell Gmail|📧 ጂሜይል ለመሸጥ)$"), start_sell_gmail)],
        states={
            WAITING_FOR_GMAIL: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_gmail)],
            WAITING_FOR_PASSWORD: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_password)],
        },
        fallbacks=[CommandHandler("cancel", cancel), MessageHandler(menu_buttons_filter, handle_message)],
        allow_reentry=True
    )

    withdraw_handler = ConversationHandler(
        entry_points=[MessageHandler(filters.Regex("^(💳 Withdraw|💳 ገንዘብ ማውጣት)$"), start_withdraw)],
        states={
            SELECT_WITHDRAW_METHOD: [MessageHandler(filters.TEXT & ~filters.COMMAND, select_withdraw_method)],
            ENTER_WITHDRAW_DETAILS: [MessageHandler(filters.TEXT & ~filters.COMMAND, enter_withdraw_details)],
            ENTER_WITHDRAW_AMOUNT: [MessageHandler(filters.TEXT & ~filters.COMMAND, enter_withdraw_amount)],
        },
        fallbacks=[CommandHandler("cancel", cancel), MessageHandler(menu_buttons_filter, handle_message)],
        allow_reentry=True
    )

    reject_handler = ConversationHandler(
        entry_points=[CallbackQueryHandler(start_admin_reject, pattern="^r_")],
        states={
            WAITING_FOR_REJECT_REASON: [CallbackQueryHandler(receive_reject_reason_callback, pattern="^rej_reason_")],
        },
        fallbacks=[CommandHandler("cancel", cancel)]
    )

    admin_credential_handler = ConversationHandler(
        entry_points=[CallbackQueryHandler(start_admin_send_credentials, pattern="^sendcred_")],
        states={
            WAITING_FOR_ADMIN_CREDENTIALS: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_admin_credentials)],
        },
        fallbacks=[CommandHandler("cancel", cancel)]
    )

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("ban", ban_command))
    app.add_handler(CommandHandler("unban", unban_command))
    app.add_handler(CommandHandler("setsellprice", set_sell_price_command))
    app.add_handler(CommandHandler("setcreateprice", set_create_price_command))
    app.add_handler(CommandHandler("admin", admin_control_panel))
    app.add_handler(CallbackQueryHandler(handle_admin_control_callbacks, pattern="^admin_task_"))
    app.add_handler(CommandHandler("broadcast", broadcast_command))
    app.add_handler(CommandHandler("stats", stats_command))
    
    app.add_handler(CallbackQueryHandler(check_join_callback, pattern="^check_join_status$"))
    
    app.add_handler(MessageHandler(filters.Regex("^(📧 Gmail Services|📧 ጂሜይል ሰራ/ሽያጭ)$"), show_service_menu))
    app.add_handler(MessageHandler(filters.Regex("^(🛠 Create Gmail|🛠 ጂሜይል ለመክፈት)$"), ask_create_gmail_confirm))
    app.add_handler(CallbackQueryHandler(handle_create_gmail_callbacks, pattern="^(confirm_create_gmail|cancel_create_gmail)$"))

    app.add_handler(sell_gmail_handler)
    app.add_handler(withdraw_handler)
    app.add_handler(admin_credential_handler)
    app.add_handler(CallbackQueryHandler(handle_direct_approve, pattern="^a_"))
    app.add_handler(CallbackQueryHandler(handle_withdraw_paid, pattern="^wpay_"))
    app.add_handler(CallbackQueryHandler(handle_gmail_done_callback, pattern="^gmail_done_"))
    app.add_handler(CallbackCodeHandler := CallbackQueryHandler(handle_copy_callbacks, pattern="^(copymail_|copypass_)"))
    app.add_handler(CallbackQueryHandler(handle_created_gmail_admin_decision, pattern="^mgmail_"))
    app.add_handler(reject_handler)
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    print("ቦቱ ሙሉ በሙሉ ተስተካክሎ መስራት ጀምሯል...")
    app.run_polling()
