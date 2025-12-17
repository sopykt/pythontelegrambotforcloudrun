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
from google.adk.tools import google_search, FunctionTool, AgentTool
from google.genai import types
from google.adk.sessions import VertexAiSessionService
from google.genai.errors import ClientError

# --- IMPORT LOGIC ---
from logic import process_data, process_specific_report, calculate_admitted_df_len

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

# --- SECURE DRIVE DOWNLOADER ---
def download_file_from_drive(output_path):
    SCOPES = ['https://www.googleapis.com/auth/drive.readonly']
    creds, _ = google.auth.default(scopes=SCOPES)
    service = build('drive', 'v3', credentials=creds)
    
    request = service.files().get_media(fileId=TARGET_FILE_ID)
    with open(output_path, 'wb') as f:
        f.write(request.execute())

def get_admitted_patients_count() -> str:
    """
    Calculates and returns the total number of currently admitted patients.

    This function reads the locally cached Excel data ('drive_data.xlsx'), filters for 
    patients who have not yet been discharged or transferred (where both discharge 
    and transfer dates are missing), and returns the total count.

    Returns:
        str: A summary sentence with the count (e.g., "Total admitted patients: 45").
             If the data file is missing or invalid, returns an error message.
    """
    if os.path.exists(UPLOAD_FOLDER):
        shutil.rmtree(UPLOAD_FOLDER)
    os.makedirs(UPLOAD_FOLDER, exist_ok=True)
    
    excel_path = os.path.join(UPLOAD_FOLDER, "drive_data.xlsx")
    download_file_from_drive(excel_path)

    if not os.path.exists(excel_path):
        return "Error: Data file not found. Please ask user to 'Fix loading data file properly' first to download the latest data."

    try:
        count = calculate_admitted_df_len(excel_path)
        return f"There are currently {count} admitted patients."
    except Exception as e:
        return f"Error processing data: {str(e)}"


# 1. Wrap your custom function
admitted_patient_tool = FunctionTool(get_admitted_patients_count)

# 2. Search Worker


# 3. Data Worker


# 4. Root Agent (The Boss)


# --- RUNNER SETUP WITH SESSIONS ---
# Initialize the connection to Vertex AI Session Service




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

# --- ISOLATED AGENT EXECUTION (THE FIX) ---
def run_multi_agent_sync(user_text, user_id):
    """
    Runs the entire agent lifecycle (Session Check -> Execution) in a single synchronous thread.
    This prevents 'Client Closed' errors by ensuring no AsyncClient leaks between loops.
    """
    print(f"--- 🔄 Starting Sync Agent Run for {user_id} ---")
    
    # 1. Setup Session Service (Fresh instance)
    # Using sync methods or bridging correctly if the SDK forces async.
    # Note: VertexAiSessionService methods are typically async. 
    # Since we are in a thread, we must run a NEW event loop for this work 
    # OR use the synchronous 'Runner.run' which handles its own loop logic internally.
    
    # Ideally, we pass the session_id if we have it, but since we can't get it 
    # reliably from the main loop without errors, we might need a workaround.
    # WORKAROUND: For this specific error, we let the Runner manage the session 
    # using the user_id as a lookup, if supported, or we accept we might create new sessions.
    
    # However, to be perfectly safe, we will use a fresh Runner which creates its own internal loop.
    
    local_session_service = VertexAiSessionService(
        PROJECT_ID,
        LOCATION,
        AGENT_ENGINE_ID
    )

    # 2. Re-Initialize Workers (Fresh Model Clients)
    search_worker = Agent(
        name="search_worker",
        model=Gemini(model="gemini-2.5-flash-lite", retry_options=retry_config),
        tools=[google_search],
        description="A specialist that searches the internet.",
        instruction="You are a research specialist. Use Google Search to find current information."
    )

    data_worker = Agent(
        name="data_worker",
        model=Gemini(model="gemini-2.5-flash-lite", retry_options=retry_config),
        tools=[admitted_patient_tool],
        description="A specialist agent that has EXCLUSIVE access to the patient database.",
        instruction="You are a data analyst. Use the admitted_patient_tool to check the database."
    )

    root_agent = Agent(
        name="helpful_assistant",
        model=Gemini(model="gemini-2.5-flash-lite", retry_options=retry_config),
        description="A manager agent that delegates tasks.",
        instruction="""
        You are a helpful assistant acting as a manager.
        RULES:
        1. Delegate 'patient data' questions to 'data_worker'.
        2. Delegate 'general info' questions to 'search_worker'.
        """,
        tools=[AgentTool(search_worker), AgentTool(data_worker)],
    )

    local_runner = adk.Runner(
        agent=root_agent,
        app_name=app_name,
        session_service=local_session_service
    )

    content = types.Content(role='user', parts=[types.Part(text=user_text)])

    # CRITICAL: We use runner.run() which is the SYNCHRONOUS blocking call.
    # This will handle the session lookup internally via the session_service 
    # (or create a new one if session_id is None).
    
    # We must first get or create a session. Since we can't await here (we are sync),
    # we have to use a small helper or rely on the runner.
    # The ADK Runner.run() method usually takes a session_id. 
    # If we don't have one, we have to create one. 
    # BUT: session_service.create_session is async.
    
    # SOLUTION: We use asyncio.run() INSIDE this thread to handle the async setup parts
    # strictly for this thread.
    
    async def _async_setup_and_run():
        # A. Get Session ID
        sessions_list = await local_session_service.list_sessions(app_name=app_name, user_id=user_id)
        if sessions_list.sessions:
            sid = sessions_list.sessions[0].id
        else:
            new_sess = await local_session_service.create_session(app_name=app_name, user_id=user_id)
            sid = new_sess.id
            
        # B. Run Agent (using run_async inside this local loop is safer than run() wrapper)
        responses = []
        async for evt in local_runner.run_async(user_id=user_id, session_id=sid, new_message=content):
            if evt.is_final_response():
                responses.append(evt.content.parts[0].text)
        return responses[0] if responses else ""

    # Execute the isolated async loop
    result_text = asyncio.run(_async_setup_and_run())
            
    print(f"--- ✅ Sync Agent Run Finished ---")
    return result_text
    

async def gemini_res(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    CLEAN HANDLER:
    It does NO google work itself. It just dispatches to the isolated thread.
    """
    user_id = str(update.effective_user.id)
    user_text = update.message.text

    try:
        await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")
        
        # Dispatch to completely isolated thread
        final_response_text = await asyncio.to_thread(
            run_multi_agent_sync, 
            user_text, 
            user_id
        )

        if final_response_text:
            await update.message.reply_text(final_response_text)
        else:
            await update.message.reply_text("🤔 I'm thinking, but I have nothing to say.")
            
    except Exception as e:
        print(f"Agent Execution Error: {e}")
        traceback.print_exc()
        await update.message.reply_text("⚠️ Brain freeze! (Agent Error)")
    

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
