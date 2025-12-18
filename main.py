import os
import uvicorn
import asyncio
import zipfile
import shutil
import traceback
import google.auth
import re  # Added for date regex
from datetime import datetime, timedelta
from fastapi import FastAPI, Request
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    ContextTypes,
    TypeHandler,
    ApplicationHandlerStop,
    MessageHandler,
    filters
)
from googleapiclient.discovery import build

# --- IMPORT GOOGLE ADK components ---
from google import adk
from google.adk.agents import Agent
from google.adk.models.google_llm import Gemini
from google.adk.runners import InMemoryRunner
from google.adk.tools import google_search
from google.genai import types
from google.adk.sessions import VertexAiSessionService
from google.genai.errors import ClientError

# --- IMPORT LOGIC ---
from logic import process_data, process_specific_report

# 1. Load Secrets
TOKEN = os.getenv("TELEGRAM_TOKEN")
ADMIN_ENV = os.getenv("ADMIN_ID")
GOOGLE_API_KEY = os.getenv("GEMINI_API_KEY")
# --- AGENT ENGINE CONFIGURATION ---
PROJECT_ID = os.getenv("PROJECT_ID")
LOCATION = os.getenv("LOCATION")    
AGENT_ENGINE_ID = os.getenv("AGENT_ENGINE_ID")
app_name = "assistant-ai-tg"

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


# --- CONFIGURE RETRY OPTIONS ---
retry_config=types.HttpRetryOptions(
    attempts=5,  # Maximum retry attempts
    exp_base=7,  # Delay multiplier
    initial_delay=1, # Initial delay before first retry (in seconds)
    http_status_codes=[429, 500, 503, 504] # Retry on these HTTP errors
)



# runner = InMemoryRunner(agent = root_agent)

TARGET_FILE_ID = '1yRy9ozaiFIgarkBRKrE5tGXEoMs2BSDa' 

os.makedirs(UPLOAD_FOLDER, exist_ok=True)

