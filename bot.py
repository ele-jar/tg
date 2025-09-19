# bot.py

import os
import sys
import shutil
import json
import random
import string
import threading
import time
import atexit # NEW: Import atexit for clean shutdown saving
from concurrent.futures import ThreadPoolExecutor

from dotenv import load_dotenv
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ParseMode
from telegram.error import BadRequest
from telegram.ext import (Updater, CommandHandler, CallbackContext, ConversationHandler,
                          MessageHandler, Filters, CallbackQueryHandler)

from text import (get_welcome_message, get_stats_message, get_server_status_message,
                  get_filename_choice_message)
from tasks import get_http_filename, worker_task
from utils import escape_markdown, parse_filename, DOWNLOAD_PATH, fetch_root_dir_id, setup_logger, LOGGER

load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")
BUZZHEAVIER_ACCOUNT_ID = os.getenv("BUZZHEAVIER_ACCOUNT_ID")
BUZZHEAVIER_ROOT_DIR_ID = None

STATS_FILE = os.path.join(os.getcwd(), "stats.json")
executor = ThreadPoolExecutor(max_workers=4)

ACTIVE_TASKS = {}
task_lock = threading.Lock()
(AWAIT_LINK, AWAIT_FILENAME_CHOICE, AWAIT_CUSTOM_NAME) = range(3)

def load_data(context: CallbackContext):
    context.bot_data['data_lock'] = threading.Lock()
    stats_data = {"downloaded": 0, "uploaded": 0}; links_data = {}
    if os.path.exists(STATS_FILE):
        try:
            with open(STATS_FILE, 'r') as f: data = json.load(f)
            stats_data = data.get("stats", stats_data); links_data = data.get("saved_links", links_data)
        except (json.JSONDecodeError, IOError) as e: LOGGER.warning(f"Could not load stats file: {e}")
    context.bot_data['stats'] = stats_data; context.bot_data['saved_links'] = links_data
    def save_stats_func():
        with context.bot_data['data_lock']:
            try:
                with open(STATS_FILE, 'w') as f:
                    json.dump({"stats": context.bot_data['stats'], 
                               "saved_links": context.bot_data['saved_links']}, f, indent=4)
                LOGGER.info("Stats data saved to disk.") # NEW
            except IOError as e: LOGGER.error(f"Could not save stats file: {e}")
    context.bot_data['save_stats'] = save_stats_func
    # NEW: Register the save function to be called on program exit
    atexit.register(save_stats_func)

def start(update: Update, context: CallbackContext) -> None:
    LOGGER.info(f"User {update.effective_user.id} triggered /start")
    update.message.reply_text(get_welcome_message(), parse_mode=ParseMode.MARKDOWN_V2)

def send_command(update: Update, context: CallbackContext) -> int:
    user_id = update.effective_user.id
    LOGGER.info(f"User {user_id} triggered /send")
    with task_lock:
        if user_id in ACTIVE_TASKS:
            LOGGER.warning(f"User {user_id} tried to start a new task while one is already active.")
            update.message.reply_text("You already have an active task\. Please wait for it to complete\.")
            return ConversationHandler.END
    update.message.reply_text("Please send me the URL or magnet link to process\.")
    return AWAIT_LINK

def info_updater_thread(context: CallbackContext, user_id: int, chat_id: int, message_id: int): # MODIFIED: Signature changed
    last_text = ""
    while True:
        with task_lock:
            if user_id not in ACTIVE_TASKS: break
            current_text = ACTIVE_TASKS[user_id].get('status_text', "")
        if current_text and current_text != last_text:
            try:
                context.bot.edit_message_text(chat_id=chat_id, message_id=message_id,
                                              text=current_text, parse_mode=ParseMode.MARKDOWN_V2)
                last_text = current_text
            except BadRequest as e:
                if "Message is not modified" not in str(e): LOGGER.error(f"Info update error: {e}"); break
            except Exception as e: LOGGER.error(f"Unexpected info update error: {e}"); break
        time.sleep(2)

