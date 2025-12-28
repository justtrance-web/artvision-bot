"""
Artvision Telegram Bot — Vercel Serverless
"""

from http.server import BaseHTTPRequestHandler
import os
import json
import urllib.request
import urllib.parse
from datetime import datetime, timedelta

TG_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
GH_TOKEN = os.environ.get("GH_TOKEN", "")
WM_TOKEN = os.environ.get("YANDEX_WEBMASTER_TOKEN", "")
ADMIN_IDS = os.environ.get("ADMIN_IDS", "161261562").split(",")
WM_USER_ID = "126256095"

def http_get(url, headers=None):
    req = urllib.request.Request(url, headers=headers or {})
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read().decode())
    except:
        return None

def http_post(url, data, headers=None):
    headers = headers or {}
    if isinstance(data, dict):
        data = json.dumps(data).encode()
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read().decode())
    except Exception as e:
        print(f"HTTP POST error: {e}")
        return None

def send_message(chat_id, text):
    url = f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage"
    http_post(url, {"chat_id": chat_id, "text": text[:4000], "parse_mode": "HTML"})

def get_last_report():
    import base64
    url = "https://api.github.com/repos/justtrance-web/artvision-data/contents/monitoring/position_history.json"
    data = http_get(url, {"Authorization": f"token {GH_TOKEN}"})
    if data and "content" in data:
        return json.loads(base64.b64decode(data["content"]))
    return None

def get_webmaster_hosts():
    url = f"https://api.webmaster.yandex.net/v4/user/{WM_USER_ID}/hosts"
    data = http_get(url, {"Authorization": f"OAuth {WM_TOKEN}"})
    if data:
        return {h["ascii_host_url"]: h["host_id"] for h in data.get("hosts", []) if h.get("verified")}
    return {}

def get_positions(domain):
    hosts = get_webmaster_hosts()
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
    data = http_post(url, {
        "offset": 0, "limit": 15, "device_type_indicator": "ALL",
        "text_indicator": "QUERY", "date_from": date_from, "date_to": date_to
    }, {"Authorization": f"OAuth {WM_TOKEN}", "Content-Type": "application/json"})
    
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
            results.append({"query": query, "pos": avg_pos, "clicks": int(clicks), "shows": int(shows)})
    return sorted(results, key=lambda x: x["shows"], reverse=True)

def trigger_workflow(workflow):
    url = f"https://api.github.com/repos/justtrance-web/semantic-pipeline/actions/workflows/{workflow}/dispatches"
    return http_post(url, {"ref": "main"}, {"Authorization": f"token {GH_TOKEN}"}) is not None

def handle_command(chat_id, user_id, text):
    if str(user_id) not in ADMIN_IDS:
        send_message(chat_id, "⛔ Нет доступа")
        return
    
    parts = text.strip().split()
    cmd = parts[0].lower().split("@")[0]
    args = parts[1:] if len(parts) > 1 else []
    
    if cmd in ["/start", "/help"]:
        send_message(chat_id, "<b>🤖 Artvision Bot</b>\n\n/status — данные\n/positions [сайт] — позиции\n/check — запуск\n/sites — сайты")
        return
    
    if cmd == "/status":
        report = get_last_report()
        if not report:
            send_message(chat_id, "❌ Нет данных")
            return
        msg = [f"<b>📊 {report.get('date', '?')}</b>\n"]
        for domain, queries in list(report.get("sites", {}).items())[:7]:
            top = sorted(queries, key=lambda x: x.get("impressions", 0), reverse=True)[:1]
            if top:
                msg.append(f"• <b>{domain}</b>: {len(queries)} зап")
        send_message(chat_id, "\n".join(msg))
        return
    
    if cmd == "/sites":
        hosts = get_webmaster_hosts()
        msg = [f"<b>🌐 Webmaster ({len(hosts)}):</b>\n"]
        for url in sorted(hosts.keys())[:15]:
            msg.append(f"• {url.replace('https://','').rstrip('/')}")
        send_message(chat_id, "\n".join(msg))
        return
    
    if cmd == "/positions":
        if not args:
            send_message(chat_id, "❓ /positions ant.partners")
            return
        domain = args[0].replace("https://", "").rstrip("/")
        positions = get_positions(domain)
        if not positions:
            send_message(chat_id, f"❌ {domain} не найден")
            return
        msg = [f"<b>📈 {domain}</b>\n<pre>"]
        for q in positions[:10]:
            msg.append(f"{q['pos']:>3.0f} {q['clicks']:>3} {q['shows']:>5} {q['query'][:20]}")
        msg.append("</pre>")
        send_message(chat_id, "\n".join(msg))
        return
    
    if cmd == "/check":
        send_message(chat_id, "🚀 Запускаю...")
        trigger_workflow("position_monitor.yml")
        trigger_workflow("weekly_check.yml")
        send_message(chat_id, "✅ Запущено, ~2 мин")
        return
    
    send_message(chat_id, "❓ /help")

class handler(BaseHTTPRequestHandler):
    def do_POST(self):
        try:
            content_length = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(content_length).decode())
            
            msg = body.get("message", {})
            chat_id = msg.get("chat", {}).get("id")
            user_id = msg.get("from", {}).get("id")
            text = msg.get("text", "")
            
            if text.startswith("/"):
                handle_command(chat_id, user_id, text)
        except Exception as e:
            print(f"Error: {e}")
        
        self.send_response(200)
        self.send_header("Content-Type", "text/plain")
        self.end_headers()
        self.wfile.write(b"ok")
    
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/plain")
        self.end_headers()
        self.wfile.write(b"Artvision Bot OK")
