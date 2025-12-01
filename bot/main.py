"""
Contacts Manager Bot - Main
Telegram бот для управления контактами с ИИ-интерфейсом
"""

import os
import logging
from dotenv import load_dotenv

from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    filters,
    ContextTypes
)
from supabase import create_client, Client

from handlers import ContactHandlers
from ai_interface import AIInterface

# Загрузка переменных окружения
load_dotenv()

# Настройка логирования
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Инициализация Supabase клиента
SUPABASE_URL = os.getenv('SUPABASE_URL')
SUPABASE_KEY = os.getenv('SUPABASE_KEY')

if not SUPABASE_URL or not SUPABASE_KEY:
    raise ValueError("SUPABASE_URL и SUPABASE_KEY должны быть установлены в .env файле")

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

# Инициализация обработчиков
contact_handlers = ContactHandlers(supabase)
ai_interface = AIInterface(supabase)


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /start - приветствие"""
    welcome_message = """👋 **Добро пожаловать в Contacts Manager!**

Я помогу вам управлять контактами и находить нужных людей с помощью ИИ.

**Основные команды:**

📝 **Добавление контактов:**
/quick - Быстрое добавление одной строкой
/add - Интерактивное добавление

💬 **Заметки:**
/note - Добавить заметку к контакту

🔍 **Поиск:**
/find - Найти контакт
/list - Показать последние контакты

📊 **Статистика:**
/stats - Показать статистику

🤖 **ИИ-запросы:**
Просто напишите мне вопрос, например:
• Кто у меня есть из HR?
• С кем я познакомился на AI Summit?
• Покажи всех, с кем я не общался больше месяца

Нужна помощь? Используйте /help"""

    await update.message.reply_text(welcome_message, parse_mode='Markdown')


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /help - справка"""
    help_text = """📖 **Справка по командам**

**Добавление контакта:**
`/quick Иван Петров, TechCorp, HR Manager, ivan@tech.com, @ivan_hr`

**Добавление заметки:**
`/note @ivan_hr Созвонились, обсудили вакансию`
`/note ivan@tech.com Купил курс по Python за 15000₽`

**Поиск:**
`/find Иван` - поиск по имени
`/find TechCorp` - поиск по компании
`/find HR` - поиск по тегу

**ИИ-запросы (без команд):**
Просто напишите вопрос:
• Кто у меня есть из HR?
• С кем я не общался больше 2 месяцев?
• Кто покупал у меня в ноябре?

**Статистика:**
/stats - общая статистика по контактам

**Формат быстрого добавления:**
Имя, Компания, Должность, email, @telegram

Минимально нужно только имя, остальное опционально."""

    await update.message.reply_text(help_text, parse_mode='Markdown')


async def stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /stats - статистика"""
    stats = await ai_interface.get_contact_stats()
    await update.message.reply_text(stats, parse_mode='Markdown')


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Обработка обычных сообщений (без команд)
    Пересылать в ИИ для обработки запроса
    """
    user_message = update.message.text
    
    # Показать индикатор "печатает..."
    await update.message.chat.send_action(action="typing")
    
    # Проверка на pending заметку
    if 'pending_note_contact_id' in context.user_data:
        # Пользователь отправляет первую заметку после добавления контакта
        contact_id = context.user_data['pending_note_contact_id']
        
        try:
            # Определить тип и сохранить заметку
            interaction_type = contact_handlers._detect_interaction_type(user_message)
            
            supabase.table('interactions').insert({
                'contact_id': contact_id,
                'type': interaction_type,
                'note': user_message
            }).execute()
            
            await update.message.reply_text(
                f"✅ Заметка сохранена!\n"
                f"Тип: {interaction_type}"
            )
            
            # Очистить pending статус
            del context.user_data['pending_note_contact_id']
            return
            
        except Exception as e:
            await update.message.reply_text(f"❌ Ошибка: {str(e)}")
            return
    
    # Обработка как ИИ-запрос
    try:
        response = await ai_interface.process_query(user_message)
        await update.message.reply_text(response, parse_mode='Markdown')
    except Exception as e:
        logger.error(f"Ошибка обработки запроса: {e}")
        await update.message.reply_text(
            "❌ Произошла ошибка при обработке запроса. Попробуйте переформулировать вопрос."
        )


async def skip_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Пропустить добавление заметки"""
    if 'pending_note_contact_id' in context.user_data:
        del context.user_data['pending_note_contact_id']
        await update.message.reply_text("✅ Пропущено")
    else:
        await update.message.reply_text("Нечего пропускать 😊")


def main():
    """Запуск бота"""
    # Получить токен бота
    token = os.getenv('TELEGRAM_BOT_TOKEN')
    if not token:
        raise ValueError("TELEGRAM_BOT_TOKEN не найден в .env файле")
    
    # Создать приложение
    application = Application.builder().token(token).build()
    
    # Регистрация обработчиков команд
    
    # --- БЛОКИРОВКА ДОСТУПА ДЛЯ ПОСТОРОННИХ ---
    ADMIN_ID = 1031225569
    
    async def unauthorized_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработчик для неавторизованных пользователей"""
        await update.message.reply_text(
            "⛔️ Если вам нужен такой бот, обратитесь к @alexander_stashenko"
        )

    # Этот хендлер должен быть ПЕРВЫМ. 
    # ~filters.User(user_id=ADMIN_ID) означает "все пользователи КРОМЕ админа"
    # block=False не ставим, чтобы он прерывал цепочку (по умолчанию в PTB один хендлер срабатывает)
    # Но постойте, в PTB по умолчанию срабатывает первый подходящий хендлер в группе.
    # Если мы добавим его первым, он перехватит всё для чужаков.
    application.add_handler(MessageHandler(~filters.User(user_id=ADMIN_ID), unauthorized_handler), group=0)
    # -------------------------------------------

    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("stats", stats_command))
    application.add_handler(CommandHandler("skip", skip_command))
    
    # Обработчики контактов
    application.add_handler(CommandHandler("add", contact_handlers.add_contact_interactive))
    application.add_handler(CommandHandler("quick", contact_handlers.quick_add_contact))
    application.add_handler(CommandHandler("note", contact_handlers.add_note))
    application.add_handler(CommandHandler("find", contact_handlers.find_contact))
    application.add_handler(CommandHandler("list", contact_handlers.list_recent_contacts))
    
    # Обработчик файлов (импорт контактов)
    application.add_handler(MessageHandler(filters.Document.ALL, contact_handlers.handle_document))
    
    # Обработчик обычных сообщений (ИИ-запросы)
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    
    # Запуск бота
    logger.info("🤖 Бот запущен!")
    application.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == '__main__':
    main()