def info_command(update: Update, context: CallbackContext) -> None:
    user_id = update.effective_user.id
    LOGGER.info(f"User {user_id} triggered /info")
    with task_lock:
        if user_id in ACTIVE_TASKS:
            if not ACTIVE_TASKS[user_id].get('info_message_id'): # MODIFIED: Check for message_id instead of a boolean flag
                message = update.message.reply_text("`Querying status\.\.\.`", parse_mode=ParseMode.MARKDOWN_V2)
                # NEW: Store message details in the active task dictionary
                ACTIVE_TASKS[user_id]['info_message_id'] = message.message_id
                ACTIVE_TASKS[user_id]['info_chat_id'] = message.chat_id
                threading.Thread(target=info_updater_thread, args=(context, user_id, message.chat_id, message.message_id), daemon=True).start()
                LOGGER.info(f"Started info updater thread for user {user_id}")
            else:
                LOGGER.info(f"User {user_id} triggered /info, but updater thread is already active.")
                update.message.reply_text("A live status update is already active for your task\.")
        else:
            update.message.reply_text("You have no active tasks\.")

def savedlinks_command(update: Update, context: CallbackContext) -> None:
    LOGGER.info(f"User {update.effective_user.id} triggered /savedlinks")
    with context.bot_data['data_lock']: saved_links = context.bot_data['saved_links']
    if not saved_links: update.message.reply_text("No links have been saved yet\."); return
    message = "*\-\-\- Saved Links \-\-\-*\n\n"
    for filename, link in saved_links.items():
        message += f"*File:* `{escape_markdown(filename)}`\n*Link:* {escape_markdown(link)}\n\n"
    update.message.reply_text(message, parse_mode=ParseMode.MARKDOWN_V2, disable_web_page_preview=True)

def stats_command(update: Update, context: CallbackContext) -> None:
    LOGGER.info(f"User {update.effective_user.id} triggered /stats")
    with context.bot_data['data_lock']: stats = context.bot_data['stats']
    update.message.reply_text(get_stats_message(stats), parse_mode=ParseMode.MARKDOWN_V2)

def h_command(update: Update, context: CallbackContext) -> None:
    LOGGER.info(f"User {update.effective_user.id} triggered /h")
    total, used, free = shutil.disk_usage("/")
    with context.bot_data['data_lock']: total_bw = context.bot_data['stats']['downloaded'] + context.bot_data['stats']['uploaded']
    update.message.reply_text(get_server_status_message(total, used, free, total_bw), parse_mode=ParseMode.MARKDOWN_V2)

def cancel(update: Update, context: CallbackContext) -> int:
    LOGGER.info(f"User {update.effective_user.id} triggered /cancel")
    update.message.reply_text('Operation cancelled\. Note: any in\-progress download/upload will continue\.')
    return ConversationHandler.END

def receive_link(update: Update, context: CallbackContext) -> int:
    user_id = update.effective_user.id
    url = update.message.text.strip(); LOGGER.info(f"User {user_id} sent a link/magnet for processing.")
    context.user_data['url'] = url
    message = update.message.reply_text("_Fetching file details\.\.\._", parse_mode=ParseMode.MARKDOWN_V2)
    original_filename = "magnet_download"
    if url.startswith('http'):
        original_filename = get_http_filename(url)
        if not original_filename:
            LOGGER.warning(f"User {user_id} sent an invalid HTTP link. Could not get filename.")
            message.edit_text("Could not fetch file details\. Please check the URL\."); return ConversationHandler.END
    ext = os.path.splitext(original_filename)[1]; base_name = os.path.splitext(original_filename)[0]
    context.user_data['original_filename'] = original_filename
    context.user_data['smart_name'] = f"{parse_filename(base_name)}{ext}"
    context.user_data['short_name'] = f"{''.join(random.choices(string.ascii_letters + string.digits, k=8))}{ext}"
    text = get_filename_choice_message(context.user_data['original_filename'], context.user_data['smart_name'], context.user_data['short_name'])
    keyboard = [[InlineKeyboardButton("1. Full Name", callback_data='full')],[InlineKeyboardButton("2. Smart Name", callback_data='smart')],
                [InlineKeyboardButton("3. Short Name", callback_data='short')],[InlineKeyboardButton("4. Custom Name", callback_data='custom')]]
    message.edit_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=ParseMode.MARKDOWN_V2)
    return AWAIT_FILENAME_CHOICE

