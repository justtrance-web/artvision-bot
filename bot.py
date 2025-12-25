#!/usr/bin/env python3
"""
Artvision Task Manager Bot
Управление задачами через Telegram с голосовым интерфейсом + трекер времени
"""

import os
import json
import logging
import sqlite3
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from pathlib import Path

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
BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
ASANA_TOKEN = os.getenv("ASANA_TOKEN")
ASANA_PROJECT = os.getenv("ASANA_PROJECT", "1212305892582815")
ASANA_WORKSPACE = os.getenv("ASANA_WORKSPACE", "860693669973770")
ADMIN_IDS = [int(x) for x in os.getenv("ADMIN_IDS", "161261652").split(",")]
MOSCOW_TZ = ZoneInfo("Europe/Moscow")

# База данных
DB_PATH = Path("/data/timetracker.db") if os.path.exists("/data") else Path("timetracker.db")

# Команда участников
TEAM = {
    "@antonkamer": {"name": "Anton", "asana_gid": "860693669618957"},
    "@PandaCaffe": {"name": "Andrey", "asana_gid": None},
    "@mig555555": {"name": "Mig", "asana_gid": None},
    "@akpersik": {"name": "Akpersik", "asana_gid": None},
}

# ═══════════════════════════════════════════════════════════════
# БАЗА ДАННЫХ (SQLite)
# ═══════════════════════════════════════════════════════════════

def init_db():
    """Инициализация базы данных"""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    
    # Таблица сессий трекинга
    c.execute('''
        CREATE TABLE IF NOT EXISTS time_sessions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            username TEXT,
            task_name TEXT,
            asana_task_id TEXT,
            started_at TIMESTAMP NOT NULL,
            ended_at TIMESTAMP,
            duration_minutes INTEGER,
            notes TEXT
        )
    ''')
    
    # Индексы
    c.execute('CREATE INDEX IF NOT EXISTS idx_user_id ON time_sessions(user_id)')
    c.execute('CREATE INDEX IF NOT EXISTS idx_started_at ON time_sessions(started_at)')
    
    conn.commit()
    conn.close()
    logger.info(f"✅ БД инициализирована: {DB_PATH}")

def get_active_session(user_id: int) -> dict | None:
    """Получить активную сессию пользователя"""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('''
        SELECT id, task_name, asana_task_id, started_at 
        FROM time_sessions 
        WHERE user_id = ? AND ended_at IS NULL
        ORDER BY started_at DESC LIMIT 1
    ''', (user_id,))
    row = c.fetchone()
    conn.close()
    
    if row:
        return {
            "id": row[0],
            "task_name": row[1],
            "asana_task_id": row[2],
            "started_at": datetime.fromisoformat(row[3])
        }
    return None

def start_session(user_id: int, username: str, task_name: str, asana_task_id: str = None) -> int:
    """Начать новую сессию"""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('''
        INSERT INTO time_sessions (user_id, username, task_name, asana_task_id, started_at)
        VALUES (?, ?, ?, ?, ?)
    ''', (user_id, username, task_name, asana_task_id, datetime.now(MOSCOW_TZ).isoformat()))
    session_id = c.lastrowid
    conn.commit()
    conn.close()
    return session_id

def stop_session(user_id: int, notes: str = None) -> dict | None:
    """Остановить активную сессию"""
    session = get_active_session(user_id)
    if not session:
        return None
    
    ended_at = datetime.now(MOSCOW_TZ)
    started_at = session["started_at"]
    if started_at.tzinfo is None:
        started_at = started_at.replace(tzinfo=MOSCOW_TZ)
    
    duration = int((ended_at - started_at).total_seconds() / 60)
    
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('''
        UPDATE time_sessions 
        SET ended_at = ?, duration_minutes = ?, notes = ?
        WHERE id = ?
    ''', (ended_at.isoformat(), duration, notes, session["id"]))
    conn.commit()
    conn.close()
    
    return {
        "task_name": session["task_name"],
        "duration_minutes": duration,
        "started_at": started_at,
        "ended_at": ended_at
    }

