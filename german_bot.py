import csv
import os
import random
import logging
import gspread
import asyncio
import atexit
import signal
import sys
from datetime import datetime, time
from google.oauth2.service_account import Credentials
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, ReplyKeyboardRemove
from telegram.ext import (
    Application, 
    CommandHandler, 
    CallbackQueryHandler, 
    ContextTypes, 
    MessageHandler, 
    filters,
    ConversationHandler
)
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from pytz import timezone
from requests.exceptions import RequestException
from tenacity import retry, stop_after_attempt, wait_exponential
import nest_asyncio
nest_asyncio.apply()

# Configure logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO,
    handlers=[
        logging.FileHandler('bot.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# Get environment variables
TOKEN = os.environ.get('TELEGRAM_BOT_TOKEN')
if not TOKEN:
    raise ValueError("TELEGRAM_BOT_TOKEN environment variable is not set")

SPREADSHEET_ID = os.environ.get('SPREADSHEET_ID')
if not SPREADSHEET_ID:
    raise ValueError("SPREADSHEET_ID environment variable is not set")

# Google Sheets setup
SCOPES = [
    'https://www.googleapis.com/auth/spreadsheets.readonly',
    'https://www.googleapis.com/auth/drive.readonly'
]

# Try to get timezone, fallback to UTC if failed
try:
    DEFAULT_TIMEZONE = timezone('Europe/Kiev')
except Exception as e:
    logger.error(f"Invalid timezone: {e}")
    DEFAULT_TIMEZONE = timezone('UTC')

# Conversation states
CHOOSING_HOUR = 1
CHOOSING_MINUTE = 2

# Global variables
words = []
application = None
class MessageFormatter:
    """Format bot messages consistently"""
    
    @staticmethod
    def format_word_card(word: dict) -> str:
        """Format single word card with all details"""
        message = [
            f"🇩🇪 <b>{word['Німецькою']}</b>",
            f"🇺🇦 {word['Українською']}",
            f"🇬🇧 {word['Англійською']}"
        ]
        
        if word['Приклад']:
            message.append(f"📚 <i>{word['Приклад']}</i>")
        if word['Мнемотехніка']:
            message.append(f"💡 {word['Мнемотехніка']}")
            
        return "\n".join(message)
    
    @staticmethod
    def format_daily_words(words: list) -> str:
        """Format daily words list"""
        message = ["🎯 <b>Your daily German words:</b>\n"]
        
        for i, word in enumerate(words, 1):
            message.append(f"{i}. {MessageFormatter.format_word_card(word)}\n")
            
        return "\n".join(message)
    
    @staticmethod
    def format_test_question(word: dict) -> str:
        """Format test question"""
        return f"🤔 Переклад слова німецькою: '<b>{word['Німецькою']}</b>'?"
    
    @staticmethod
    def format_test_result(word: dict, is_correct: bool, user_answer: str) -> str:
        """Format test result with full explanation"""
        message = []
        
        if is_correct:
            message.append("✅ <b>Correct! Well done!</b>")
        else:
            message.extend([
                "❌ <b>Incorrect</b>",
                f"Your answer: {user_answer}",
                f"Correct answer: {word['Українською']}"
            ])
            
        message.append("\n<b>Full word info:</b>")
        message.append(MessageFormatter.format_word_card(word))
        
        return "\n".join(message)
    
    @staticmethod
    def format_notification_set(hour: int, minute: int) -> str:
        """Format notification time confirmation"""
        return (
            f"✅ Daily notifications have been set to <b>{hour:02d}:{minute:02d}</b>\n"
            "You'll receive 10 new words every day at this time."
        )
    
    @staticmethod
    def format_error_message(error_type: str) -> str:
        """Format error messages"""
        messages = {
            'no_words': "😕 Sorry, no words are available at the moment.",
            'load_failed': "❌ Failed to load words. Please try again later.",
            'invalid_time': "⚠️ Please select a valid time.",
            'general_error': "😔 Something went wrong. Please try again."
        }
        return messages.get(error_type, messages['general_error'])
    
@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=4, max=10))
def load_words_from_sheets():
    """Load words from Google Sheets with retry mechanism"""
    try:
        creds = Credentials.from_service_account_file(
            'credentials.json',
            scopes=SCOPES
        )
        client = gspread.authorize(creds)
        sheet = client.open_by_key(SPREADSHEET_ID).sheet1
        all_values = sheet.get_all_values()
        
        if len(all_values) < 2:
            logger.error("Spreadsheet is empty or has only headers")
            return False
            
        words.clear()
        for row in all_values[1:]:  # Skip header row
            if len(row) >= 5 and any(row):  # Check if row is not empty
                word = {
                    'Німецькою': row[0].strip(),
                    'Українською': row[1].strip(),
                    'Англійською': row[2].strip(),
                    'Приклад': row[3].strip(),
                    'Мнемотехніка': row[4].strip() if len(row) > 4 else ''
                }
                # Only add word if essential fields are not empty
                if word['Німецькою'] and word['Українською'] and word['Англійською']:
                    words.append(word)
        
        logger.info(f"Loaded {len(words)} words from Google Sheets")
        return True
    except (FileNotFoundError, RequestException) as e:
        logger.error(f"Failed to load credentials or connect to Google Sheets: {e}")
        return False
    except Exception as e:
        logger.error(f"Error loading from Google Sheets: {e}")
        return False

