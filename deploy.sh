#!/bin/bash
# Деплой Artvision Task Manager Bot на VPS
# Запуск: bash deploy.sh

set -e

echo "🚀 Деплой Artvision Bot..."

# Создаём директорию
mkdir -p /opt/artvision-bot
cd /opt/artvision-bot

# Создаём .env
cat > .env << 'ENVEOF'
# Telegram
BOT_TOKEN=8570860596:AAG8sAPiClGDCGCQi8SMltJFGW5sRUcJdns
CHAT_ID=-4273200821

# OpenAI (Whisper)
OPENAI_API_KEY=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

# Asana
ASANA_TOKEN=2/860693669618957/1212561864093885:78afd287e878d07f01705f1f3402c25e
ENVEOF

# Создаём requirements.txt
cat > requirements.txt << 'REQEOF'
python-telegram-bot[job-queue]==20.7
openai>=1.0.0
requests>=2.31.0
APScheduler>=3.10.0
python-dotenv>=1.0.0
REQEOF

# Создаём bot.py
cat > bot.py << 'BOTEOF'
#!/usr/bin/env python3
"""Artvision Task Manager Bot — Гибридная версия"""

import os
import logging
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from dotenv import load_dotenv

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, MessageHandler, 
    CallbackQueryHandler, filters, ContextTypes
)
import openai
import requests

load_dotenv()

