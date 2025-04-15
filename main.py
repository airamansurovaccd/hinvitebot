import os
import csv
import time
import logging
from threading import Event
from dotenv import load_dotenv
from telegram import Bot, Update
from telegram.ext import (
    Updater,
    CommandHandler,
    MessageHandler,
    Filters,
    CallbackContext,
    DispatcherHandlerStop
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
    def wrapped(update, context, *args, **kwargs):
        if update.effective_user.id not in ADMIN_IDS:
            context.bot.send_message(
                chat_id=update.effective_chat.id,
                text="🚫 Доступ запрещен: нужны права администратора"
            )
            raise DispatcherHandlerStop
        return func(update, context, *args, **kwargs)
    return wrapped

def notify_admin(message: str):
    """Отправка уведомления админам"""
    for admin_id in ADMIN_IDS:
        try:
            bot.send_message(chat_id=admin_id, text=message)
        except Exception as e:
            logger.error(f"Ошибка уведомления админа {admin_id}: {e}")

# --- Основные функции --- #
def load_usernames(filename: str = CSV_FILE):
    """Загрузка юзернеймов из CSV"""
    try:
        with open(filename, mode='r', encoding='utf-8') as file:
            return [row[0].strip() for row in csv.reader(file) if row]
    except Exception as e:
        logger.error(f"Ошибка загрузки файла: {e}")
        return []

def add_user_to_group(username: str, context: CallbackContext):
    """Добавление одного пользователя"""
    if not username.startswith('@'):
        username = f'@{username}'
    
    try:
        context.bot.add_chat_member(
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

def process_users(usernames: list, context: CallbackContext):
    """Основной процесс добавления"""
    session_stats['total'] = len(usernames)
    
    for idx, username in enumerate(usernames, 1):
        if stop_event.is_set():
            logger.info("Процесс остановлен администратором")
            return
        
        add_user_to_group(username, context)
        
        # Обновление прогресса каждые 10 пользователей
        if idx % 10 == 0:
            progress = f"Прогресс: {idx}/{session_stats['total']} " \
                     f"(Успешно: {session_stats['success']}, " \
                     f"Ошибки: {session_stats['failed']})"
            notify_admin(progress)
        
        # Пауза между добавлениями
        time.sleep(DELAY)
    
    # Финальный отчет
    report = (
        "✅ Добавление завершено!\n"
        f"Всего: {session_stats['total']}\n"
        f"Успешно: {session_stats['success']}\n"
        f"Ошибки: {session_stats['failed']}"
    )
    notify_admin(report)

# --- Команды бота --- #
@restricted
def start_invite(update: Update, context: CallbackContext):
    """Запуск процесса добавления"""
    if stop_event.is_set():
        stop_event.clear()
    
    usernames = load_usernames()
    if not usernames:
        update.message.reply_text("❌ Файл с юзернеймами пуст или не найден")
        return
    
    update.message.reply_text(
        f"🚀 Начинаю добавление {len(usernames)} пользователей...\n"
        f"Используйте /stop для остановки"
    )
    
    # Запуск в отдельном потоке
    context.job_queue.run_once(
        lambda ctx: process_users(usernames, ctx),
        when=0
    )

@restricted
def stop_invite(update: Update, context: CallbackContext):
    """Экстренная остановка"""
    stop_event.set()
    update.message.reply_text("🛑 Процесс добавления будет остановлен!")

@restricted
def stats(update: Update, context: CallbackContext):
    """Статистика добавления"""
    stats_text = (
        "📊 Текущая статистика:\n"
        f"Всего: {session_stats['total']}\n"
        f"Успешно: {session_stats['success']}\n"
        f"Ошибки: {session_stats['failed']}\n"
        f"Осталось: {session_stats['total'] - session_stats['success'] - session_stats['failed']}"
    )
    update.message.reply_text(stats_text)

@restricted
def add_single(update: Update, context: CallbackContext):
    """Добавление одного пользователя по команде"""
    if not context.args:
        update.message.reply_text("Использование: /add @username")
        return
    
    username = context.args[0]
    if add_user_to_group(username, context):
        update.message.reply_text(f"✅ {username} успешно добавлен")
    else:
        update.message.reply_text(f"❌ Не удалось добавить {username}")

# --- Инициализация --- #
def main():
    updater = Updater(token=TOKEN, use_context=True)
    dp = updater.dispatcher

    # Регистрация команд
    dp.add_handler(CommandHandler("start", start_invite))
    dp.add_handler(CommandHandler("stop", stop_invite))
    dp.add_handler(CommandHandler("stats", stats))
    dp.add_handler(CommandHandler("add", add_single))

    # Уведомление о запуске
    notify_admin("🤖 Бот успешно запущен и готов к работе!")
    logger.info("Бот запущен")

    # Запуск бота
    updater.start_polling()
    updater.idle()

if __name__ == '__main__':
    main()