import os
import uvicorn
from fastapi import FastAPI, Request
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

# 1. Load your token from environment variables (Safety first!)
TOKEN = os.getenv("TELEGRAM_TOKEN")
if not TOKEN:
    raise ValueError("No TELEGRAM_TOKEN found in environment variables")

# 2. Define your bot logic (The "Hello World" part)
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Sends a hello message when the command /start is issued."""
    await update.message.reply_text("Hello World! I am running on Google Cloud Run.")

# 3. Setup the PTB Application (note: no run_polling here!)
ptb_application = Application.builder().token(TOKEN).build()
ptb_application.add_handler(CommandHandler("start", start))

# 4. FastAPI Setup with Lifecycle Management
# This ensures the bot initializes correctly before receiving traffic
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
# Telegram sends updates here. We pass them to PTB.
@app.post("/")
async def telegram_webhook(request: Request):
    # Get the data from the request
    data = await request.json()
    # Convert it to a PTB Update object
    update = Update.de_json(data, ptb_application.bot)
    # Process the update
    await ptb_application.process_update(update)
    return {"status": "ok"}

# 6. Local Development Helper
if __name__ == "__main__":
    # Cloud Run sets the PORT env var automatically
    port = int(os.environ.get("PORT", 8080))
    uvicorn.run(app, host="0.0.0.0", port=port)
  
