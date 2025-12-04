import os
import uvicorn
from fastapi import FastAPI, Request
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

# 1. Load your token
TOKEN = os.getenv("TELEGRAM_TOKEN")
if not TOKEN:
    raise ValueError("No TELEGRAM_TOKEN found in environment variables")

# 2. Define your bot commands

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Sends a hello message."""
    user_first_name = update.effective_user.first_name
    await update.message.reply_text(f"Hello {user_first_name}! I am running on Google Cloud Run.")

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Sends a formatted help message."""
    # You can use HTML tags like <b>, <i>, <code>, <pre>
    help_text = (
        "<b>🤖 Bot Help Menu</b>\n\n"
        "Here are the commands you can use:\n"
        "/start - Wake me up and say hello\n"
        "/help - Show this help message\n\n"
        "<i>💡 Hint: You can edit this text in the 'help_command' function in main.py</i>"
    )
    # Note: parse_mode="HTML" is required for the tags to work
    await update.message.reply_text(help_text, parse_mode="HTML")

# 3. Setup the PTB Application
ptb_application = Application.builder().token(TOKEN).build()

# --- Register your handlers here ---
ptb_application.add_handler(CommandHandler("start", start))
ptb_application.add_handler(CommandHandler("help", help_command))

# 4. FastAPI Setup with Lifecycle Management
async def lifespan(app: FastAPI):
    # Startup: Initialize the bot
    await ptb_application.initialize()
    await ptb_application.start()
    print("Bot started and ready to receive updates.")
    yield
    # Shutdown: Clean up resources
    await ptb_application.stop()
    await ptb_application.shutdown()

app = FastAPI(lifespan=lifespan)

# 5. The Webhook Endpoint
@app.post("/")
async def telegram_webhook(request: Request):
    data = await request.json()
    update = Update.de_json(data, ptb_application.bot)
    await ptb_application.process_update(update)
    return {"status": "ok"}

# 6. Local Development Helper
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    uvicorn.run(app, host="0.0.0.0", port=port)
