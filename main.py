import os
import uvicorn
from fastapi import FastAPI, Request
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes

# 1. Load Token
TOKEN = os.getenv("TELEGRAM_TOKEN")
if not TOKEN:
    raise ValueError("No TELEGRAM_TOKEN found in environment variables")

# --- KEYBOARD LAYOUTS ---
# We define them as functions so we can generate them dynamically if needed

def get_main_menu_keyboard():
    keyboard = [
        [
            InlineKeyboardButton("🚀 Tools", callback_data='menu_tools'),
            InlineKeyboardButton("ℹ️ Help", callback_data='menu_help'),
        ],
        [InlineKeyboardButton("🔗 Visit Website", url='https://google.com')]
    ]
    return InlineKeyboardMarkup(keyboard)

def get_tools_menu_keyboard():
    keyboard = [
        [InlineKeyboardButton("Ping 📡", callback_data='action_ping')],
        [InlineKeyboardButton("Weather ☀️", callback_data='action_weather')],
        [InlineKeyboardButton("🔙 Back to Main", callback_data='menu_main')]
    ]
    return InlineKeyboardMarkup(keyboard)

def get_back_button():
    keyboard = [[InlineKeyboardButton("🔙 Back to Main", callback_data='menu_main')]]
    return InlineKeyboardMarkup(keyboard)

# --- COMMAND HANDLERS ---

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Sends the initial message with the main menu."""
    user = update.effective_user.first_name
    await update.message.reply_text(
        f"Hello {user}! Welcome to the bot.\nSelect an option below:",
        reply_markup=get_main_menu_keyboard()
    )

# --- CALLBACK QUERY HANDLER (The Brains) ---

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Parses the CallbackQuery and updates the message text."""
    query = update.callback_query
    
    # Always answer the query first to stop the button loading animation
    await query.answer()

    # Determine which button was pressed based on 'callback_data'
    data = query.data

    # 1. Navigation Logic (Switching Menus)
    if data == 'menu_main':
        await query.edit_message_text(
            text="<b>🤖 Main Menu</b>\nSelect an option:",
            parse_mode='HTML',
            reply_markup=get_main_menu_keyboard()
        )
    
    elif data == 'menu_tools':
        await query.edit_message_text(
            text="<b>🛠 Tools Menu</b>\nSelect a tool to run:",
            parse_mode='HTML',
            reply_markup=get_tools_menu_keyboard()
        )

    elif data == 'menu_help':
        await query.edit_message_text(
            text=(
                "<b>ℹ️ Help Section</b>\n\n"
                "This bot runs on Google Cloud Run.\n"
                "It uses Webhooks for zero-cost latency.\n\n"
                "<i>Click Back to return.</i>"
            ),
            parse_mode='HTML',
            reply_markup=get_back_button()
        )

    # 2. Action Logic (Doing things)
    elif data == 'action_ping':
        # Notification (Pop-up toast at top of screen)
        await query.answer("Pong! 🏓 Connection is good.", show_alert=False)
        # We don't edit the text here, just show the toast
    
    elif data == 'action_weather':
        # Alert (Modal popup that requires user to click OK)
        await query.answer("It's always sunny in the Cloud! ☁️", show_alert=True)

# --- APP SETUP ---

ptb_application = Application.builder().token(TOKEN).build()

# Register Handlers
ptb_application.add_handler(CommandHandler("start", start))
# This handler catches *any* inline button press
ptb_application.add_handler(CallbackQueryHandler(button_handler))

# --- FASTAPI LIFECYCLE ---

async def lifespan(app: FastAPI):
    await ptb_application.initialize()
    await ptb_application.start()
    print("Bot started...")
    yield
    await ptb_application.stop()
    await ptb_application.shutdown()

app = FastAPI(lifespan=lifespan)

@app.post("/")
async def telegram_webhook(request: Request):
    data = await request.json()
    update = Update.de_json(data, ptb_application.bot)
    await ptb_application.process_update(update)
    return {"status": "ok"}

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    uvicorn.run(app, host="0.0.0.0", port=port)
