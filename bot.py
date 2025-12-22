#!/usr/bin/env python3
"""
Artvision Task Manager Bot
Управление задачами через Telegram с голосовым интерфейсом
"""

import os
import json
import logging
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, MessageHandler, 
    CallbackQueryHandler, filters, ContextTypes
)
import openai
import requests

# Настройка логирования
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Конфигурация
BOT_TOKEN = os.getenv("BOT_TOKEN")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
ASANA_TOKEN = os.getenv("ASANA_TOKEN")
ASANA_PROJECT = "1212305892582815"
ASANA_WORKSPACE = "860693669973770"
CHAT_ID = int(os.getenv("CHAT_ID", "-4273200821"))
MOSCOW_TZ = ZoneInfo("Europe/Moscow")

# Команда участников
TEAM = {
    "@antonkamer": {"name": "Anton", "asana_gid": "860693669618957"},
    "@PandaCaffe": {"name": "Andrey", "asana_gid": None},
    "@mig555555": {"name": "Mig", "asana_gid": None},
    "@akpersik": {"name": "Akpersik", "asana_gid": None},
}

# ═══════════════════════════════════════════════════════════════
# КОМАНДЫ БОТА
# ═══════════════════════════════════════════════════════════════

HELP_TEXT = """
🤖 **Artvision Task Manager**

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

📋 **КОМАНДЫ:**

/tasks — мои задачи
/week — план на неделю
/overdue — просроченные задачи
/today — задачи на сегодня
/help — эта справка

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

🎤 **ГОЛОСОВЫЕ КОМАНДЫ:**

**Создать задачу:**
"Новая задача: [описание] для @username до [дата]"
"Задача: сделать отчёт Бурение для @PandaCaffe до пятницы"

**Принять задачу:**
"Принял [название задачи]"
"Беру задачу отчёт Бурение"

**Сдать на проверку:**
"Готово [задача]" + прикрепи файл или ссылку
"Сделал отчёт Бурение, вот ссылка: docs.google.com/..."

**Проверить и закрыть:**
"Принято" — закрыть задачу
"Доработать: [комментарий]" — вернуть на доработку

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

🔘 **КНОПКИ:**

После получения задачи нажми:
✅ Принять — взять в работу
❌ Отклонить — отказаться
💬 Комментарий — написать вопрос

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

📊 **РАСПИСАНИЕ УВЕДОМЛЕНИЙ:**
Пн-Пт в 10:30 МСК — план на неделю + просрочки

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

💡 Вопросы? Пиши @antonkamer
"""


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /start"""
    await update.message.reply_text(
        "👋 Привет! Я бот управления задачами Artvision.\n\n"
        "Используй /help для списка команд."
    )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /help — справка по командам"""
    await update.message.reply_text(HELP_TEXT, parse_mode="Markdown")


async def tasks_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /tasks — мои задачи"""
    user = update.effective_user.username
    tg_handle = f"@{user}" if user else None
    
    if tg_handle not in TEAM:
        await update.message.reply_text(
            "❌ Ты не в команде. Обратись к @antonkamer."
        )
        return
    
    # Получаем задачи из Asana
    tasks = await get_asana_tasks(TEAM[tg_handle].get("asana_gid"))
    
    if not tasks:
        await update.message.reply_text("📭 У тебя нет активных задач.")
        return
    
    text = "📋 **Твои задачи:**\n\n"
    for t in tasks[:10]:
        due = t.get("due_on", "без срока")
        status = "⚠️" if is_overdue(due) else "📌"
        text += f"{status} {t['name']}\n   📅 {due}\n\n"
    
    await update.message.reply_text(text, parse_mode="Markdown")


async def week_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /week — план на неделю"""
    await send_weekly_plan(context, update.effective_chat.id)


async def overdue_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /overdue — просроченные задачи"""
    tasks = await get_overdue_tasks()
    
    if not tasks:
        await update.message.reply_text("✅ Нет просроченных задач!")
        return
    
    text = "⚠️ **ПРОСРОЧЕННЫЕ ЗАДАЧИ:**\n\n"
    for t in tasks[:15]:
        assignee = t.get("assignee", {}).get("name", "нет исполнителя")
        text += f"• {t['name']}\n  📅 {t.get('due_on')} — {assignee}\n\n"
    
    await update.message.reply_text(text, parse_mode="Markdown")


async def today_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /today — задачи на сегодня"""
    today = datetime.now(MOSCOW_TZ).strftime("%Y-%m-%d")
    tasks = await get_tasks_by_date(today)
    
    if not tasks:
        await update.message.reply_text("📭 На сегодня задач нет.")
        return
    
    text = f"📅 **Задачи на {today}:**\n\n"
    for t in tasks:
        assignee = t.get("assignee", {}).get("name", "—")
        text += f"• {t['name']} — {assignee}\n"
    
    await update.message.reply_text(text, parse_mode="Markdown")


# ═══════════════════════════════════════════════════════════════
# ГОЛОСОВЫЕ СООБЩЕНИЯ
# ═══════════════════════════════════════════════════════════════

