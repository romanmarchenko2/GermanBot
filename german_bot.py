import csv
import os
import random
import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes, MessageHandler, filters

# Configure logging
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

# Get the bot token from environment variable
TOKEN = os.environ.get('TELEGRAM_BOT_TOKEN')

# Load words from CSV file
words = []
try:
    with open('Meine Worte - Deutsche Wörter.csv', 'r', encoding='utf-8') as file:
        csv_reader = csv.reader(file, delimiter=',')
        headers = next(csv_reader)  # Read the header row
        for row in csv_reader:
            if len(row) >= 5:  # Ensure the row has at least 5 columns
                word = {
                    'Німецькою': row[0],
                    'Українською': row[1],
                    'Англійською': row[2],
                    'Приклад': row[3],
                    'Мнемотехніка': row[4]
                }
                words.append(word)
    logger.info(f"Loaded {len(words)} words from the CSV file")
    if words:
        logger.info(f"Sample word: {words[0]}")
    else:
        logger.warning("No words loaded from the CSV file")
except Exception as e:
    logger.error(f"Error loading CSV file: {e}")

# Function to get a random word
def get_random_word():
    return random.choice(words) if words else None

# Function to get 3 random wrong answers
def get_wrong_answers(correct_answer):
    wrong_answers = []
    while len(wrong_answers) < 3:
        word = random.choice(words)
        if word['Українською'] != correct_answer and word['Українською'] not in wrong_answers:
            wrong_answers.append(word['Українською'])
    return wrong_answers

# Create an inline keyboard markup
def get_main_keyboard():
    keyboard = [
        [InlineKeyboardButton("🎲 Get a random word", callback_data='random')],
        [InlineKeyboardButton("📝 Test me", callback_data='test')]
    ]
    return InlineKeyboardMarkup(keyboard)

# Create a keyboard for test answers
def get_test_keyboard(correct_answer):
    wrong_answers = get_wrong_answers(correct_answer)
    all_answers = wrong_answers + [correct_answer]
    random.shuffle(all_answers)
    keyboard = [[InlineKeyboardButton(answer, callback_data=f'answer_{i}')] for i, answer in enumerate(all_answers)]
    return InlineKeyboardMarkup(keyboard)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "Welcome to the German Learning Bot! 🇩🇪🤖\nUse the buttons below to learn new words or test yourself.",
        reply_markup=get_main_keyboard()
    )

async def button(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()

    if query.data == 'random':
        word = get_random_word()
        if word:
            try:
                response = f"🇩🇪 German: {word['Німецькою']}\n🇺🇦 Ukrainian: {word['Українською']}\n🇬🇧 English: {word['Англійською']}\n📚 Example: {word['Приклад']}"
                await query.message.reply_text(response, reply_markup=get_main_keyboard())
            except KeyError as e:
                logger.error(f"KeyError in word dictionary: {e}")
                await query.message.reply_text("Sorry, there was an error processing the word. Please try again.", reply_markup=get_main_keyboard())
        else:
            await query.message.reply_text("Sorry, no words are available. Please check the CSV file.", reply_markup=get_main_keyboard())
    elif query.data == 'test':
        word = get_random_word()
        if word:
            context.user_data['test_word'] = word
            await query.message.reply_text(
                f"🇩🇪➡️🇺🇦 What's the Ukrainian translation of '{word['Німецькою']}'?",
                reply_markup=get_test_keyboard(word['Українською'])
            )
        else:
            await query.message.reply_text("Sorry, no words are available for testing. Please check the CSV file.", reply_markup=get_main_keyboard())
    elif query.data.startswith('answer_'):
        if 'test_word' in context.user_data:
            word = context.user_data['test_word']
            selected_answer = query.message.reply_markup.inline_keyboard[int(query.data.split('_')[1])][0].text
            if selected_answer == word['Українською']:
                await query.message.reply_text("✅ Correct! Well done!", reply_markup=get_main_keyboard())
            else:
                await query.message.reply_text(f"❌ Sorry, that's incorrect. The correct answer is '{word['Українською']}'.", reply_markup=get_main_keyboard())
            del context.user_data['test_word']
        else:
            await query.message.reply_text("Please start a new test.", reply_markup=get_main_keyboard())

async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.error(f"Exception while handling an update: {context.error}")

def main() -> None:
    application = Application.builder().token(TOKEN).build()

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CallbackQueryHandler(button))
    application.add_handler(CommandHandler("help", start))

    # Add error handler
    application.add_error_handler(error_handler)

    application.run_polling()

if __name__ == '__main__':
    main()