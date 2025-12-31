"""Artvision Bot v5 - Smart Trigger Mode

Режимы реакции:
1. Команды (/help, /status...) — стандартно
2. "Бот, ..." — прямое обращение, отвечает всегда
3. Обычное общение — молча следит, но может предложить помощь

Триггеры для обращения:
- "бот" / "бот," / "бот!" в начале сообщения
- @avportalbot упоминание
- Ответ на сообщение бота (reply)
"""

from http.server import BaseHTTPRequestHandler
import json
import os
import urllib.request
import base64
import re
from datetime import datetime, timedelta

# === КОНФИГ ===
TG_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
GH_TOKEN = os.environ.get("GH_TOKEN", "")
WM_TOKEN = os.environ.get("YANDEX_WEBMASTER_TOKEN", "")
ASANA_TOKEN = os.environ.get("ASANA_TOKEN", "")
ADMIN_IDS = os.environ.get("ADMIN_IDS", "161261562").split(",")
TEAM_IDS = os.environ.get("TEAM_IDS", "161261562").split(",")  # ID сотрудников
WM_USER_ID = "126256095"
BOT_USERNAME = "avportalbot"

# Паттерны для распознавания задач в чате
TASK_PATTERNS = [
    r"(надо|нужно|необходимо)\s+(.+)",
    r"(сделать|сделай)\s+(.+)",
    r"(давай|давайте)\s+(.+)",
    r"(план[ируем|ирую]?)\s+(.+)",
    r"(добавь|добавить)\s+(.+)",
]


def log(msg):
    """Логирование"""
    print(f"[BOT v5] {datetime.now().strftime('%H:%M:%S')} {msg}")


def http_request(url, data=None, headers=None):
    """HTTP запрос"""
    headers = headers or {}
    if data:
        data = json.dumps(data).encode()
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read().decode())
    except Exception as e:
        log(f"HTTP error: {e}")
        return None


def send_tg(chat_id, text, reply_to=None, buttons=None):
    """Отправить сообщение в Telegram"""
    url = f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": text[:4000],
        "parse_mode": "HTML"
    }
    if reply_to:
        payload["reply_to_message_id"] = reply_to
    if buttons:
        payload["reply_markup"] = {"inline_keyboard": buttons}
    return http_request(url, payload)


# === ОПРЕДЕЛЕНИЕ ТИПА СООБЩЕНИЯ ===

def is_bot_trigger(text, message):
    """
    Проверяет, обращаются ли к боту
    
    Триггеры:
    - "бот" / "бот," / "бот!" в начале (регистронезависимо)
    - @avportalbot в любом месте
    - Reply на сообщение бота
    """
    text_lower = text.lower().strip()
    
    # Паттерн: начинается с "бот" + пробел/знак препинания
    if re.match(r'^бот[\s,!?.:\-]', text_lower):
        return True
    if text_lower == "бот":
        return True
    
    # Упоминание @username
    if f"@{BOT_USERNAME}" in text_lower:
        return True
    
    # Reply на сообщение бота
    reply_to = message.get("reply_to_message", {})
    if reply_to.get("from", {}).get("username") == BOT_USERNAME:
        return True
    
    return False


def extract_bot_query(text):
    """
    Извлекает текст запроса, убирая триггер
    
    "Бот, создай задачу" → "создай задачу"
    "@avportalbot помоги" → "помоги"
    """
    # Убираем "бот" в начале
    text = re.sub(r'^бот[\s,!?.:\-]*', '', text, flags=re.IGNORECASE).strip()
    # Убираем @username
    text = re.sub(rf'@{BOT_USERNAME}\s*', '', text, flags=re.IGNORECASE).strip()
    return text


def detect_task_intent(text):
    """
    Проверяет, есть ли в сообщении намерение на задачу
    Возвращает (True, описание) или (False, None)
    """
    text_lower = text.lower()
    for pattern in TASK_PATTERNS:
        match = re.search(pattern, text_lower, re.IGNORECASE)
        if match:
            # Извлекаем описание задачи
            task_desc = match.group(2).strip()
            # Убираем лишнее
            task_desc = re.sub(r'[\.\!\?]+$', '', task_desc)
            if len(task_desc) > 5:  # Минимум 5 символов
                return True, task_desc
    return False, None


# === ОБРАБОТЧИКИ ===