def get_today_stats(user_id: int) -> dict:
    """Статистика за сегодня"""
    today = datetime.now(MOSCOW_TZ).date().isoformat()
    
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    
    # Завершённые сессии
    c.execute('''
        SELECT SUM(duration_minutes), COUNT(*) 
        FROM time_sessions 
        WHERE user_id = ? AND date(started_at) = ? AND ended_at IS NOT NULL
    ''', (user_id, today))
    row = c.fetchone()
    total_minutes = row[0] or 0
    sessions_count = row[1] or 0
    
    # Список задач
    c.execute('''
        SELECT task_name, SUM(duration_minutes) as total
        FROM time_sessions 
        WHERE user_id = ? AND date(started_at) = ? AND ended_at IS NOT NULL
        GROUP BY task_name
        ORDER BY total DESC
    ''', (user_id, today))
    tasks = c.fetchall()
    
    conn.close()
    
    return {
        "total_minutes": total_minutes,
        "sessions_count": sessions_count,
        "tasks": [(t[0], t[1]) for t in tasks]
    }

def get_week_stats(user_id: int) -> dict:
    """Статистика за неделю"""
    week_ago = (datetime.now(MOSCOW_TZ) - timedelta(days=7)).date().isoformat()
    
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    
    c.execute('''
        SELECT date(started_at) as day, SUM(duration_minutes) as total
        FROM time_sessions 
        WHERE user_id = ? AND date(started_at) >= ? AND ended_at IS NOT NULL
        GROUP BY day
        ORDER BY day
    ''', (user_id, week_ago))
    days = c.fetchall()
    
    c.execute('''
        SELECT SUM(duration_minutes)
        FROM time_sessions 
        WHERE user_id = ? AND date(started_at) >= ? AND ended_at IS NOT NULL
    ''', (user_id, week_ago))
    total = c.fetchone()[0] or 0
    
    conn.close()
    
    return {
        "total_minutes": total,
        "days": [(d[0], d[1]) for d in days]
    }

# ═══════════════════════════════════════════════════════════════
# ASANA API
# ═══════════════════════════════════════════════════════════════

def asana_request(method: str, endpoint: str, data: dict = None) -> dict:
    """Запрос к Asana API"""
    headers = {
        "Authorization": f"Bearer {ASANA_TOKEN}",
        "Content-Type": "application/json"
    }
    url = f"https://app.asana.com/api/1.0{endpoint}"
    
    try:
        if method == "GET":
            resp = requests.get(url, headers=headers, params=data, timeout=10)
        elif method == "POST":
            resp = requests.post(url, headers=headers, json={"data": data}, timeout=10)
        else:
            resp = requests.request(method, url, headers=headers, json={"data": data}, timeout=10)
        
        resp.raise_for_status()
        return resp.json().get("data", {})
    except Exception as e:
        logger.error(f"Asana API error: {e}")
        return {}

def get_my_tasks(assignee: str = "me", limit: int = 10) -> list:
    """Получить задачи пользователя"""
    endpoint = "/tasks"
    params = {
        "assignee": assignee,
        "workspace": ASANA_WORKSPACE,
        "completed_since": "now",
        "opt_fields": "name,due_on,completed,projects.name",
        "limit": limit
    }
    return asana_request("GET", endpoint, params) or []

def get_overdue_tasks() -> list:
    """Просроченные задачи"""
    tasks = get_my_tasks(limit=50)
    today = datetime.now(MOSCOW_TZ).date()
    
    overdue = []
    for task in tasks:
        if task.get("due_on") and not task.get("completed"):
            due = datetime.strptime(task["due_on"], "%Y-%m-%d").date()
            if due < today:
                overdue.append(task)
    
    return overdue