def get_random_word():
    """Get a random word from the list"""
    if not words:
        logger.error("No words available")
        return None
    return random.choice(words)

def get_wrong_answers(correct_answer):
    """Get up to 3 random wrong answers"""
    wrong_answers = []
    available_words = [w for w in words if w['Українською'] != correct_answer]
    if available_words:
        num_answers = min(3, len(available_words))
        wrong_answers = random.sample([w['Українською'] for w in available_words], num_answers)
    return wrong_answers

def get_hour_keyboard():
    """Create keyboard with hours"""
    keyboard = []
    row = []
    for hour in range(24):
        row.append(str(hour).zfill(2))
        if len(row) == 6:
            keyboard.append(row)
            row = []
    if row:
        keyboard.append(row)
    keyboard.append(['Cancel'])
    return ReplyKeyboardMarkup(keyboard, one_time_keyboard=True)

def get_minute_keyboard():
    """Create keyboard with minutes"""
    keyboard = []
    row = []
    for minute in range(0, 60, 5):
        row.append(str(minute).zfill(2))
        if len(row) == 6:
            keyboard.append(row)
            row = []
    if row:
        keyboard.append(row)
    keyboard.append(['Cancel'])
    return ReplyKeyboardMarkup(keyboard, one_time_keyboard=True)

def get_test_keyboard(correct_answer):
    """Create keyboard for test answers"""
    wrong_answers = get_wrong_answers(correct_answer)
    all_answers = wrong_answers + [correct_answer]
    random.shuffle(all_answers)
    keyboard = [[InlineKeyboardButton(answer, callback_data=f'answer_{i}')] for i, answer in enumerate(all_answers)]
    return InlineKeyboardMarkup(keyboard)

async def send_daily_words(chat_id: int):
    try:
        success = load_words_from_sheets()
        if not success or not words:
            await application.bot.send_message(
                chat_id=chat_id,
                text=MessageFormatter.format_error_message('no_words'),
                parse_mode='HTML'
            )
            return

        daily_words = random.sample(words, min(10, len(words)))
        message = MessageFormatter.format_daily_words(daily_words)
        
        await application.bot.send_message(
            chat_id=chat_id,
            text=message,
            parse_mode='HTML'
        )
        
    except Exception as e:
        logger.error(f"Error sending daily words: {e}")
        await application.bot.send_message(
            chat_id=chat_id,
            text=MessageFormatter.format_error_message('general_error'),
            parse_mode='HTML'
        )