def handle_bot_command(chat_id, user_id, text, message):
    """Обработка прямых команд боту"""
    query = extract_bot_query(text)
    query_lower = query.lower()
    
    log(f"Bot query: '{query}'")
    
    # Простые ответы
    if query_lower in ["привет", "здравствуй", "ты тут?", "ты здесь?", "ты здесь", "ты тут"]:
        send_tg(chat_id, "👋 Да, слежу за чатом! Чем помочь?", reply_to=message.get("message_id"))
        return
    
    if query_lower in ["помоги", "помощь", "что умеешь", "help"]:
        send_tg(chat_id, """🤖 <b>Чем могу помочь:</b>

• <b>Бот, создай задачу</b> [описание] — добавлю в Asana
• <b>Бот, статус</b> — позиции сайтов
• <b>Бот, позиции</b> [сайт] — детальные позиции

Также слежу за общением и предложу создать задачу, если замечу планы.""",
                reply_to=message.get("message_id"))
        return
    
    # Создание задачи
    if query_lower.startswith(("создай задачу", "добавь задачу", "новая задача")):
        task_name = re.sub(r'^(создай|добавь|новая)\s*задач[у|а][\s:]*', '', query, flags=re.IGNORECASE).strip()
        if task_name:
            # TODO: интеграция с Asana
            send_tg(chat_id, f"✅ Задача создана:\n<b>{task_name}</b>\n\n<i>(интеграция с Asana в разработке)</i>",
                    reply_to=message.get("message_id"))
        else:
            send_tg(chat_id, "❓ Укажи название задачи:\n<code>Бот, создай задачу Проверить мета-теги</code>",
                    reply_to=message.get("message_id"))
        return
    
    # Статус
    if query_lower in ["статус", "status"]:
        handle_status(chat_id)
        return
    
    # Позиции
    if query_lower.startswith("позиции"):
        args = query.split()[1:] if len(query.split()) > 1 else []
        handle_positions(chat_id, args)
        return
    
    # Не понял
    send_tg(chat_id, f"🤔 Не совсем понял. Попробуй:\n• <code>Бот, помоги</code>\n• <code>Бот, создай задачу [описание]</code>",
            reply_to=message.get("message_id"))


def handle_passive_monitoring(chat_id, user_id, text, message):
    """
    Пассивный мониторинг чата
    Предлагает помощь если видит паттерн задачи
    """
    # Только для команды (сотрудников)
    if str(user_id) not in TEAM_IDS:
        return
    
    # Проверяем на паттерн задачи
    is_task, task_desc = detect_task_intent(text)
    
    if is_task and task_desc:
        log(f"Detected task intent: {task_desc}")
        
        # Предлагаем создать задачу
        buttons = [[
            {"text": "✅ Да, создай", "callback_data": f"create_task:{task_desc[:50]}"},
            {"text": "❌ Не надо", "callback_data": "dismiss"}
        ]]
        
        send_tg(
            chat_id,
            f"💡 Заметил план действий:\n<i>\"{task_desc[:100]}...\"</i>\n\nСоздать задачу в Asana?",
            reply_to=message.get("message_id"),
            buttons=buttons
        )


# === СТАНДАРТНЫЕ КОМАНДЫ ===

def get_report():
    url = "https://api.github.com/repos/justtrance-web/artvision-data/contents/monitoring/position_history.json"
    data = http_request(url, headers={"Authorization": f"token {GH_TOKEN}"})
    if data and "content" in data:
        return json.loads(base64.b64decode(data["content"]))
    return None


def get_hosts():
    url = f"https://api.webmaster.yandex.net/v4/user/{WM_USER_ID}/hosts"
    data = http_request(url, headers={"Authorization": f"OAuth {WM_TOKEN}"})
    if data:
        return {h["ascii_host_url"]: h["host_id"] for h in data.get("hosts", []) if h.get("verified")}
    return {}


def get_positions(domain):
    hosts = get_hosts()
    host_id = None
    for url, hid in hosts.items():
        if domain in url:
            host_id = hid
            break
    if not host_id:
        return None
    
    today = datetime.now()
    date_to = (today - timedelta(days=1)).strftime("%Y-%m-%d")
    date_from = (today - timedelta(days=7)).strftime("%Y-%m-%d")
    
    url = f"https://api.webmaster.yandex.net/v4/user/{WM_USER_ID}/hosts/{host_id}/query-analytics/list"
    data = http_request(url, {
        "offset": 0, "limit": 12, "device_type_indicator": "ALL",
        "text_indicator": "QUERY", "date_from": date_from, "date_to": date_to
    }, {"Authorization": f"OAuth {WM_TOKEN}"})
    
    if not data:
        return None
    
    results = []
    for q in data.get("text_indicator_to_statistics", []):
        query = q.get("text_indicator", {}).get("value", "")
        stats = q.get("statistics", [])
        clicks = sum(s["value"] for s in stats if s["field"] == "CLICKS")
        shows = sum(s["value"] for s in stats if s["field"] == "IMPRESSIONS")
        positions = [s["value"] for s in stats if s["field"] == "POSITION" and s["value"] > 0]
        avg_pos = sum(positions) / len(positions) if positions else 0
        if shows > 0:
            results.append({"q": query, "p": avg_pos, "c": int(clicks), "s": int(shows)})
    return sorted(results, key=lambda x: x["s"], reverse=True)


def handle_status(chat_id):
    report = get_report()
    if not report:
        send_tg(chat_id, "❌ Нет данных")
        return
    msg = [f"<b>📊 {report.get('date', '?')}</b>\n"]
    for domain, queries in list(report.get("sites", {}).items())[:7]:
        top = sorted(queries, key=lambda x: x.get("impressions", 0), reverse=True)[:1]
        if top:
            msg.append(f"• <b>{domain}</b>: {len(queries)} зап, топ поз {top[0].get('position', 0):.0f}")
    send_tg(chat_id, "\n".join(msg))