def search_tasks(query: str) -> list:
    """Поиск задач по названию"""
    endpoint = f"/workspaces/{ASANA_WORKSPACE}/tasks/search"
    params = {
        "text": query,
        "opt_fields": "name,due_on,completed,gid",
        "limit": 5
    }
    return asana_request("GET", endpoint, params) or []

# ═══════════════════════════════════════════════════════════════
# КОМАНДЫ БОТА
# ═══════════════════════════════════════════════════════════════

HELP_TEXT = """
🤖 **Artvision Task Manager**

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

📋 **ЗАДАЧИ:**
/tasks — мои задачи
/week — план на неделю
/overdue — просроченные
/today — на сегодня

⏱️ **ТРЕКЕР ВРЕМЕНИ:**
/track [задача] — начать трекинг
/stop — остановить
/status — текущий статус
/report — отчёт за сегодня
/weekreport — отчёт за неделю

🎤 **ГОЛОС:**
Отправь голосовое — создам задачу

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /start"""
    user = update.effective_user
    await update.message.reply_text(
        f"👋 Привет, {user.first_name}!\n\n"
        f"Я помогу управлять задачами и трекать время.\n\n"
        f"Напиши /help для списка команд."
    )

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /help"""
    await update.message.reply_text(HELP_TEXT, parse_mode="Markdown")

async def tasks_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /tasks — список задач"""
    await update.message.reply_text("⏳ Загружаю задачи...")
    
    tasks = get_my_tasks()
    if not tasks:
        await update.message.reply_text("📭 Нет активных задач")
        return
    
    text = "📋 **Мои задачи:**\n\n"
    for i, task in enumerate(tasks[:10], 1):
        due = task.get("due_on", "—")
        name = task.get("name", "Без названия")
        text += f"{i}. {name}\n   📅 {due}\n\n"
    
    await update.message.reply_text(text, parse_mode="Markdown")

async def week_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /week — план на неделю"""
    await update.message.reply_text("⏳ Загружаю план...")
    
    tasks = get_my_tasks(limit=30)
    today = datetime.now(MOSCOW_TZ).date()
    week_end = today + timedelta(days=7)
    
    week_tasks = []
    for task in tasks:
        if task.get("due_on"):
            due = datetime.strptime(task["due_on"], "%Y-%m-%d").date()
            if today <= due <= week_end:
                week_tasks.append(task)
    
    if not week_tasks:
        await update.message.reply_text("📭 На эту неделю задач нет")
        return
    
    # Группируем по дням
    by_day = {}
    for task in week_tasks:
        day = task["due_on"]
        if day not in by_day:
            by_day[day] = []
        by_day[day].append(task["name"])
    
    text = "📅 **План на неделю:**\n\n"
    for day in sorted(by_day.keys()):
        dt = datetime.strptime(day, "%Y-%m-%d")
        day_name = dt.strftime("%a %d.%m")
        text += f"**{day_name}**\n"
        for task_name in by_day[day]:
            text += f"  • {task_name}\n"
        text += "\n"
    
    await update.message.reply_text(text, parse_mode="Markdown")

async def overdue_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /overdue — просроченные"""
    await update.message.reply_text("⏳ Проверяю...")
    
    tasks = get_overdue_tasks()
    if not tasks:
        await update.message.reply_text("✅ Просроченных задач нет!")
        return
    
    text = "🔴 **Просроченные задачи:**\n\n"
    for task in tasks:
        name = task.get("name", "—")
        due = task.get("due_on", "—")
        text += f"• {name}\n  📅 {due}\n\n"
    
    await update.message.reply_text(text, parse_mode="Markdown")

