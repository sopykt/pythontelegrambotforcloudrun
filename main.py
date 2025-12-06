import os
import uvicorn
import asyncio
import zipfile
import shutil
import traceback
import google.auth
from datetime import datetime, timedelta
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
from logic import process_data, process_specific_report

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
UPLOAD_FOLDER = '/tmp/uploads'
FONT_PATH = os.path.join(BASE_DIR, 'fonts', 'NotoSansMyanmar-Regular.ttf')
WKHTML_PATH = '/usr/bin/wkhtmltoimage'

TARGET_FILE_ID = '1yRy9ozaiFIgarkBRKrE5tGXEoMs2BSDa' 

os.makedirs(UPLOAD_FOLDER, exist_ok=True)

# --- HELPER: CONVERT DATE TO BURMESE ---
def convert_to_burmese_date(dt_obj):
    eng_date = f"{dt_obj.day}-{dt_obj.month}-{dt_obj.year}"
    translation_table = str.maketrans("0123456789", "၀၁၂၃၄၅၆၇၈၉")
    return eng_date.translate(translation_table)

def get_burmese_today():
    return convert_to_burmese_date(datetime.now())

def get_burmese_yesterday():
    yesterday = datetime.now() - timedelta(days=1)
    return convert_to_burmese_date(yesterday)

# --- SECURE DRIVE DOWNLOADER ---
def download_file_from_drive(output_path):
    SCOPES = ['https://www.googleapis.com/auth/drive.readonly']
    creds, _ = google.auth.default(scopes=SCOPES)
    service = build('drive', 'v3', credentials=creds)
    
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
        [InlineKeyboardButton("📅 Today", callback_data='action_gen_today')],
        [InlineKeyboardButton("⏪ Yesterday", callback_data='action_gen_yesterday')],
        [InlineKeyboardButton("🔙 Back", callback_data='menu_main')]
    ]
    return InlineKeyboardMarkup(keyboard)

# --- SECURITY ---
async def enforce_access(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.effective_user: return
    if update.effective_user.id not in ALLOWED_USER_IDS:
        raise ApplicationHandlerStop

# --- HEAVY TASKS (SYNC) ---
def generate_reports_sync(date_string):
    """Old button logic: generates ALL files and Zips them"""
    if os.path.exists(UPLOAD_FOLDER):
        shutil.rmtree(UPLOAD_FOLDER)
    os.makedirs(UPLOAD_FOLDER, exist_ok=True)
    
    excel_path = os.path.join(UPLOAD_FOLDER, "drive_data.xlsx")
    download_file_from_drive(excel_path)
    
    generated_files = process_data(excel_path, UPLOAD_FOLDER, date_string, FONT_PATH, WKHTML_PATH)
    
    zip_filename = f"Report_{date_string}.zip"
    zip_path = os.path.join(UPLOAD_FOLDER, zip_filename)
    
    with zipfile.ZipFile(zip_path, 'w') as zipf:
        for f in generated_files:
            file_path = os.path.join(UPLOAD_FOLDER, f)
            if os.path.exists(file_path):
                zipf.write(file_path, arcname=f)
                
    return [zip_path] # Return as list to match structure

def generate_specific_sync(date_string, r_type, r_formats):
    """New command logic: generates specific files"""
    if os.path.exists(UPLOAD_FOLDER):
        shutil.rmtree(UPLOAD_FOLDER)
    os.makedirs(UPLOAD_FOLDER, exist_ok=True)
    
    excel_path = os.path.join(UPLOAD_FOLDER, "drive_data.xlsx")
    download_file_from_drive(excel_path)
    
    # Call the new specific logic
    generated_files = process_specific_report(
        excel_path, UPLOAD_FOLDER, date_string, FONT_PATH, WKHTML_PATH, r_type, r_formats
    )
    
    # Return full paths
    return [os.path.join(UPLOAD_FOLDER, f) for f in generated_files]

# --- HANDLERS ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("👋 Hello Boss! Ready to generate.", reply_markup=get_main_menu_keyboard())

async def gen_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Parses commands like: /gen tatsin p
    """
    args = context.args
    valid_types = ['tatsin', 'sitchar', 'room']
    valid_formats = ['e', 'p']
    
    # 1. Validation Logic
    is_valid = True
    
    # Must have at least 2 args: type + at least one format
    if len(args) < 2:
        is_valid = False
    else:
        req_type = args[0].lower()
        req_formats = [a.lower() for a in args[1:]]
        
        # Check type
        if req_type not in valid_types:
            is_valid = False
        
        # Check formats (must be 'e' or 'p', and NO duplicates)
        if len(req_formats) != len(set(req_formats)): # Check for duplicates (e.g. e e)
            is_valid = False
        
        for f in req_formats:
            if f not in valid_formats:
                is_valid = False

    if not is_valid:
        await update.message.reply_text("your command is wrong, check again")
        return

    # 2. Execution Logic
    msg = await update.message.reply_text("⏳ <b>Processing...</b>", parse_mode='HTML')
    today_burmese = get_burmese_today()
    
    try:
        # Run specific generation in thread
        file_paths = await asyncio.to_thread(
            generate_specific_sync, today_burmese, args[0].lower(), [a.lower() for a in args[1:]]
        )
        
        if not file_paths:
            await msg.edit_text("⚠️ No data found for today.")
            return

        # Upload files
        for fpath in file_paths:
            await context.bot.send_document(
                chat_id=update.effective_chat.id,
                document=fpath,
                filename=os.path.basename(fpath)
            )
        
        await msg.delete() # cleanup "processing" message
        
    except Exception as e:
        print(f"🔥 GEN CMD ERROR:\n{traceback.format_exc()}")
        await msg.edit_text("❌ Error occurred processing command.")

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer() 
    
    if query.data == 'menu_main':
        await query.edit_message_text("<b>🤖 Main Menu</b>", parse_mode='HTML', reply_markup=get_main_menu_keyboard())
    
    elif query.data == 'menu_reports':
        await query.edit_message_text("<b>📊 Report Generator</b>\nSelect option:", parse_mode='HTML', reply_markup=get_report_menu())

    elif query.data in ['action_gen_today', 'action_gen_yesterday']:
        if query.data == 'action_gen_today':
            target_date = get_burmese_today()
            label = "Today"
        else:
            target_date = get_burmese_yesterday()
            label = "Yesterday"
        
        await query.edit_message_text(
            f"⏳ <b>Generating for {label} ({target_date})...</b>\n<i>Authenticating securely & Processing...</i>", 
            parse_mode='HTML'
        )
        
        try:
            # Note: generate_reports_sync returns a list containing the zip path
            result_list = await asyncio.to_thread(generate_reports_sync, target_date)
            zip_path = result_list[0]
            
            await context.bot.send_document(
                chat_id=update.effective_chat.id,
                document=zip_path,
                filename=os.path.basename(zip_path),
                caption=f"✅ Reports for {target_date} generated!"
            )
            await query.message.reply_text("Done! What else?", reply_markup=get_main_menu_keyboard())
            
        except Exception as e:
            error_details = traceback.format_exc()
            print(f"🔥 ERROR:\n{error_details}") 
            await query.message.reply_text(f"❌ Error Occurred:\n{str(e)[:300]}")

# --- APP SETUP ---
ptb_application = Application.builder().token(TOKEN).build()
ptb_application.add_handler(TypeHandler(Update, enforce_access), group=-1)
ptb_application.add_handler(CommandHandler("start", start))
ptb_application.add_handler(CommandHandler("gen", gen_command)) # <--- ADDED GEN COMMAND
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
