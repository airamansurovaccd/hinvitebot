import os
import csv
import asyncio
import logging
from threading import Event
from dotenv import load_dotenv
from telegram import Bot, Update
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
    """Декоратор для ограничения доступа только админам"""
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
    """Отправка уведомления админам"""
    for admin_id in ADMIN_IDS:
        try:
            await bot.send_message(chat_id=admin_id, text=message)
        except Exception as e:
            logger.error(f"Ошибка уведомления админа {admin_id}: {e}")

def load_usernames(filename: str = CSV_FILE):
    """Загрузка юзернеймов из CSV (синхронная)"""
    try:
        with open(filename, mode='r', encoding='utf-8') as file:
            return [row[0].strip() for row in csv.reader(file) if row]
    except Exception as e:
        logger.error(f"Ошибка загрузки файла: {e}")
        return []

# --- Основные функции --- #
async def add_user_to_group(username: str, context: ContextTypes.DEFAULT_TYPE):
    """Добавление одного пользователя"""
    if not username.startswith('@'):
        username = f'@{username}'
    
    try:
        await context.bot.add_chat_member(
            chat_id=GROUP_ID,
            user_id=username
        )
        session_stats['success'] += 1
        logger.info(f"Успешно добавлен {username}")
        return True
    except Exception as e:
        session_stats['failed'] += 1
        logger.warning(f"Ошибка с {username}: {str(e)}")
        return False

async def process_users(usernames: list, context: ContextTypes.DEFAULT_TYPE):
    """Основной процесс добавления"""
    session_stats['total'] = len(usernames)
    
    for idx, username in enumerate(usernames, 1):
        if stop_event.is_set():
            logger.info("Процесс остановлен администратором")
            return
        
        await add_user_to_group(username, context)
        
        if idx % 10 == 0:
            progress = f"Прогресс: {idx}/{session_stats['total']} " \
                     f"(Успешно: {session_stats['success']}, " \
                     f"Ошибки: {session_stats['failed']})"
            await notify_admin(progress)
        
        await asyncio.sleep(DELAY)
    
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
    """Запуск процесса добавления"""
    if stop_event.is_set():
        stop_event.clear()
    
    usernames = await asyncio.to_thread(load_usernames)
    if not usernames:
        await update.message.reply_text("❌ Файл с юзернеймами пуст или не найден")
        return
    
    await update.message.reply_text(
        f"🚀 Начинаю добавление {len(usernames)} пользователей...\n"
        f"Используйте /stop для остановки"
    )
    
    asyncio.create_task(process_users(usernames, context))

@restricted
async def stop_invite(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Экстренная остановка"""
    stop_event.set()
    await update.message.reply_text("🛑 Процесс добавления будет остановлен!")

@restricted
async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Статистика добавления"""
    stats_text = (
        "📊 Текущая статистика:\n"
        f"Всего: {session_stats['total']}\n"
        f"Успешно: {session_stats['success']}\n"
        f"Ошибки: {session_stats['failed']}\n"
        f"Осталось: {session_stats['total'] - session_stats['success'] - session_stats['failed']}"
    )
    await update.message.reply_text(stats_text)

@restricted
async def add_single(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Добавление одного пользователя по команде"""
    if not context.args:
        await update.message.reply_text("Использование: /add @username")
        return
    
    username = context.args[0]
    if await add_user_to_group(username, context):
        await update.message.reply_text(f"✅ {username} успешно добавлен")
    else:
        await update.message.reply_text(f"❌ Не удалось добавить {username}")

# --- Инициализация --- #
async def on_startup(app: Application):
    """Выполняется при запуске бота"""
    await notify_admin("🤖 Бот успешно запущен и готов к работе!")

def main():
    # Создаем Application с обработчиком запуска
    application = Application.builder() \
        .token(TOKEN) \
        .post_init(on_startup) \
        .build()

    # Регистрация команд
    application.add_handler(CommandHandler("start", start_invite))
    application.add_handler(CommandHandler("stop", stop_invite))
    application.add_handler(CommandHandler("stats", stats))
    application.add_handler(CommandHandler("add", add_single))

    logger.info("Запуск бота...")
    application.run_polling()

if __name__ == '__main__':
    main()