async def today_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /today — задачи на сегодня"""
    tasks = get_my_tasks(limit=30)
    today = datetime.now(MOSCOW_TZ).strftime("%Y-%m-%d")
    
    today_tasks = [t for t in tasks if t.get("due_on") == today]
    
    if not today_tasks:
        await update.message.reply_text("📭 На сегодня задач нет")
        return
    
    text = "📋 **На сегодня:**\n\n"
    for task in today_tasks:
        text += f"• {task['name']}\n"
    
    await update.message.reply_text(text, parse_mode="Markdown")

# ═══════════════════════════════════════════════════════════════
# ТРЕКЕР ВРЕМЕНИ
# ═══════════════════════════════════════════════════════════════

async def track_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /track [задача] — начать трекинг"""
    user = update.effective_user
    
    # Проверяем, нет ли активной сессии
    active = get_active_session(user.id)
    if active:
        started = active["started_at"]
        if started.tzinfo is None:
            started = started.replace(tzinfo=MOSCOW_TZ)
        elapsed = int((datetime.now(MOSCOW_TZ) - started).total_seconds() / 60)
        await update.message.reply_text(
            f"⚠️ У тебя уже есть активная сессия:\n\n"
            f"📌 **{active['task_name']}**\n"
            f"⏱️ {elapsed} мин\n\n"
            f"Используй /stop чтобы остановить",
            parse_mode="Markdown"
        )
        return
    
    # Получаем название задачи
    task_name = " ".join(context.args) if context.args else None
    
    if not task_name:
        # Показываем кнопки с задачами из Asana
        tasks = get_my_tasks(limit=5)
        if tasks:
            keyboard = []
            for task in tasks:
                keyboard.append([InlineKeyboardButton(
                    task["name"][:40],
                    callback_data=f"track:{task['gid']}:{task['name'][:30]}"
                )])
            keyboard.append([InlineKeyboardButton("✏️ Своё название", callback_data="track:custom")])
            
            await update.message.reply_text(
                "🎯 Выбери задачу или напиши своё название:",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
        else:
            await update.message.reply_text(
                "📝 Напиши название задачи:\n"
                "`/track Название задачи`",
                parse_mode="Markdown"
            )
        return
    
    # Начинаем сессию
    session_id = start_session(user.id, user.username, task_name)
    
    await update.message.reply_text(
        f"▶️ **Трекинг начат!**\n\n"
        f"📌 {task_name}\n"
        f"🕐 {datetime.now(MOSCOW_TZ).strftime('%H:%M')}\n\n"
        f"Используй /stop когда закончишь",
        parse_mode="Markdown"
    )

async def track_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка выбора задачи для трекинга"""
    query = update.callback_query
    await query.answer()
    
    user = update.effective_user
    data = query.data
    
    if data == "track:custom":
        await query.edit_message_text(
            "✏️ Напиши:\n`/track Название задачи`",
            parse_mode="Markdown"
        )
        return
    
    parts = data.split(":", 2)
    if len(parts) >= 3:
        asana_id = parts[1]
        task_name = parts[2]
        
        session_id = start_session(user.id, user.username, task_name, asana_id)
        
        await query.edit_message_text(
            f"▶️ **Трекинг начат!**\n\n"
            f"📌 {task_name}\n"
            f"🕐 {datetime.now(MOSCOW_TZ).strftime('%H:%M')}\n\n"
            f"Используй /stop когда закончишь",
            parse_mode="Markdown"
        )

async def stop_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /stop — остановить трекинг"""
    user = update.effective_user
    notes = " ".join(context.args) if context.args else None
    
    result = stop_session(user.id, notes)
    
    if not result:
        await update.message.reply_text("❌ Нет активной сессии")
        return
    
    hours = result["duration_minutes"] // 60
    mins = result["duration_minutes"] % 60
    duration_str = f"{hours}ч {mins}мин" if hours else f"{mins} мин"
    
    await update.message.reply_text(
        f"⏹️ **Трекинг остановлен!**\n\n"
        f"📌 {result['task_name']}\n"
        f"⏱️ {duration_str}\n"
        f"🕐 {result['started_at'].strftime('%H:%M')} → {result['ended_at'].strftime('%H:%M')}",
        parse_mode="Markdown"
    )

async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /status — текущий статус"""
    user = update.effective_user
    
    active = get_active_session(user.id)
    if not active:
        await update.message.reply_text(
            "💤 Нет активного трекинга\n\n"
            "Начни с /track [задача]"
        )
        return
    
    started = active["started_at"]
    if started.tzinfo is None:
        started = started.replace(tzinfo=MOSCOW_TZ)
    
    elapsed = int((datetime.now(MOSCOW_TZ) - started).total_seconds() / 60)
    hours = elapsed // 60
    mins = elapsed % 60
    elapsed_str = f"{hours}ч {mins}мин" if hours else f"{mins} мин"
    
    await update.message.reply_text(
        f"🟢 **Активный трекинг**\n\n"
        f"📌 {active['task_name']}\n"
        f"⏱️ {elapsed_str}\n"
        f"🕐 Начат в {started.strftime('%H:%M')}",
        parse_mode="Markdown"
    )

async def report_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /report — отчёт за сегодня"""
    user = update.effective_user
    stats = get_today_stats(user.id)
    
    if stats["total_minutes"] == 0:
        await update.message.reply_text("📊 Сегодня ещё нет записей")
        return
    
    hours = stats["total_minutes"] // 60
    mins = stats["total_minutes"] % 60
    total_str = f"{hours}ч {mins}мин" if hours else f"{mins} мин"
    
    text = f"📊 **Отчёт за сегодня**\n\n"
    text += f"⏱️ Всего: **{total_str}**\n"
    text += f"📝 Сессий: {stats['sessions_count']}\n\n"
    
    if stats["tasks"]:
        text += "**По задачам:**\n"
        for task_name, minutes in stats["tasks"]:
            h = minutes // 60
            m = minutes % 60
            t_str = f"{h}ч {m}мин" if h else f"{m} мин"
            text += f"• {task_name}: {t_str}\n"
    
    await update.message.reply_text(text, parse_mode="Markdown")

async def weekreport_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /weekreport — отчёт за неделю"""
    user = update.effective_user
    stats = get_week_stats(user.id)
    
    if stats["total_minutes"] == 0:
        await update.message.reply_text("📊 За неделю нет записей")
        return
    
    hours = stats["total_minutes"] // 60
    mins = stats["total_minutes"] % 60
    total_str = f"{hours}ч {mins}мин" if hours else f"{mins} мин"
    
    text = f"📊 **Отчёт за неделю**\n\n"
    text += f"⏱️ Всего: **{total_str}**\n\n"
    
    if stats["days"]:
        text += "**По дням:**\n"
        for day, minutes in stats["days"]:
            dt = datetime.strptime(day, "%Y-%m-%d")
            day_name = dt.strftime("%a %d.%m")
            h = minutes // 60
            m = minutes % 60
            t_str = f"{h}ч {m}мин" if h else f"{m} мин"
            text += f"• {day_name}: {t_str}\n"
    
    await update.message.reply_text(text, parse_mode="Markdown")

# ═══════════════════════════════════════════════════════════════
# ГОЛОСОВЫЕ СООБЩЕНИЯ
# ═══════════════════════════════════════════════════════════════

async def handle_voice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка голосовых сообщений"""
    if not OPENAI_API_KEY:
        await update.message.reply_text("⚠️ OpenAI API не настроен")
        return
    
    await update.message.reply_text("🎤 Распознаю...")
    
    try:
        # Скачиваем голосовое
        voice = update.message.voice
        file = await context.bot.get_file(voice.file_id)
        
        # Временный файл
        voice_path = f"/tmp/voice_{update.message.message_id}.ogg"
        await file.download_to_drive(voice_path)
        
        # Распознаём через Whisper
        client = openai.OpenAI(api_key=OPENAI_API_KEY)
        with open(voice_path, "rb") as audio_file:
            transcript = client.audio.transcriptions.create(
                model="whisper-1",
                file=audio_file,
                language="ru"
            )
        
        text = transcript.text
        os.remove(voice_path)
        
        await update.message.reply_text(
            f"📝 Распознано:\n\n_{text}_\n\n"
            f"Создать задачу?",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("✅ Создать", callback_data=f"voice_task:{text[:100]}")],
                [InlineKeyboardButton("❌ Отмена", callback_data="voice_cancel")]
            ])
        )
        
    except Exception as e:
        logger.error(f"Voice error: {e}")
        await update.message.reply_text(f"❌ Ошибка: {e}")

