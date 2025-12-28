"""
Artvision Telegram Bot — Vercel Serverless
"""

import os
import json
import requests
from datetime import datetime, timedelta

TG_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
GH_TOKEN = os.environ.get("GH_TOKEN", "")
WM_TOKEN = os.environ.get("YANDEX_WEBMASTER_TOKEN", "")
ASANA_TOKEN = os.environ.get("ASANA_TOKEN", "")
ADMIN_IDS = os.environ.get("ADMIN_IDS", "161261562").split(",")

WM_USER_ID = "126256095"
GH_REPO = "justtrance-web/semantic-pipeline"
ASANA_PROJECT = "1212305892582815"

def send_message(chat_id, text, parse_mode="HTML"):
    requests.post(
        f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage",
        json={"chat_id": chat_id, "text": text[:4000], "parse_mode": parse_mode}
    )

def get_last_report():
    try:
        import base64
        resp = requests.get(
            "https://api.github.com/repos/justtrance-web/artvision-data/contents/monitoring/position_history.json",
            headers={"Authorization": f"token {GH_TOKEN}"}
        )
        if resp.status_code == 200:
            return json.loads(base64.b64decode(resp.json()["content"]))
    except:
        pass
    return None

def get_webmaster_hosts():
    try:
        resp = requests.get(
            f"https://api.webmaster.yandex.net/v4/user/{WM_USER_ID}/hosts",
            headers={"Authorization": f"OAuth {WM_TOKEN}"}
        )
        if resp.status_code == 200:
            return {h["ascii_host_url"]: h["host_id"] for h in resp.json().get("hosts", []) if h.get("verified")}
    except:
        pass
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
    
    resp = requests.post(
        f"https://api.webmaster.yandex.net/v4/user/{WM_USER_ID}/hosts/{host_id}/query-analytics/list",
        headers={"Authorization": f"OAuth {WM_TOKEN}", "Content-Type": "application/json"},
        json={"offset": 0, "limit": 15, "device_type_indicator": "ALL", "text_indicator": "QUERY", "date_from": date_from, "date_to": date_to}
    )
    
    if resp.status_code != 200:
        return None
    
    results = []
    for q in resp.json().get("text_indicator_to_statistics", []):
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
    resp = requests.post(
        f"https://api.github.com/repos/{GH_REPO}/actions/workflows/{workflow}/dispatches",
        headers={"Authorization": f"token {GH_TOKEN}"},
        json={"ref": "main"}
    )
    return resp.status_code == 204

def handle_command(chat_id, user_id, text):
    if str(user_id) not in ADMIN_IDS:
        send_message(chat_id, "⛔ Нет доступа")
        return
    
    parts = text.strip().split()
    cmd = parts[0].lower().split("@")[0]
    args = parts[1:] if len(parts) > 1 else []
    
    if cmd in ["/start", "/help"]:
        msg = """<b>🤖 Artvision Bot</b>

/status — последняя проверка
/positions [сайт] — позиции
/check — запустить проверку
/sites — список сайтов

Пример: <code>/positions ant.partners</code>"""
        send_message(chat_id, msg)
        return
    
    if cmd == "/status":
        report = get_last_report()
        if not report:
            send_message(chat_id, "❌ Нет данных")
            return
        
        date = report.get("date", "?")
        sites = report.get("sites", {})
        msg = [f"<b>📊 {date}</b>\n"]
        for domain, queries in list(sites.items())[:8]:
            top = sorted(queries, key=lambda x: x.get("impressions", 0), reverse=True)[:1]
            if top:
                q = top[0]
                msg.append(f"• <b>{domain}</b>: {len(queries)} зап, топ поз {q['position']:.0f}")
        send_message(chat_id, "\n".join(msg))
        return
    
    if cmd == "/sites":
        hosts = get_webmaster_hosts()
        msg = [f"<b>🌐 Webmaster ({len(hosts)}):</b>\n"]
        for url in sorted(hosts.keys())[:20]:
            domain = url.replace("https://", "").rstrip("/")
            msg.append(f"• {domain}")
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
        msg.append(f"{'Поз':>3} {'Кл':>3} {'Пок':>5}  Запрос")
        for q in positions[:12]:
            msg.append(f"{q['pos']:>3.0f} {q['clicks']:>3} {q['shows']:>5}  {q['query'][:22]}")
        msg.append("</pre>")
        send_message(chat_id, "\n".join(msg))
        return
    
    if cmd == "/check":
        send_message(chat_id, "🚀 Запускаю...")
        ok1 = trigger_workflow("position_monitor.yml")
        ok2 = trigger_workflow("weekly_check.yml")
        msg = f"{'✅' if ok1 else '❌'} Positions\n{'✅' if ok2 else '❌'} Weekly\n\n⏳ ~2 мин"
        send_message(chat_id, msg)
        return
    
    send_message(chat_id, "❓ /help")

def handler(request):
    """Vercel handler"""
    if request.method == "POST":
        try:
            body = request.get_json()
            msg = body.get("message", {})
            chat_id = msg.get("chat", {}).get("id")
            user_id = msg.get("from", {}).get("id")
            text = msg.get("text", "")
            
            if text.startswith("/"):
                handle_command(chat_id, user_id, text)
        except Exception as e:
            print(f"Error: {e}")
    
    return "ok"