# --- HELPER: CONVERT DATE TO BURMESE ---
def convert_to_burmese_date(dt_obj):
    # Converts datetime object to D-M-YYYY in Burmese digits
    # Example: 6-12-2025 -> ၆-၁၂-၂၀၂၅
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
    Parses commands intelligently.
    Examples:
    /gen tatsin e 4-12-25  -> Specific Date
    /gen tatsin p          -> Today
    /gen sitchar e p       -> Today, multiple formats
    """
    args = context.args
    
    # Configuration
    valid_types = ['tatsin', 'sitchar', 'room']
    valid_formats = ['e', 'p']
    
    req_type = None
    req_formats = []
    custom_date_obj = None

    # Regex for date: 1-2 digits, hyphen, 1-2 digits, hyphen, 2 or 4 digits
    # Matches: 4-12-25, 04-12-2025
    date_pattern = re.compile(r"^(\d{1,2})-(\d{1,2})-(\d{2,4})$")

    # --- 1. Parse Arguments ---
    for arg in args:
        arg_lower = arg.lower()

        # Check for Date Pattern (e.g., 6-12-25)
        date_match = date_pattern.match(arg)
        if date_match:
            try:
                d, m, y = map(int, date_match.groups())
                # Handle 2-digit year (e.g., 25 -> 2025)
                if y < 100:
                    y += 2000
                
                custom_date_obj = datetime(y, m, d)
                continue # Arg processed, move to next
            except ValueError:
                # Invalid date numbers (e.g. month 13), ignore or let it fail later
                pass

        # Check for Report Type
        if arg_lower in valid_types:
            req_type = arg_lower
            continue

        # Check for Formats
        if arg_lower in valid_formats:
            if arg_lower not in req_formats:
                req_formats.append(arg_lower)
            continue

    # --- 2. Validation ---
    if not req_type:
        await update.message.reply_text("⚠️ <b>Error:</b> Specify report type (tatsin, sitchar, room).\nEx: <code>/gen tatsin e</code>", parse_mode='HTML')
        return

    if not req_formats:
        await update.message.reply_text("⚠️ <b>Error:</b> Specify format (e, p).\nEx: <code>/gen tatsin e p</code>", parse_mode='HTML')
        return

    # --- 3. Determine Date ---
    if custom_date_obj:
        # Convert custom date to Burmese string
        target_burmese_date = convert_to_burmese_date(custom_date_obj)
        display_info = f"{custom_date_obj.day}-{custom_date_obj.month}-{custom_date_obj.year}"
    else:
        # Default to Today
        target_burmese_date = get_burmese_today()
        display_info = "Today"

    # --- 4. Execution ---
    msg = await update.message.reply_text(
        f"⏳ <b>Processing...</b>\n"
        f"Type: {req_type.upper()} [{', '.join(req_formats).upper()}]\n"
        f"Date: {target_burmese_date} ({display_info})", 
        parse_mode='HTML'
    )
    
    try:
        # Run specific generation in thread
        file_paths = await asyncio.to_thread(
            generate_specific_sync, target_burmese_date, req_type, req_formats
        )
        
        if not file_paths:
            await msg.edit_text(f"⚠️ No data found for {target_burmese_date}.")
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

async def send_long_message(update: Update, text: str):
    """
    Splits long text into chunks of 4000 characters to avoid Telegram's 
    MessageTooLong error (limit is 4096).
    """
    if not text:
        return

    # Safety margin: 4000 chars allows for some overhead
    MAX_LENGTH = 4000 
    
    # Loop through the text and send chunks
    for i in range(0, len(text), MAX_LENGTH):
        chunk = text[i:i + MAX_LENGTH]
        await update.message.reply_text(chunk)
            

async def gemini_res(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Gemini response the user message."""
    user_id = str(update.effective_user.id)
    user_text = update.message.text
    session_id = None
    try:
        # --- RUNNER SETUP WITH SESSIONS ---
        # Initialize the connection to Vertex AI Session Service
        session_service = VertexAiSessionService(
            PROJECT_ID,
            LOCATION,
            AGENT_ENGINE_ID
        )

        # Check for existing sessions
        response = await session_service.list_sessions(app_name=app_name, user_id=user_id)
        if response.sessions:
            # Use the most recent session
            session_id = response.sessions[0].id
            print(f"✅ Found existing session: {session_id}")
            # await session_service.delete_session(app_name=app_name, user_id=user_id, session_id=session_id)
        else:
            # Create a completely new session for this user
            session = await session_service.create_session(
                app_name=app_name,
                user_id=user_id
            )
            session_id = session.id
            print(f"🆕 Created new session: {session_id}")
        
    except Exception as e:
        print(f"Session Error: {e}")
        await update.message.reply_text("⚠️ Error connecting to memory service.")
        return

    # Helper method to send query to the runner
    def call_agent(query, session_id, user_id):
        content = types.Content(role='user', parts=[types.Part(text=query)])
        print('runner now running..')
        root_agent = Agent(
            name = "helpful_assistant",
            model = Gemini(
                model="gemini-2.5-flash-lite",
                retry_options=retry_config
            ),
            description = "A simple agent that can answer general questions.",
            instruction = "You are a helpful assistant. Use Google Search for current info or if unsure.",
            tools=[google_search],
        )
        runner = adk.Runner(
            agent=root_agent,
            app_name=app_name,
            session_service=session_service
        )
        events = runner.run(
            user_id=user_id, 
            session_id=session_id, 
            new_message=content)

        for event in events:
            if not event.is_final_response():
                print(f"Event is not final response. Event: {event}")
                return 
            else:
                final_response = event.content.parts[0].text
                print("Agent Response: ", final_response)
                return final_response
    
    try:
        
        final_response_text = ""
        final_response_text = call_agent(user_text, session_id, user_id)
        
        if final_response_text:
            await send_long_message(update, final_response_text)
        else:
            await update.message.reply_text("🤔 I'm thinking, but I have nothing to say.")
    except Exception as e:
        print(f"Agent Execution Error: {e}")
        traceback.print_exc()
        await update.message.reply_text("⚠️ An error occurred while processing.")

# --- APP SETUP ---
ptb_application = Application.builder().token(TOKEN).build()
ptb_application.add_handler(TypeHandler(Update, enforce_access), group=-1)
ptb_application.add_handler(CommandHandler("start", start))
ptb_application.add_handler(CommandHandler("gen", gen_command)) 
ptb_application.add_handler(CallbackQueryHandler(button_handler))
ptb_application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, gemini_res))


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