async def voice_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка создания задачи из голоса"""
    query = update.callback_query
    await query.answer()
    
    if query.data == "voice_cancel":
        await query.edit_message_text("❌ Отменено")
        return
    
    task_name = query.data.replace("voice_task:", "")
    
    # Создаём задачу в Asana
    result = asana_request("POST", "/tasks", {
        "name": task_name,
        "projects": [ASANA_PROJECT],
        "workspace": ASANA_WORKSPACE
    })
    
    if result:
        await query.edit_message_text(f"✅ Задача создана:\n\n**{task_name}**", parse_mode="Markdown")
    else:
        await query.edit_message_text(f"❌ Ошибка создания задачи")

# ═══════════════════════════════════════════════════════════════
# ЕЖЕДНЕВНЫЕ УВЕДОМЛЕНИЯ
# ═══════════════════════════════════════════════════════════════

async def daily_notification(context: ContextTypes.DEFAULT_TYPE):
    """Ежедневное уведомление с планом"""
    for admin_id in ADMIN_IDS:
        try:
            tasks = get_my_tasks(limit=10)
            today = datetime.now(MOSCOW_TZ).strftime("%Y-%m-%d")
            today_tasks = [t for t in tasks if t.get("due_on") == today]
            overdue = get_overdue_tasks()
            
            text = f"☀️ **Доброе утро!**\n\n"
            text += f"📅 {datetime.now(MOSCOW_TZ).strftime('%d.%m.%Y, %A')}\n\n"
            
            if overdue:
                text += f"🔴 **Просрочено:** {len(overdue)}\n"
            
            if today_tasks:
                text += f"\n📋 **На сегодня ({len(today_tasks)}):**\n"
                for t in today_tasks[:5]:
                    text += f"• {t['name']}\n"
            else:
                text += "\n✨ На сегодня задач нет\n"
            
            text += "\nХорошего дня! 🚀"
            
            await context.bot.send_message(admin_id, text, parse_mode="Markdown")
        except Exception as e:
            logger.error(f"Daily notification error: {e}")

# ═══════════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════════

def main():
    """Запуск бота"""
    if not BOT_TOKEN:
        logger.error("TELEGRAM_BOT_TOKEN не задан!")
        return
    
    # Инициализация БД
    init_db()
    
    app = Application.builder().token(BOT_TOKEN).build()
    
    # Команды
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("tasks", tasks_command))
    app.add_handler(CommandHandler("week", week_command))
    app.add_handler(CommandHandler("overdue", overdue_command))
    app.add_handler(CommandHandler("today", today_command))
    
    # Трекер времени
    app.add_handler(CommandHandler("track", track_command))
    app.add_handler(CommandHandler("stop", stop_command))
    app.add_handler(CommandHandler("status", status_command))
    app.add_handler(CommandHandler("report", report_command))
    app.add_handler(CommandHandler("weekreport", weekreport_command))
    
    # Callbacks
    app.add_handler(CallbackQueryHandler(track_callback, pattern="^track:"))
    app.add_handler(CallbackQueryHandler(voice_callback, pattern="^voice_"))
    
    # Голосовые
    app.add_handler(MessageHandler(filters.VOICE, handle_voice))
    
    # Планировщик
    job_queue = app.job_queue
    job_queue.run_daily(
        daily_notification,
        time=datetime.strptime("10:30", "%H:%M").time(),
        days=(0, 1, 2, 3, 4),
        name="daily_plan"
    )
    
    logger.info("🤖 Бот запущен!")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