# Настройка
logging.basicConfig(format='%(asctime)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

BOT_TOKEN = os.getenv("BOT_TOKEN")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
ASANA_TOKEN = os.getenv("ASANA_TOKEN")
ASANA_PROJECT = "1212305892582815"
CHAT_ID = int(os.getenv("CHAT_ID", "-4273200821"))
MOSCOW_TZ = ZoneInfo("Europe/Moscow")

TEAM = {
    "@antonkamer": {"name": "Anton", "asana_gid": "860693669618957"},
    "@PandaCaffe": {"name": "Andrey", "asana_gid": None},
    "@mig555555": {"name": "Mig", "asana_gid": None},
    "@akpersik": {"name": "Akpersik", "asana_gid": None},
}

HELP_TEXT = """
🤖 *Artvision Task Manager*

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

📋 *КОМАНДЫ:*
/tasks — мои задачи
/week — план на неделю
/overdue — просроченные
/today — на сегодня
/help — справка

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

🎤 *ГОЛОСОВЫЕ:*
• "Новая задача: [описание] для @user до [дата]"
• "Принял [задачу]"
• "Готово [задача]"

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

📊 *УВЕДОМЛЕНИЯ:*
Пн-Пт в 10:30 МСК

💡 Вопросы → @antonkamer
"""


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("👋 Привет! Я бот Artvision.\n/help — справка")


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(HELP_TEXT, parse_mode="Markdown")


async def get_asana_tasks(assignee_gid=None):
    """Получить задачи из Asana"""
    if not ASANA_TOKEN:
        return []
    
    headers = {"Authorization": f"Bearer {ASANA_TOKEN}"}
    url = f"https://app.asana.com/api/1.0/projects/{ASANA_PROJECT}/tasks"
    params = {"opt_fields": "name,due_on,assignee,assignee.name,completed", "completed_since": "now"}
    
    try:
        resp = requests.get(url, headers=headers, params=params, timeout=10)
        tasks = resp.json().get("data", [])
        if assignee_gid:
            tasks = [t for t in tasks if t.get("assignee", {}).get("gid") == assignee_gid]
        return tasks
    except Exception as e:
        logger.error(f"Asana error: {e}")
        return []


async def tasks_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = f"@{update.effective_user.username}" if update.effective_user.username else None
    gid = TEAM.get(user, {}).get("asana_gid")
    tasks = await get_asana_tasks(gid)
    
    if not tasks:
        await update.message.reply_text("📭 Нет активных задач.")
        return
    
    today = datetime.now(MOSCOW_TZ).strftime("%Y-%m-%d")
    text = "📋 *Твои задачи:*\n\n"
    for t in tasks[:15]:
        due = t.get("due_on", "—")
        icon = "🔥" if due and due < today else "📌"
        text += f"{icon} {t['name']}\n   📅 {due}\n\n"
    
    await update.message.reply_text(text, parse_mode="Markdown")


async def week_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await send_weekly_plan(context, update.effective_chat.id)


async def overdue_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    tasks = await get_asana_tasks()
    today = datetime.now(MOSCOW_TZ).strftime("%Y-%m-%d")
    overdue = [t for t in tasks if t.get("due_on") and t["due_on"] < today]
    
    if not overdue:
        await update.message.reply_text("✅ Нет просроченных задач!")
        return
    
    text = f"⚠️ *ПРОСРОЧЕНО ({len(overdue)}):*\n\n"
    for t in overdue[:15]:
        assignee = t.get("assignee", {}).get("name", "—")
        text += f"• {t['name']}\n  📅 {t.get('due_on')} — {assignee}\n\n"
    
    await update.message.reply_text(text, parse_mode="Markdown")


async def today_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    tasks = await get_asana_tasks()
    today = datetime.now(MOSCOW_TZ).strftime("%Y-%m-%d")
    today_tasks = [t for t in tasks if t.get("due_on") == today]
    
    if not today_tasks:
        await update.message.reply_text("📭 На сегодня задач нет.")
        return
    
    text = f"📅 *Сегодня ({today}):*\n\n"
    for t in today_tasks:
        assignee = t.get("assignee", {}).get("name", "—")
        text += f"• {t['name']} — {assignee}\n"
    
    await update.message.reply_text(text, parse_mode="Markdown")


async def send_weekly_plan(context: ContextTypes.DEFAULT_TYPE, chat_id=None):
    """Отправить план на неделю"""
    if chat_id is None:
        chat_id = CHAT_ID
    
    now = datetime.now(MOSCOW_TZ)
    today = now.strftime("%Y-%m-%d")
    date_str = now.strftime("%d.%m")
    weekdays_ru = ["Понедельник", "Вторник", "Среда", "Четверг", "Пятница", "Суббота", "Воскресенье"]
    weekday = weekdays_ru[now.weekday()]
    
    tasks = await get_asana_tasks()
    
    # Сегодня
    today_tasks = [t for t in tasks if t.get("due_on") == today]
    
    # Просрочено
    overdue = [t for t in tasks if t.get("due_on") and t["due_on"] < today]
    
    # На неделю
    week_end = (now + timedelta(days=7)).strftime("%Y-%m-%d")
    week_tasks = [t for t in tasks if t.get("due_on") and today < t["due_on"] <= week_end]
    
    # Без даты/исполнителя
    no_info = [t for t in tasks if not t.get("due_on") or not t.get("assignee")]
    
    text = f"📋 *ПЛАН — {weekday}, {date_str}*\n\n"
    text += "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
    
    if today_tasks:
        text += f"📅 *СЕГОДНЯ ({date_str}):*\n"
        for t in today_tasks:
            assignee = t.get("assignee", {}).get("name", "⚠️")
            text += f"• {t['name']} — {assignee}\n"
        text += "\n"
    
    if week_tasks:
        text += "📅 *ЭТА НЕДЕЛЯ:*\n"
        for t in sorted(week_tasks, key=lambda x: x.get("due_on", ""))[:10]:
            due = t.get("due_on", "")[-5:].replace("-", ".")
            assignee = t.get("assignee", {}).get("name", "—")
            text += f"• {due} — {t['name']} — {assignee}\n"
        text += "\n"
    
    if overdue:
        text += "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        text += f"⚠️ *ПРОСРОЧЕНО ({len(overdue)}):*\n"
        for t in overdue[:10]:
            due = t.get("due_on", "")[-5:].replace("-", ".")
            assignee = t.get("assignee", {}).get("name", "—")
            text += f"• {due} — {t['name']} — {assignee}\n"
        text += "\n"
    
    if no_info:
        text += f"❌ *БЕЗ ДАТЫ/ИСПОЛНИТЕЛЯ ({len(no_info)}):*\n"
        for t in no_info[:5]:
            text += f"• {t['name']}\n"
        text += "\n"
    
    text += "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
    text += "💡 /help — справка"
    
    await context.bot.send_message(chat_id=chat_id, text=text, parse_mode="Markdown")


async def handle_voice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка голосовых"""
    voice = update.message.voice
    file = await context.bot.get_file(voice.file_id)
    voice_path = f"/tmp/voice_{update.message.message_id}.ogg"
    await file.download_to_drive(voice_path)
    
    try:
        client = openai.OpenAI(api_key=OPENAI_API_KEY)
        with open(voice_path, "rb") as f:
            transcript = client.audio.transcriptions.create(model="whisper-1", file=f, language="ru")
        text = transcript.text
        
        await update.message.reply_text(f"🎤 _{text}_\n\n⚠️ Умный разбор в разработке. Пока используй команды /help", parse_mode="Markdown")
    except Exception as e:
        logger.error(f"Whisper error: {e}")
        await update.message.reply_text("❌ Не распознал. Попробуй ещё.")
    finally:
        if os.path.exists(voice_path):
            os.remove(voice_path)


async def daily_notification(context: ContextTypes.DEFAULT_TYPE):
    """Ежедневное уведомление 10:30"""
    now = datetime.now(MOSCOW_TZ)
    if now.weekday() >= 5:  # сб, вс
        return
    await send_weekly_plan(context)


def main():
    if not BOT_TOKEN:
        logger.error("BOT_TOKEN не задан!")
        return
    
    app = Application.builder().token(BOT_TOKEN).build()
    
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("tasks", tasks_command))
    app.add_handler(CommandHandler("week", week_command))
    app.add_handler(CommandHandler("overdue", overdue_command))
    app.add_handler(CommandHandler("today", today_command))
    app.add_handler(MessageHandler(filters.VOICE, handle_voice))
    
    # Уведомления 10:30 МСК
    from datetime import time
    app.job_queue.run_daily(
        daily_notification,
        time=time(hour=7, minute=30),  # UTC = 10:30 MSK
        days=(0, 1, 2, 3, 4),
        name="daily"
    )
    
    logger.info("🤖 Бот запущен!")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
BOTEOF

echo "📦 Установка зависимостей..."
pip3 install -r requirements.txt -q

echo "🔄 Создаю systemd сервис..."
cat > /etc/systemd/system/artvision-bot.service << 'SVCEOF'
[Unit]
Description=Artvision Task Manager Bot
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory=/opt/artvision-bot
ExecStart=/usr/bin/python3 /opt/artvision-bot/bot.py
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
SVCEOF

systemctl daemon-reload
systemctl enable artvision-bot
systemctl restart artvision-bot

echo ""
echo "✅ Бот запущен!"
echo ""
echo "Команды:"
echo "  systemctl status artvision-bot  — статус"
echo "  journalctl -u artvision-bot -f  — логи"
echo "  systemctl restart artvision-bot — перезапуск"