def schedule_daily_notification(chat_id: int, hour: int, minute: int):
    """Schedule daily notification using APScheduler"""
    try:
        # Remove existing jobs for this chat
        for job in scheduler.get_jobs():
            if job.id == f"notify_{chat_id}":
                job.remove()
                logger.info(f"Removed existing job for chat {chat_id}")

        # Create async wrapper
        async def send_daily_words_wrapper():
            await send_daily_words(chat_id)

        # Schedule new job with retry mechanism
        scheduler.add_job(
            send_daily_words_wrapper,
            trigger=CronTrigger(hour=hour, minute=minute, timezone=DEFAULT_TIMEZONE),
            id=f"notify_{chat_id}",
            replace_existing=True,
            misfire_grace_time=3600
        )
        logger.info(f"Scheduled new job for chat {chat_id} at {hour:02d}:{minute:02d}")
        return True
    except Exception as e:
        logger.error(f"Error scheduling notification: {e}")
        return False

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle the /start command"""
    user = update.effective_user
    welcome_message = (
        f"Welcome {user.first_name} to the German Learning Bot! 🇩🇪🤖\n\n"
        "Use the buttons below to:\n"
        "🎲 Отримати слово німецькою\n"
        "📝 Протестуй знання\n"
        "🔔 Встановити щоденне нагадування\n"
        "🔄 Оновити слова"
    )

    await update.message.reply_text(
        welcome_message, 
        reply_markup=get_main_keyboard()
    )

async def button(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()

    try:
        if query.data == 'random':
            word = get_random_word()
            if word:
                response = MessageFormatter.format_word_card(word)
                await query.message.edit_text(
                    text=response,
                    reply_markup=get_main_keyboard(),
                    parse_mode='HTML'
                )
            else:
                await query.message.edit_text(
                    MessageFormatter.format_error_message('no_words'),
                    reply_markup=get_main_keyboard()
                )
                
        elif query.data == 'test':
            word = get_random_word()
            if word:
                context.user_data['test_word'] = word
                question = MessageFormatter.format_test_question(word)
                await query.message.edit_text(
                    text=question,
                    reply_markup=get_test_keyboard(word['Українською']),
                    parse_mode='HTML'
                )
            else:
                await query.message.edit_text(
                    MessageFormatter.format_error_message('no_words'),
                    reply_markup=get_main_keyboard()
                )
                
        elif query.data.startswith('answer_'):
            if 'test_word' in context.user_data:
                word = context.user_data['test_word']
                selected_answer = query.message.reply_markup.inline_keyboard[int(query.data.split('_')[1])][0].text
                is_correct = selected_answer == word['Українською']
                
                message = MessageFormatter.format_test_result(
                    word=word,
                    is_correct=is_correct,
                    user_answer=selected_answer
                )
                
                await query.message.edit_text(
                    text=message,
                    reply_markup=get_main_keyboard(),
                    parse_mode='HTML'
                )
                del context.user_data['test_word']
            else:
                await query.message.edit_text(
                    "Please start a new test.",
                    reply_markup=get_main_keyboard()
                )
                
        elif query.data == 'set_time':
            await set_notification_time(update, context)
        elif query.data == 'start_daily':
            await start_daily(update, context)
        elif query.data == 'stop_daily':
            await stop_daily(update, context)
        elif query.data == 'refresh':
            await refresh_words(update, context)
            
    except Exception as e:
        logger.error(f"Error in button handler: {e}")
        await query.message.edit_text(
            MessageFormatter.format_error_message('general_error'),
            reply_markup=get_main_keyboard()
        )
          
def get_main_keyboard():
    keyboard = [
        [InlineKeyboardButton("🎲 Отримати слово німецькою", callback_data='random')],
        [InlineKeyboardButton("📝 Протестувати знання", callback_data='test')],
        [InlineKeyboardButton("⏰ Встановити щоденний таймер", callback_data='set_time')],
        [InlineKeyboardButton("🔄 Оновити слова", callback_data='refresh')]
    ]
    return InlineKeyboardMarkup(keyboard)

async def show_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show main menu"""
    await update.message.reply_text(
        "Main menu:",
        reply_markup=get_main_keyboard()
    )
    
