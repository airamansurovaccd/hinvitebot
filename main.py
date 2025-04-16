import os
import csv
import asyncio
import logging
from threading import Event
from dotenv import load_dotenv
from telegram import (
    Bot,
    Update,
    ReplyKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardRemove
)
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters
)

# --- Конфигурация --- #
load_dotenv()
TOKEN = os.getenv('BOT_TOKEN')
GROUP_ID = int(os.getenv('GROUP_ID'))
ADMIN_IDS = [int(id) for id in os.getenv('ADMIN_IDS').split(',')]
CSV_FILE = os.getenv('CSV_FILE', 'username.csv')
DELAY = int(os.getenv('DELAY_SECONDS', 5))

# Настройка логирования
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Глобальные переменные
stop_event = Event()
session_stats = {'success': 0, 'failed': 0, 'total': 0}

# --- Клавиатуры --- #
def get_main_keyboard():
    return ReplyKeyboardMarkup(
        [
            [KeyboardButton("▶️ Начать добавление")],
            [KeyboardButton("⏹ Остановить"), KeyboardButton("📊 Статистика")],
            [KeyboardButton("➕ Добавить пользователя")]
        ],
        resize_keyboard=True,
        one_time_keyboard=False
    )

def get_cancel_keyboard():
    return ReplyKeyboardMarkup(
        [[KeyboardButton("❌ Отмена")]],
        resize_keyboard=True
    )

# --- Утилиты --- #
def restricted(func):
    async def wrapped(update: Update, context: ContextTypes.DEFAULT_TYPE, *args, **kwargs):
        if update.effective_user.id not in ADMIN_IDS:
            await update.message.reply_text(
                "🚫 Доступ запрещен: нужны права администратора",
                reply_markup=ReplyKeyboardRemove()
            )
            return
        return await func(update, context, *args, **kwargs)
    return wrapped

async def notify_admin(context: ContextTypes.DEFAULT_TYPE, message: str):
    for admin_id in ADMIN_IDS:
        try:
            await context.bot.send_message(
                chat_id=admin_id,
                text=message,
                reply_markup=get_main_keyboard()
            )
        except Exception as e:
            logger.error(f"Ошибка уведомления админа {admin_id}: {e}")

def load_usernames():
    try:
        with open(CSV_FILE, mode='r', encoding='utf-8') as file:
            return [row[0].strip() for row in csv.reader(file) if row]
    except Exception as e:
        logger.error(f"Ошибка загрузки файла: {e}")
        return []

# --- Основные функции --- #
async def add_user_to_group(username: str, context: ContextTypes.DEFAULT_TYPE):
    if not username.startswith('@'):
        username = f'@{username}'
    
    try:
        user = await context.bot.get_chat(username)
        await context.bot.add_chat_member(
            chat_id=GROUP_ID,
            user_id=user.id
        )
        session_stats['success'] += 1
        logger.info(f"Успешно добавлен {username}")
        return True
    except Exception as e:
        session_stats['failed'] += 1
        logger.warning(f"Ошибка с {username}: {str(e)}")
        return False

async def process_users(context: ContextTypes.DEFAULT_TYPE):
    usernames = load_usernames()
    if not usernames:
        await notify_admin(context, "❌ Файл с юзернеймами пуст или не найден")
        return
    
    session_stats['total'] = len(usernames)
    
    for idx, username in enumerate(usernames, 1):
        if stop_event.is_set():
            logger.info("Процесс остановлен администратором")
            await notify_admin(context, "⏹ Добавление остановлено")
            return
        
        await add_user_to_group(username, context)
        
        if idx % 10 == 0:
            progress = (
                f"Прогресс: {idx}/{session_stats['total']}\n"
                f"✅ Успешно: {session_stats['success']}\n"
                f"❌ Ошибки: {session_stats['failed']}"
            )
            await notify_admin(context, progress)
        
        await asyncio.sleep(DELAY)
    
    report = (
        "🎉 Добавление завершено!\n"
        f"Всего: {session_stats['total']}\n"
        f"Успешно: {session_stats['success']}\n"
        f"Ошибки: {session_stats['failed']}"
    )
    await notify_admin(context, report)

# --- Обработчики сообщений --- #
@restricted
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🤖 Бот готов к работе!",
        reply_markup=get_main_keyboard()
    )

@restricted
async def handle_messages(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    
    if text == "▶️ Начать добавление":
        if stop_event.is_set():
            stop_event.clear()
        
        await update.message.reply_text(
            "🔍 Загружаю список пользователей...",
            reply_markup=get_main_keyboard()
        )
        asyncio.create_task(process_users(context))
    
    elif text == "⏹ Остановить":
        stop_event.set()
        await update.message.reply_text(
            "🛑 Процесс добавления будет остановлен!",
            reply_markup=get_main_keyboard()
        )
    
    elif text == "📊 Статистика":
        stats_text = (
            "📊 Текущая статистика:\n"
            f"• Всего: {session_stats['total']}\n"
            f"• Успешно: {session_stats['success']}\n"
            f"• Ошибки: {session_stats['failed']}\n"
            f"• Осталось: {session_stats['total'] - session_stats['success'] - session_stats['failed']}"
        )
        await update.message.reply_text(
            stats_text,
            reply_markup=get_main_keyboard()
        )
    
    elif text == "➕ Добавить пользователя":
        await update.message.reply_text(
            "Введите @username пользователя:",
            reply_markup=get_cancel_keyboard()
        )
        context.user_data['awaiting_username'] = True
    
    elif text == "❌ Отмена":
        await update.message.reply_text(
            "Действие отменено",
            reply_markup=get_main_keyboard()
        )
        context.user_data.pop('awaiting_username', None)
    
    elif context.user_data.get('awaiting_username'):
        username = text.strip()
        if await add_user_to_group(username, context):
            await update.message.reply_text(
                f"✅ {username} успешно добавлен",
                reply_markup=get_main_keyboard()
            )
        else:
            await update.message.reply_text(
                f"❌ Не удалось добавить {username}",
                reply_markup=get_main_keyboard()
            )
        context.user_data.pop('awaiting_username', None)

# --- Инициализация --- #
async def post_init(application: Application):
    await application.bot.send_message(
        chat_id=ADMIN_IDS[0],
        text="🤖 Бот успешно запущен!",
        reply_markup=get_main_keyboard()
    )

def main():
    application = Application.builder() \
        .token(TOKEN) \
        .post_init(post_init) \
        .build()

    # Регистрация обработчиков
    application.add_handler(CommandHandler("start", start))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_messages))

    application.run_polling(
        drop_pending_updates=True,
        allowed_updates=Update.ALL_TYPES
    )

if __name__ == '__main__':
    main()
