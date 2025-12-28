"""
Artvision Telegram Bot v2 — Vercel Serverless
"""

from http.server import BaseHTTPRequestHandler
import os
import json
import urllib.request
import urllib.parse
from datetime import datetime, timedelta
import base64
import traceback

TG_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
GH_TOKEN = os.environ.get("GH_TOKEN", "")
WM_TOKEN = os.environ.get("YANDEX_WEBMASTER_TOKEN", "")
ADMIN_IDS = os.environ.get("ADMIN_IDS", "161261562").split(",")
WM_USER_ID = "126256095"

def log(msg):
    print(f"[BOT] {msg}")

def http_get(url, headers=None):
    req = urllib.request.Request(url, headers=headers or {})
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read().decode())
    except Exception as e:
        log(f"GET error: {e}")
        return None

def http_post(url, data, headers=None):
    headers = headers or {}
    if isinstance(data, dict):
        data = json.dumps(data).encode('utf-8')
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            result = json.loads(resp.read().decode())
            log(f"POST OK: {url[:50]}")
            return result
    except Exception as e:
        log(f"POST error {url[:50]}: {e}")
        return None

def send_message(chat_id, text):
    log(f"Sending to {chat_id}: {text[:50]}...")
    url = f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage"
    result = http_post(url, {"chat_id": chat_id, "text": text[:4000], "parse_mode": "HTML"})
    if result and result.get("ok"):
        log("Message sent OK")
    else:
        log(f"Message failed: {result}")
    return result

def get_last_report():
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

def handle_command(chat_id, user_id, text):
    log(f"Command from {user_id}: {text}")
    
    if str(user_id) not in ADMIN_IDS:
        send_message(chat_id, "⛔ Нет доступа")
        return
    
    parts = text.strip().split()
    cmd = parts[0].lower().split("@")[0]
    
    if cmd in ["/start", "/help"]:
        send_message(chat_id, "<b>🤖 Artvision Bot</b>\n\n/status — данные\n/positions [сайт] — позиции\n/sites — сайты")
        return
    
    if cmd == "/status":
        log("Getting status...")
        report = get_last_report()
        if not report:
            send_message(chat_id, "❌ Нет данных")
            return
        msg = [f"<b>📊 {report.get('date', '?')}</b>\n"]
        for domain, queries in list(report.get("sites", {}).items())[:7]:
            msg.append(f"• <b>{domain}</b>: {len(queries)} зап")
        send_message(chat_id, "\n".join(msg))
        return
    
    if cmd == "/sites":
        log("Getting sites...")
        hosts = get_webmaster_hosts()
        msg = [f"<b>🌐 Webmaster ({len(hosts)}):</b>\n"]
        for url in sorted(hosts.keys())[:15]:
            msg.append(f"• {url.replace('https://','').rstrip('/')}")
        send_message(chat_id, "\n".join(msg))
        return
    
    if cmd == "/test":
        send_message(chat_id, f"✅ Test OK\nToken: {TG_TOKEN[:10]}...\nGH: {GH_TOKEN[:10]}...")
        return
    
    send_message(chat_id, "❓ /help")

class handler(BaseHTTPRequestHandler):
    def do_POST(self):
        log("POST received")
        try:
            content_length = int(self.headers.get("Content-Length", 0))
            body_raw = self.rfile.read(content_length)
            log(f"Body: {body_raw[:200]}")
            
            body = json.loads(body_raw.decode())
            msg = body.get("message", {})
            chat_id = msg.get("chat", {}).get("id")
            user_id = msg.get("from", {}).get("id")
            text = msg.get("text", "")
            
            log(f"Parsed: chat={chat_id}, user={user_id}, text={text}")
            
            if chat_id and text.startswith("/"):
                handle_command(chat_id, user_id, text)
            else:
                log("No command to handle")
        except Exception as e:
            log(f"ERROR: {e}")
            log(traceback.format_exc())
        
        self.send_response(200)
        self.send_header("Content-Type", "text/plain")
        self.end_headers()
        self.wfile.write(b"ok")
    
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/plain")
        self.end_headers()
        self.wfile.write(f"Artvision Bot OK\nToken: {TG_TOKEN[:10]}...".encode())