def start_worker_and_notify(update: Update, context: CallbackContext, final_filename: str):
    user_id = update.effective_user.id; chat_id = update.effective_chat.id; url = context.user_data['url']
    LOGGER.info(f"User {user_id} confirmed filename '{final_filename}'. Submitting worker task.")
    message_text = f"✅ *Task started successfully\!* Use /info to track progress\."
    if update.callback_query: update.callback_query.edit_message_text(message_text, parse_mode=ParseMode.MARKDOWN_V2)
    else: update.message.reply_text(message_text, parse_mode=ParseMode.MARKDOWN_V2)
    
    def update_status_in_active_tasks(text):
        with task_lock:
            if user_id in ACTIVE_TASKS: ACTIVE_TASKS[user_id]['status_text'] = text
            
    def on_task_complete(final_status_text): # MODIFIED: Accepts final status
        with task_lock:
            if user_id in ACTIVE_TASKS:
                task_info = ACTIVE_TASKS.pop(user_id) # MODIFIED: Use pop to get and remove atomically
                # NEW: Update the info message with the final status if it exists
                if task_info.get('info_message_id'):
                    try:
                        context.bot.edit_message_text(
                            text=final_status_text,
                            chat_id=task_info['info_chat_id'],
                            message_id=task_info['info_message_id'],
                            parse_mode=ParseMode.MARKDOWN_V2
                        )
                    except BadRequest as e:
                        LOGGER.warning(f"Could not edit final status for user {user_id}: {e}")

    with task_lock: ACTIVE_TASKS[user_id] = {'status_text': 'Initializing\.\.\.'} # MODIFIED: Simplified dict
    
    executor.submit(worker_task, url, final_filename, user_id, chat_id, context,
                    BUZZHEAVIER_ACCOUNT_ID, BUZZHEAVIER_ROOT_DIR_ID,
                    update_status_in_active_tasks, on_task_complete)
    return ConversationHandler.END

def filename_choice_handler(update: Update, context: CallbackContext) -> int:
    query = update.callback_query; query.answer(); choice = query.data
    LOGGER.info(f"User {update.effective_user.id} chose filename option: '{choice}'")
    if choice == 'custom': query.edit_message_text("Please reply with your desired custom filename\."); return AWAIT_CUSTOM_NAME
    filename_map = {'full': context.user_data['original_filename'], 'smart': context.user_data['smart_name'], 'short': context.user_data['short_name']}
    final_filename = filename_map[choice]
    return start_worker_and_notify(update, context, final_filename)

def custom_name_received(update: Update, context: CallbackContext) -> int:
    custom_name = update.message.text
    LOGGER.info(f"User {update.effective_user.id} provided custom name: '{custom_name}'")
    original_filename = context.user_data['original_filename']; ext = os.path.splitext(original_filename)[1]
    final_filename = f"{custom_name}{ext}" if ext and not custom_name.endswith(ext) else custom_name
    return start_worker_and_notify(update, context, final_filename)

def main() -> None:
    global BUZZHEAVIER_ROOT_DIR_ID
    setup_logger()
    LOGGER.info("Bot process started.")
    if not all([BOT_TOKEN, BUZZHEAVIER_ACCOUNT_ID]): LOGGER.critical("BOT_TOKEN or BUZZHEAVIER_ACCOUNT_ID not found in .env file."); sys.exit(1)
    updater = Updater(BOT_TOKEN); dispatcher = updater.dispatcher
    load_data(dispatcher)
    BUZZHEAVIER_ROOT_DIR_ID = fetch_root_dir_id(BUZZHEAVIER_ACCOUNT_ID)
    if not BUZZHEAVIER_ROOT_DIR_ID: LOGGER.critical("Could not fetch BuzzHeavier Root ID. Exiting."); sys.exit(1)
    if not os.path.exists(DOWNLOAD_PATH): os.makedirs(DOWNLOAD_PATH); LOGGER.info(f"Created download directory at {DOWNLOAD_PATH}")
    conv_handler = ConversationHandler(
        entry_points=[CommandHandler('send', send_command)],
        states={AWAIT_LINK: [MessageHandler(Filters.text & ~Filters.command, receive_link)],
                AWAIT_FILENAME_CHOICE: [CallbackQueryHandler(filename_choice_handler)],
                AWAIT_CUSTOM_NAME: [MessageHandler(Filters.text & ~Filters.command, custom_name_received)]},
        fallbacks=[CommandHandler('cancel', cancel)])
    dispatcher.add_handler(CommandHandler("start", start))
    dispatcher.add_handler(conv_handler)
    dispatcher.add_handler(CommandHandler("info", info_command))
    dispatcher.add_handler(CommandHandler("savedlinks", savedlinks_command))
    dispatcher.add_handler(CommandHandler("stats", stats_command))
    dispatcher.add_handler(CommandHandler("h", h_command))
    updater.start_polling()
    LOGGER.info("Bot started successfully. Listening for commands...")
    updater.idle()
    LOGGER.info("Bot is shutting down.")

if __name__ == '__main__':
    main()
