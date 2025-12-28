"""Artvision Bot v3 - minimal debug"""

from http.server import BaseHTTPRequestHandler
import json
import os

TG_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
ADMIN_IDS = os.environ.get("ADMIN_IDS", "161261562").split(",")

def send_tg(chat_id, text):
    import urllib.request
    url = f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage"
    data = json.dumps({"chat_id": chat_id, "text": text}).encode()
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
    try:
        resp = urllib.request.urlopen(req, timeout=10)
        return resp.read()
    except Exception as e:
        return str(e)

class handler(BaseHTTPRequestHandler):
    def do_POST(self):
        try:
            length = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(length))
            
            msg = body.get("message", {})
            chat_id = msg.get("chat", {}).get("id")
            user_id = msg.get("from", {}).get("id")
            text = msg.get("text", "")
            
            if chat_id and str(user_id) in ADMIN_IDS and text.startswith("/"):
                cmd = text.split()[0].lower().split("@")[0]
                
                if cmd == "/ping":
                    send_tg(chat_id, "🏓 pong!")
                elif cmd == "/help":
                    send_tg(chat_id, "🤖 Команды: /ping /help /status /sites")
                elif cmd == "/status":
                    send_tg(chat_id, "📊 Status OK")
                elif cmd == "/sites":
                    send_tg(chat_id, "🌐 Sites: работает!")
                else:
                    send_tg(chat_id, f"❓ Неизвестно: {cmd}")
        except Exception as e:
            print(f"Error: {e}")
        
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"ok")
    
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        msg = f"Bot OK | Token: {TG_TOKEN[:15]}... | Admins: {ADMIN_IDS}"
        self.wfile.write(msg.encode())
