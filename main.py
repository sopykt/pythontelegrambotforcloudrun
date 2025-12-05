import os
import uvicorn
import asyncio
import zipfile
import shutil
import google.auth # <--- NEW IMPORT
from datetime import datetime
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
from googleapiclient.discovery import build

# --- IMPORT LOGIC ---
from logic import process_data

# 1. Load Secrets
TOKEN = os.getenv("TELEGRAM_TOKEN")
ADMIN_ENV = os.getenv("ADMIN_ID")
ALLOWED_USER_IDS = []

if ADMIN_ENV:
    try:
        ALLOWED_USER_IDS = [int(ADMIN_ENV)]
    except ValueError:
        print("Error: ADMIN_ID must be a number")

# --- CONFIGURATION ---
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
UPLOAD_FOLDER = '/tmp/uploads' # Still using tmp
FONT_PATH = os.path.join(BASE_DIR, 'fonts', 'NotoSansMyanmar-Regular.ttf')
WKHTML_PATH = '/usr/bin/wkhtmltoimage'

# !!! REMOVED: SERVICE_ACCOUNT_FILE path !!! 
TARGET_FILE_ID = '1yRy9ozaiFIgarkBRKrE5tGXEoMs2BSDa' 

os.makedirs(UPLOAD_FOLDER, exist_ok=True)

# --- SECURE DRIVE DOWNLOADER ---
def download_file_from_drive(output_path):
    SCOPES = ['https://www.googleapis.com/auth/drive.readonly']
    
    # --- NEW AUTH METHOD ---
    # This automatically grabs the credentials of the Cloud Run service account
    creds, _ = google.auth.default(scopes=SCOPES)
    
    service = build('drive', 'v3', credentials=creds)
    
    # The rest is exactly the same
    request = service.files().get_media(fileId=TARGET_FILE_ID)
    with open(output_path, 'wb') as f:
        f.write(request.execute())

# --- KEYBOARDS ---
def get_main_menu_keyboard():
    keyboard = [
        [InlineKeyboardButton("📊 Generate Reports", callback_data='menu_reports')],
        [InlineKeyboardButton("ℹ️ Help", callback_data='menu_help')],
    ]
    return InlineKeyboardMarkup(keyboard)

def get_report_menu():
    keyboard = [
        [InlineKeyboardButton("📅 Generate for Today", callback_data='action_gen_today')],
        [InlineKeyboardButton("🔙 Back", callback_data='menu_main')]
    ]
    return InlineKeyboardMarkup(keyboard)

# --- SECURITY ---
async def enforce_access(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.effective_user: return
    if update.effective_user.id not in ALLOWED_USER_IDS:
        raise ApplicationHandlerStop

# --- HEAVY TASK WRAPPER ---
def generate_reports_sync(date_string):
    if os.path.exists(UPLOAD_FOLDER):
        shutil.rmtree(UPLOAD_FOLDER)
    os.makedirs(UPLOAD_FOLDER, exist_ok=True)
    
    excel_path = os.path.join(UPLOAD_FOLDER, "drive_data.xlsx")
    
    # This now uses the secure auth
    download_file_from_drive(excel_path)
    
    generated_files = process_data(excel_path, UPLOAD_FOLDER, date_string, FONT_PATH, WKHTML_PATH)
    
    zip_filename = f"Report_{date_string}.zip"
    zip_path = os.path.join(UPLOAD_FOLDER, zip_filename)
    
    with zipfile.ZipFile(zip_path, 'w') as zipf:
        for f in generated_files:
            file_path = os.path.join(UPLOAD_FOLDER, f)
            if os.path.exists(file_path):
                zipf.write(file_path, arcname=f)
                
    return zip_path

# --- HANDLERS ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("👋 Hello Boss! Ready to generate.", reply_markup=get_main_menu_keyboard())

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer() 
    
    if query.data == 'menu_main':
        await query.edit_message_text("<b>🤖 Main Menu</b>", parse_mode='HTML', reply_markup=get_main_menu_keyboard())
    
    elif query.data == 'menu_reports':
        await query.edit_message_text("<b>📊 Report Generator</b>\nSelect option:", parse_mode='HTML', reply_markup=get_report_menu())

    elif query.data == 'action_gen_today':
        await query.edit_message_text("⏳ <b>Generating...</b>\n<i>Authenticating securely & Processing...</i>", parse_mode='HTML')
        # today_str = datetime.now().strftime("%Y-%m-%d") # Format: 2023-10-27
        today_str = datetime.now().strftime("၄-၁၂-၂၀၂၅")
        
        try:
            zip_path = await asyncio.to_thread(generate_reports_sync, today_str)
            
            await context.bot.send_document(
                chat_id=update.effective_chat.id,
                document=zip_path,
                filename=os.path.basename(zip_path),
                caption=f"✅ Reports for {today_str} generated!"
            )
            await query.message.reply_text("Done! What else?", reply_markup=get_main_menu_keyboard())
            
        except Exception as e:
            # Helpful error message if permissions are wrong
            error_msg = str(e)
            if "403" in error_msg:
                error_msg = "🚫 Access Denied! Did you share the Drive file with the Cloud Run email?"
            await query.message.reply_text(f"❌ Error: {error_msg}")

# --- APP SETUP ---
ptb_application = Application.builder().token(TOKEN).build()
ptb_application.add_handler(TypeHandler(Update, enforce_access), group=-1)
ptb_application.add_handler(CommandHandler("start", start))
ptb_application.add_handler(CallbackQueryHandler(button_handler))

async def lifespan(app: FastAPI):
    await ptb_application.initialize()
    await ptb_application.start()
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
