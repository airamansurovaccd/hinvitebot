import os
import csv
import time
import logging
from threading import Event
from dotenv import load_dotenv
from telegram import Update, Bot
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    filters,
    ContextTypes,
)

# --- Конфигурация --- #
load_dotenv()
TOKEN = os.getenv('BOT_TOKEN')
GROUP_ID = int(os.getenv('GROUP_ID'))
ADMIN_IDS = [int(id) for id in os.getenv('ADMIN_IDS').split(',')]
CSV_FILE = os.getenv('CSV_FILE', 'username.csv')
DELAY = int(os.getenv('DELAY_SECONDS', 7))

# Настройка логирования
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Глобальные переменные
bot = Bot(token=TOKEN)
stop_event = Event()
session_stats = {'success': 0, 'failed': 0, 'total': 0}

# --- Утилиты --- #
def restricted(func):
    async def wrapped(update: Update, context: ContextTypes.DEFAULT_TYPE, *args, **kwargs):
        if update.effective_user.id not in ADMIN_IDS:
            await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text="🚫 Доступ запрещен: нужны права администратора"
            )
            return
        return await func(update, context, *args, **kwargs)
    return wrapped

async def notify_admin(message: str):
    for admin_id in ADMIN_IDS:
        try:
            await bot.send_message(chat_id=admin_id, text=message)
        except Exception as e:
            logger.error(f"Ошибка уведомления админа {admin_id}: {e}")

# --- Основные функции --- #
async def add_user_to_group(username: str, context: ContextTypes.DEFAULT_TYPE):
    if not username.startswith('@'):
        username = f'@{username}'
    
    try:
        await context.bot.add_chat_member(chat_id=GROUP_ID, user_id=username)
        session_stats['success'] += 1
        logger.info(f"Успешно добавлен {username}")
        return True
    except Exception as e:
        session_stats['failed'] += 1
        logger.warning(f"Ошибка с {username}: {str(e)}")
        return False

async def process_users(usernames: list, context: ContextTypes.DEFAULT_TYPE):
    session_stats['total'] = len(usernames)
    
    for idx, username in enumerate(usernames, 1):
        if stop_event.is_set():
            logger.info("Процесс остановлен администратором")
            return
        
        await add_user_to_group(username, context)
        
        if idx % 10 == 0:
            progress = f"Прогресс: {idx}/{session_stats['total']} (Успешно: {session_stats['success']}, Ошибки: {session_stats['failed']})"
            await notify_admin(progress)
        
        time.sleep(DELAY)
    
    report = (
        "✅ Добавление завершено!\n"
        f"Всего: {session_stats['total']}\n"
        f"Успешно: {session_stats['success']}\n"
        f"Ошибки: {session_stats['failed']}"
    )
    await notify_admin(report)

# --- Команды бота --- #
@restricted
async def start_invite(update: Update, context: ContextTypes.DEFAULT_TYPE):
    usernames = load_usernames()
    if not usernames:
        await update.message.reply_text("❌ Файл с юзернеймами пуст или не найден")
        return
    
    await update.message.reply_text(
        f"🚀 Начинаю добавление {len(usernames)} пользователей...\n"
        f"Используйте /stop для остановки"
    )
    
    context.job_queue.run_once(
        lambda ctx: process_users(usernames, ctx),
        when=0
    )

# --- Запуск --- #
def main():
    application = Application.builder().token(TOKEN).build()
    
    application.add_handler(CommandHandler("start", start_invite))
    # ... остальные обработчики
    
    application.run_polling()

if __name__ == '__main__':
    main()
