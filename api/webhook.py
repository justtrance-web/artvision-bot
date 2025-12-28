"""Artvision Bot v4 - Full version"""

from http.server import BaseHTTPRequestHandler
import json
import os
import urllib.request
import base64
from datetime import datetime, timedelta

TG_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
GH_TOKEN = os.environ.get("GH_TOKEN", "")
WM_TOKEN = os.environ.get("YANDEX_WEBMASTER_TOKEN", "")
ADMIN_IDS = os.environ.get("ADMIN_IDS", "161261562").split(",")
WM_USER_ID = "126256095"

def http_request(url, data=None, headers=None):
    headers = headers or {}
    if data:
        data = json.dumps(data).encode()
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read().decode())
    except:
        return None

def send_tg(chat_id, text):
    url = f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage"
    http_request(url, {"chat_id": chat_id, "text": text[:4000], "parse_mode": "HTML"})

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

def trigger_workflow(name):
    url = f"https://api.github.com/repos/justtrance-web/semantic-pipeline/actions/workflows/{name}/dispatches"
    return http_request(url, {"ref": "main"}, {"Authorization": f"token {GH_TOKEN}"}) is not None

def handle(chat_id, user_id, text):
    if str(user_id) not in ADMIN_IDS:
        send_tg(chat_id, "⛔ Нет доступа")
        return
    
    parts = text.strip().split()
    cmd = parts[0].lower().split("@")[0]
    args = parts[1:] if len(parts) > 1 else []
    
    if cmd == "/ping":
        send_tg(chat_id, "🏓 pong!")
    
    elif cmd in ["/start", "/help"]:
        send_tg(chat_id, "<b>🤖 Artvision Bot</b>\n\n/status — данные позиций\n/positions [сайт] — позиции\n/sites — список сайтов\n/check — запуск проверок\n/ping — тест")
    
    elif cmd == "/status":
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
    
    elif cmd == "/sites":
        hosts = get_hosts()
        msg = [f"<b>🌐 Webmaster ({len(hosts)}):</b>\n"]
        for url in sorted(hosts.keys())[:15]:
            msg.append(f"• {url.replace('https://','').rstrip('/')}")
        send_tg(chat_id, "\n".join(msg))
    
    elif cmd == "/positions":
        if not args:
            send_tg(chat_id, "❓ Укажи сайт:\n/positions ant.partners")
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
    
    elif cmd == "/check":
        send_tg(chat_id, "🚀 Запускаю проверки...")
        ok1 = trigger_workflow("position_monitor.yml")
        ok2 = trigger_workflow("weekly_check.yml")
        send_tg(chat_id, f"{'✅' if ok1 else '❌'} Positions\n{'✅' if ok2 else '❌'} Weekly\n\n⏳ Результат ~2 мин")
    
    else:
        send_tg(chat_id, "❓ Неизвестная команда. /help")

class handler(BaseHTTPRequestHandler):
    def do_POST(self):
        try:
            length = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(length))
            msg = body.get("message", {})
            chat_id = msg.get("chat", {}).get("id")
            user_id = msg.get("from", {}).get("id")
            text = msg.get("text", "")
            if chat_id and text.startswith("/"):
                handle(chat_id, user_id, text)
        except Exception as e:
            print(f"Error: {e}")
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"ok")
    
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"Artvision Bot OK")
