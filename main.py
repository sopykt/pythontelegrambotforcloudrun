import os
import uvicorn
from fastapi import FastAPI, Request
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    ContextTypes,
    TypeHandler,
    ApplicationHandlerStop
)

# 1. Load Secrets
TOKEN = os.getenv("TELEGRAM_TOKEN")
# Add your ID here. You can add multiple IDs (e.g., you and a friend)
# ideally load this from env, but hardcoding is fine for personal bots
ALLOWED_USER_IDS = [123456789]  # <--- REPLACE THIS WITH YOUR ID

if not TOKEN:
    raise ValueError("No TELEGRAM_TOKEN found in environment variables")

# --- KEYBOARDS (Same as before) ---
def get_main_menu_keyboard():
    keyboard = [
        [
            InlineKeyboardButton("🚀 Tools", callback_data='menu_tools'),
            InlineKeyboardButton("ℹ️ Help", callback_data='menu_help'),
        ],
    ]
    return InlineKeyboardMarkup(keyboard)

def get_back_button():
    keyboard = [[InlineKeyboardButton("🔙 Back", callback_data='menu_main')]]
    return InlineKeyboardMarkup(keyboard)

# --- SECURITY HANDLER (The "Bouncer") ---
async def enforce_access(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Checks if the user is allowed. 
    If not, stops processing completely.
    """
    user_id = update.effective_user.id
    if user_id not in ALLOWED_USER_IDS:
        print(f"⛔️ Unauthorized access attempt from User ID: {user_id}")
        # Optional: Tell them to go away (or just stay silent to be stealthy)
        # await update.message.reply_text("⛔️ Access Denied.")
        
        # This exception stops the update from reaching other handlers
        raise ApplicationHandlerStop 

# --- COMMANDS ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 Welcome, Admin! You are authorized.",
        reply_markup=get_main_menu_keyboard()
    )

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Only you can see this help menu.")

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data

    if data == 'menu_main':
        await query.edit_message_text("<b>🤖 Main Menu</b>", parse_mode='HTML', reply_markup=get_main_menu_keyboard())
    elif data == 'menu_help':
        await query.edit_message_text("<b>ℹ️ Secret Help</b>", parse_mode='HTML', reply_markup=get_back_button())

# --- APP SETUP ---
ptb_application = Application.builder().token(TOKEN).build()

# !!! CRITICAL: Add the "Bouncer" FIRST with a low group number (-1) !!!
# This ensures it runs before any command or button handlers.
ptb_application.add_handler(TypeHandler(Update, enforce_access), group=-1)

# Register normal handlers
ptb_application.add_handler(CommandHandler("start", start))
ptb_application.add_handler(CommandHandler("help", help_command))
ptb_application.add_handler(CallbackQueryHandler(button_handler))

# --- FASTAPI SETUP ---
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