async def handle_voice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка голосовых сообщений"""
    voice = update.message.voice
    
    # Скачиваем файл
    file = await context.bot.get_file(voice.file_id)
    voice_path = f"/tmp/voice_{update.message.message_id}.ogg"
    await file.download_to_drive(voice_path)
    
    # Транскрибируем через Whisper
    try:
        text = await transcribe_voice(voice_path)
        logger.info(f"Транскрипция: {text}")
        
        # Отвечаем что услышали
        await update.message.reply_text(f"🎤 Услышал: _{text}_", parse_mode="Markdown")
        
        # Парсим команду
        await process_voice_command(update, context, text)
        
    except Exception as e:
        logger.error(f"Ошибка транскрипции: {e}")
        await update.message.reply_text("❌ Не удалось распознать голос. Попробуй ещё раз.")
    finally:
        if os.path.exists(voice_path):
            os.remove(voice_path)


async def transcribe_voice(file_path: str) -> str:
    """Транскрибация голоса через OpenAI Whisper"""
    client = openai.OpenAI(api_key=OPENAI_API_KEY)
    
    with open(file_path, "rb") as audio_file:
        transcript = client.audio.transcriptions.create(
            model="whisper-1",
            file=audio_file,
            language="ru"
        )
    
    return transcript.text


async def process_voice_command(update: Update, context: ContextTypes.DEFAULT_TYPE, text: str):
    """Парсинг и выполнение голосовой команды"""
    text_lower = text.lower()
    
    # Создание задачи
    if any(kw in text_lower for kw in ["новая задача", "задача:", "создай задачу"]):
        await create_task_from_voice(update, context, text)
        return
    
    # Принять задачу
    if any(kw in text_lower for kw in ["принял", "беру", "взял"]):
        await accept_task_from_voice(update, context, text)
        return
    
    # Сдать на проверку
    if any(kw in text_lower for kw in ["готово", "сделал", "выполнил"]):
        await submit_task_from_voice(update, context, text)
        return
    
    # Закрыть задачу
    if "принято" in text_lower:
        await close_task_from_voice(update, context, text)
        return
    
    # Вернуть на доработку
    if "доработать" in text_lower:
        await return_task_from_voice(update, context, text)
        return
    
    # Не распознано
    await update.message.reply_text(
        "🤔 Не понял команду. Попробуй:\n"
        "• «Новая задача: [описание] для @username до [дата]»\n"
        "• «Принял [задачу]»\n"
        "• «Готово [задача]»\n\n"
        "Или напиши /help"
    )


async def create_task_from_voice(update: Update, context: ContextTypes.DEFAULT_TYPE, text: str):
    """Создание задачи из голоса"""
    # TODO: NLP парсинг для извлечения задачи, исполнителя, срока
    # Пока простая заглушка
    await update.message.reply_text(
        "📝 Создаю задачу...\n\n"
        f"Текст: {text}\n\n"
        "⚠️ Парсинг в разработке. Создай задачу через /new"
    )


async def accept_task_from_voice(update: Update, context: ContextTypes.DEFAULT_TYPE, text: str):
    """Принятие задачи из голоса"""
    await update.message.reply_text("✅ Задача принята! (функция в разработке)")


async def submit_task_from_voice(update: Update, context: ContextTypes.DEFAULT_TYPE, text: str):
    """Сдача задачи на проверку"""
    await update.message.reply_text("📤 Задача отправлена на проверку! (функция в разработке)")


async def close_task_from_voice(update: Update, context: ContextTypes.DEFAULT_TYPE, text: str):
    """Закрытие задачи"""
    await update.message.reply_text("✅ Задача закрыта! (функция в разработке)")


async def return_task_from_voice(update: Update, context: ContextTypes.DEFAULT_TYPE, text: str):
    """Возврат на доработку"""
    await update.message.reply_text("🔄 Задача возвращена на доработку! (функция в разработке)")


# ═══════════════════════════════════════════════════════════════
# ASANA API
# ═══════════════════════════════════════════════════════════════

async def get_asana_tasks(assignee_gid: str = None) -> list:
    """Получить задачи из Asana"""
    if not ASANA_TOKEN:
        logger.warning("ASANA_TOKEN не задан")
        return []
    
    headers = {"Authorization": f"Bearer {ASANA_TOKEN}"}
    url = f"https://app.asana.com/api/1.0/projects/{ASANA_PROJECT}/tasks"
    params = {
        "opt_fields": "name,due_on,assignee,assignee.name,completed",
        "completed_since": "now"  # только незавершённые
    }
    
    try:
        resp = requests.get(url, headers=headers, params=params)
        data = resp.json()
        tasks = data.get("data", [])
        
        # Фильтр по исполнителю если указан
        if assignee_gid:
            tasks = [t for t in tasks if t.get("assignee", {}).get("gid") == assignee_gid]
        
        return tasks
    except Exception as e:
        logger.error(f"Ошибка Asana API: {e}")
        return []


async def get_overdue_tasks() -> list:
    """Получить просроченные задачи"""
    tasks = await get_asana_tasks()
    today = datetime.now(MOSCOW_TZ).strftime("%Y-%m-%d")
    
    overdue = [t for t in tasks if t.get("due_on") and t["due_on"] < today]
    return sorted(overdue, key=lambda x: x.get("due_on", ""))


async def get_tasks_by_date(date: str) -> list:
    """Получить задачи на конкретную дату"""
    tasks = await get_asana_tasks()
    return [t for t in tasks if t.get("due_on") == date]


def is_overdue(due_on: str) -> bool:
    """Проверить просрочена ли задача"""
    if not due_on:
        return False
    today = datetime.now(MOSCOW_TZ).strftime("%Y-%m-%d")
    return due_on < today


# ═══════════════════════════════════════════════════════════════
# ЕЖЕДНЕВНЫЕ УВЕДОМЛЕНИЯ
# ═══════════════════════════════════════════════════════════════

async def send_weekly_plan(context: ContextTypes.DEFAULT_TYPE, chat_id: int = None):
    """Отправить план на неделю"""
    if chat_id is None:
        chat_id = CHAT_ID
    
    now = datetime.now(MOSCOW_TZ)
    today = now.strftime("%Y-%m-%d")
    weekday = now.strftime("%A")
    date_str = now.strftime("%d.%m")
    
    tasks = await get_asana_tasks()
    overdue = await get_overdue_tasks()
    today_tasks = [t for t in tasks if t.get("due_on") == today]
    
    # Задачи на неделю
    week_end = (now + timedelta(days=7)).strftime("%Y-%m-%d")
    week_tasks = [t for t in tasks if t.get("due_on") and today <= t["due_on"] <= week_end]
    
    # Без даты/исполнителя
    no_info = [t for t in tasks if not t.get("due_on") or not t.get("assignee")]
    
    text = f"📋 **ПЛАН НА НЕДЕЛЮ — {weekday}, {date_str}**\n\n"
    text += "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
    
    # Сегодня
    if today_tasks:
        text += f"📅 **СЕГОДНЯ ({date_str}):**\n"
        for t in today_tasks:
            assignee = t.get("assignee", {}).get("name", "нет исполнителя ⚠️")
            text += f"• {t['name']} — {assignee}\n"
        text += "\n"
    
    # Неделя
    if week_tasks:
        text += "📅 **ЭТА НЕДЕЛЯ:**\n"
        for t in sorted(week_tasks, key=lambda x: x.get("due_on", ""))[:10]:
            due = t.get("due_on", "")[-5:].replace("-", ".")
            assignee = t.get("assignee", {}).get("name", "—")
            text += f"• {due} — {t['name']} — {assignee}\n"
        text += "\n"
    
    text += "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
    
    # Просрочено
    if overdue:
        text += f"⚠️ **ПРОСРОЧЕНО ({len(overdue)}):**\n"
        for t in overdue[:10]:
            due = t.get("due_on", "")[-5:].replace("-", ".")
            assignee = t.get("assignee", {}).get("name", "нет исполнителя")
            text += f"• {due} — {t['name']} — {assignee}\n"
        text += "\n"
    
    # Без информации
    if no_info:
        text += f"❌ **БЕЗ ДАТЫ/ИСПОЛНИТЕЛЯ ({len(no_info)}):**\n"
        for t in no_info[:5]:
            text += f"• {t['name']}\n"
        text += "\n"
    
    text += "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
    text += "💡 /help — справка по командам"
    
    await context.bot.send_message(chat_id=chat_id, text=text, parse_mode="Markdown")


async def daily_notification(context: ContextTypes.DEFAULT_TYPE):
    """Ежедневное уведомление в 10:30 МСК"""
    now = datetime.now(MOSCOW_TZ)
    
    # Только рабочие дни
    if now.weekday() >= 5:  # суббота, воскресенье
        return
    
    await send_weekly_plan(context)


# ═══════════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════════

def main():
    """Запуск бота"""
    if not BOT_TOKEN:
        logger.error("BOT_TOKEN не задан!")
        return
    
    # Создаём приложение
    app = Application.builder().token(BOT_TOKEN).build()
    
    # Регистрируем обработчики
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("tasks", tasks_command))
    app.add_handler(CommandHandler("week", week_command))
    app.add_handler(CommandHandler("overdue", overdue_command))
    app.add_handler(CommandHandler("today", today_command))
    
    # Голосовые сообщения
    app.add_handler(MessageHandler(filters.VOICE, handle_voice))
    
    # Планировщик ежедневных уведомлений
    job_queue = app.job_queue
    
    # 10:30 МСК каждый день
    job_queue.run_daily(
        daily_notification,
        time=datetime.strptime("10:30", "%H:%M").time(),
        days=(0, 1, 2, 3, 4),  # пн-пт
        name="daily_plan"
    )
    
    logger.info("🤖 Бот запущен!")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