def handle_positions(chat_id, args):
    if not args:
        send_tg(chat_id, "❓ Укажи сайт:\n<code>/positions ant.partners</code>")
        return
    domain = args[0].replace("https://", "").rstrip("/")
    positions = get_positions(domain)
    if not positions:
        send_tg(chat_id, f"❌ {domain} не найден")
        return
    msg = [f"<b>📈 {domain}</b>\n<pre>"]
    msg.append(f"{'Поз':>3} {'Кл':>3} {'Пок':>5}  Запрос")
    for q in positions[:10]:
        msg.append(f"{q['p']:>3.0f} {q['c']:>3} {q['s']:>5}  {q['q'][:20]}")
    msg.append("</pre>")
    send_tg(chat_id, "\n".join(msg))


def handle_slash_command(chat_id, user_id, text, msg=None):
    """Обработка стандартных /команд"""
    if str(user_id) not in ADMIN_IDS:
        send_tg(chat_id, "⛔ Нет доступа")
        return
    
    parts = text.strip().split()
    cmd = parts[0].lower().split("@")[0]
    args = parts[1:] if len(parts) > 1 else []
    
    if cmd == "/ping":
        send_tg(chat_id, "🏓 pong!")
    
    elif cmd == "/myid":
        # Команда для всех — узнать свой Telegram ID
        user_name = msg.get("from", {}).get("first_name", "User")
        send_tg(chat_id, f"👤 {user_name}, твой Telegram ID: <code>{user_id}</code>

Скопируй и отправь Кириллу для настройки бота.")
        return
    
    elif cmd in ["/start", "/help"]:
        send_tg(chat_id, """<b>🤖 Artvision Bot v5</b>

<b>Команды:</b>
/status — данные позиций
/positions [сайт] — детальные позиции
/sites — список сайтов
/ping — тест

<b>Обращение:</b>
• <code>Бот, помоги</code>
• <code>Бот, создай задачу [описание]</code>
• <code>@avportalbot статус</code>

Также слежу за чатом и предложу создать задачу, если замечу планы 💡""")
    
    elif cmd == "/status":
        handle_status(chat_id)
    
    elif cmd == "/sites":
        hosts = get_hosts()
        msg = [f"<b>🌐 Webmaster ({len(hosts)}):</b>\n"]
        for url in sorted(hosts.keys())[:15]:
            msg.append(f"• {url.replace('https://','').rstrip('/')}")
        send_tg(chat_id, "\n".join(msg))
    
    elif cmd == "/positions":
        handle_positions(chat_id, args)
    
    else:
        send_tg(chat_id, "❓ Неизвестная команда. /help")


def handle_callback(callback):
    """Обработка inline-кнопок"""
    callback_id = callback.get("id")
    data = callback.get("data", "")
    message = callback.get("message", {})
    chat_id = message.get("chat", {}).get("id")
    message_id = message.get("message_id")
    
    # Подтверждаем callback
    http_request(f"https://api.telegram.org/bot{TG_TOKEN}/answerCallbackQuery",
                 {"callback_query_id": callback_id})
    
    if data.startswith("create_task:"):
        task_desc = data.replace("create_task:", "")
        # TODO: реальное создание в Asana
        # Редактируем сообщение
        http_request(f"https://api.telegram.org/bot{TG_TOKEN}/editMessageText", {
            "chat_id": chat_id,
            "message_id": message_id,
            "text": f"✅ Задача создана:\n<b>{task_desc}</b>\n\n<i>(интеграция с Asana в разработке)</i>",
            "parse_mode": "HTML"
        })
    
    elif data == "dismiss":
        http_request(f"https://api.telegram.org/bot{TG_TOKEN}/deleteMessage", {
            "chat_id": chat_id,
            "message_id": message_id
        })


# === MAIN HANDLER ===

class handler(BaseHTTPRequestHandler):
    def do_POST(self):
        try:
            length = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(length))
            
            # Callback query (inline кнопки)
            if "callback_query" in body:
                handle_callback(body["callback_query"])
            
            # Обычное сообщение
            elif "message" in body:
                msg = body["message"]
                chat_id = msg.get("chat", {}).get("id")
                user_id = msg.get("from", {}).get("id")
                text = msg.get("text", "")
                
                if not chat_id or not text:
                    pass
                
                # 1. Слэш-команды
                elif text.startswith("/"):
                    handle_slash_command(chat_id, user_id, text, msg)
                
                # 2. Прямое обращение к боту ("Бот, ...", @mention, reply)
                elif is_bot_trigger(text, msg):
                    if str(user_id) in TEAM_IDS:
                        handle_bot_command(chat_id, user_id, text, msg)
                    else:
                        log(f"Non-team user {user_id} tried to use bot")
                
                # 3. Пассивный мониторинг (без ответа, но может предложить)
                else:
                    handle_passive_monitoring(chat_id, user_id, text, msg)
        
        except Exception as e:
            log(f"Error: {e}")
            import traceback
            traceback.print_exc()
        
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"ok")
    
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"Artvision Bot v5 - Smart Mode")