async def set_notification_time(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Start the conversation to set notification time"""
    if update.callback_query:
        await update.callback_query.answer()
        message = update.callback_query.message
    else:
        message = update.message

    await message.reply_text(
        "Please select the hour (00-23):",
        reply_markup=get_hour_keyboard()
    )
    return CHOOSING_HOUR

async def hour_chosen(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle hour selection"""
    text = update.message.text
    logger.info(f"Received hour selection: {text}")
    
    if text == 'Cancel':
        logger.info("Hour selection cancelled")
        await update.message.reply_text(
            "Time setting cancelled.",
            reply_markup=ReplyKeyboardRemove()
        )
        await update.message.reply_text(
            "You can continue using the bot:",
            reply_markup=get_main_keyboard()
        )
        return ConversationHandler.END
    
    try:
        hour = int(text)
        if not (0 <= hour <= 23):
            logger.warning(f"Invalid hour value: {hour}")
            await update.message.reply_text(
                "Please select a valid hour (00-23):",
                reply_markup=get_hour_keyboard()
            )
            return CHOOSING_HOUR
        
        logger.info(f"Valid hour selected: {hour}")
        context.user_data['hour'] = hour
        
        # Send minute keyboard
        minute_keyboard = get_minute_keyboard()
        await update.message.reply_text(
            "Please select the minute (00-55):",
            reply_markup=minute_keyboard
        )
        
        return CHOOSING_MINUTE
        
    except ValueError:
        logger.error(f"Could not convert hour to integer: {text}")
        await update.message.reply_text(
            "Please select a valid hour (00-23):",
            reply_markup=get_hour_keyboard()
        )
        return CHOOSING_HOUR
    
async def minute_chosen(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    text = update.message.text
    try:
        if text == 'Cancel':
            await update.message.reply_text(
                "Time setting cancelled.",
                reply_markup=ReplyKeyboardRemove()
            )
            return ConversationHandler.END

        if not text.isdigit() or not (0 <= int(text) <= 59):
            await update.message.reply_text(
                "Please select a valid minute (00-59):",
                reply_markup=get_minute_keyboard()
            )
            return CHOOSING_MINUTE

        hour = context.user_data['hour']
        minute = int(text)
        chat_id = update.effective_message.chat_id

        success = schedule_daily_notification(chat_id, hour, minute)
        
        if success:
            await update.message.reply_text(
                MessageFormatter.format_notification_set(hour, minute),
                reply_markup=ReplyKeyboardRemove(),
                parse_mode='HTML'
            )
            # Send first notification immediately
            await send_daily_words(chat_id)
        else:
            await update.message.reply_text(
                MessageFormatter.format_error_message('general_error'),
                reply_markup=ReplyKeyboardRemove()
            )
            
    except Exception as e:
        logger.error(f"Error in minute_chosen: {e}")
        await update.message.reply_text(
            MessageFormatter.format_error_message('general_error'),
            reply_markup=ReplyKeyboardRemove()
        )
    finally:
        if 'hour' in context.user_data:
            del context.user_data['hour']
            
    return ConversationHandler.END

async def start_daily(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Start daily word notifications"""
    if update.callback_query:
        chat_id = update.callback_query.message.chat_id
        message = update.callback_query.message
    else:
        chat_id = update.message.chat_id
        message = update.message

    # Check if notifications are already set
    existing_job = next((job for job in scheduler.get_jobs() if job.id == f"notify_{chat_id}"), None)
    if existing_job:
        next_run = existing_job.next_run_time.strftime("%H:%M")
        await message.reply_text(
            f"You already have notifications set for {next_run}.\n"
            "You can set a new time or stop notifications using the buttons below:",
            reply_markup=get_main_keyboard()
        )
        return ConversationHandler.END

    await message.reply_text(
        "Please set the notification time first:",
        reply_markup=get_hour_keyboard()
    )
    return CHOOSING_HOUR

async def stop_daily(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Stop daily word notifications"""
    if update.callback_query:
        chat_id = update.callback_query.message.chat_id
        message = update.callback_query.message
    else:
        chat_id = update.message.chat_id
        message = update.message
    
    # Remove job from scheduler
    jobs_removed = 0
    for job in scheduler.get_jobs():
        if job.id == f"notify_{chat_id}":
            job.remove()
            jobs_removed += 1
            logger.info(f"Removed notification job for chat {chat_id}")
    
    if jobs_removed > 0:
        await message.reply_text(
            "❌ Daily word notifications have been deactivated.",
            reply_markup=get_main_keyboard()
        )
    else:
        await message.reply_text(
            "You don't have any active notifications to stop.",
            reply_markup=get_main_keyboard()
        )

async def refresh_words(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.message or update.callback_query.message
    
    try:
        # Try to load words
        success = load_words_from_sheets()
        
        if success:
            await message.edit_text(
                f"✅ Список слів оновлено! Загальна кількість слів: {len(words)}",
                reply_markup=get_main_keyboard()
            )
        else:
            await message.edit_text(
                MessageFormatter.format_error_message('load_failed'),
                reply_markup=get_main_keyboard()
            )
    except Exception as e:
        logger.error(f"Error in refresh_words: {e}")
        await message.edit_text(
            MessageFormatter.format_error_message('general_error'),
            reply_markup=get_main_keyboard()
        )

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Cancel the conversation."""
    await update.message.reply_text(
        "Time setting cancelled.",
        reply_markup=ReplyKeyboardRemove()
    )
    await update.message.reply_text(
        "You can continue using the bot:",
        reply_markup=get_main_keyboard()
    )
    return ConversationHandler.END

async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle errors"""
    logger.error(f"Exception while handling an update: {context.error}")
    logger.exception("Full traceback:")
    
    try:
        if update and update.effective_message:
            await update.effective_message.reply_text(
                "Sorry, an error occurred. Please try again later.",
                reply_markup=get_main_keyboard()
            )
    except Exception as e:
        logger.error(f"Error sending error message: {e}")

def main():
    asyncio.run(main_async())

async def main_async():
    global application, scheduler
    try:
        # Завантаження слів
        if not load_words_from_sheets():
            logger.warning("Failed to load initial words")

        # Налаштування
        application = Application.builder().token(TOKEN).build()
        scheduler = AsyncIOScheduler(timezone=DEFAULT_TIMEZONE)
        scheduler.start()
        logger.info("APScheduler started")

        # Add conversation handler for time setting
        conv_handler = ConversationHandler(
            entry_points=[
                CommandHandler('set_time', set_notification_time),
                CallbackQueryHandler(set_notification_time, pattern='^set_time$'),
                CallbackQueryHandler(start_daily, pattern='^start_daily$')
            ],
            states={
                CHOOSING_HOUR: [
                    MessageHandler(filters.TEXT & ~filters.COMMAND, hour_chosen)
                ],
                CHOOSING_MINUTE: [
                    MessageHandler(filters.TEXT & ~filters.COMMAND, minute_chosen)
                ],
            },
            fallbacks=[
                CommandHandler('cancel', cancel),
                MessageHandler(filters.Regex('^Cancel$'), cancel)
            ],
            allow_reentry=True,
            name="notification_conversation"
        )

        # Add handlers
        application.add_handler(CommandHandler("menu", show_menu))
        application.add_handler(conv_handler)
        application.add_handler(CommandHandler("start", start))
        application.add_handler(CommandHandler("help", start))
        application.add_handler(CommandHandler("refresh", refresh_words))
        application.add_handler(CallbackQueryHandler(button))
        # Add error handler
        application.add_error_handler(error_handler)

        # Запуск
        logger.info("Bot starting polling...")
        await application.run_polling(allowed_updates=Update.ALL_TYPES)
    except Exception as e:
        logger.error(f"Error in main_async: {e}")
        logger.exception("Full traceback:")
    finally:
        await shutdown()
        
async def shutdown():
    try:
        if scheduler and scheduler.running:
            scheduler.shutdown(wait=False)
        if application:
            await application.stop()
            await application.shutdown()
        logger.info("Scheduler and application shut down successfully")
    except Exception as e:
        logger.error(f"Error during shutdown: {e}")


if __name__ == '__main__':
    main()