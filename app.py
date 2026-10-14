#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
MangaBuff No Mercy Stats Bot — app.py (Render/Gunicorn)
Усиленная версия: диагностика, webhook, set-cookie, bg-threading, логирование, все кейсы.
"""

from __future__ import annotations
import os, sys, traceback, threading, logging, re
from datetime import datetime, timezone
from typing import Any, Optional
from flask import Flask, request, jsonify

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s", stream=sys.stdout)
log = logging.getLogger("app")

# ---------- ENV ----------
BOT_TOKEN = (os.environ.get("BOT_TOKEN") or "").strip()
CHAT_ID = (os.environ.get("CHAT_ID") or "").strip()
RUN_KEY = (os.environ.get("RUN_KEY") or "duck2026").strip()
CLUB_SLUG = (os.environ.get("CLUB_SLUG") or "utinoe-bratstvo").strip()
FULL_COOKIE = (os.environ.get("FULL_COOKIE") or "").strip()
SERVICE_NAME = (os.environ.get("RENDER_SERVICE_NAME") or "stats-bot").strip()

RUNTIME = {"cookie": FULL_COOKIE, "last_run": None, "last_error": None, "runs": 0}

app = Flask(__name__)

# ---------- bot import ----------
BOT = None
BOT_IMPORT_ERROR: Optional[str] = None

try:
    import bot as _bot
    BOT = _bot
    if BOT and RUNTIME["cookie"] and hasattr(BOT, "FULL_COOKIE"):
        BOT.FULL_COOKIE = RUNTIME["cookie"]
    log.info("bot.py loaded OK")
except Exception:
    BOT_IMPORT_ERROR = traceback.format_exc()
    log.error("bot.py NOT loaded: %s", BOT_IMPORT_ERROR[-1500:])

def _now() -> str: return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
def _key_ok() -> bool:
    key = (request.args.get("key") or request.form.get("key") or "").strip()
    return bool(RUN_KEY) and key == RUN_KEY
def _need_key():
    if not _key_ok(): return jsonify({"ok": False, "error": "bad key"}), 403
    return None
def _apply_cookie_to_bot(cookie: str) -> None:
    cookie = (cookie or "").strip()
    RUNTIME["cookie"] = cookie
    os.environ["FULL_COOKIE"] = cookie
    if BOT and hasattr(BOT, "FULL_COOKIE"): BOT.FULL_COOKIE = cookie
        # ---------- helpers ----------
def _tg_send_raw(text: str, chat_id: Optional[str] = None) -> dict:
    import requests
    chat = str(chat_id or CHAT_ID or "").strip()
    token = (BOT_TOKEN or "").strip()
    if not token or not chat: return {"ok": False, "error": "BOT_TOKEN или CHAT_ID пустой"}
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {"chat_id": chat, "text": text[:4000], "disable_web_page_preview": True}
    if re.search(r"<(b|code|i|u|s)>", text): payload["parse_mode"] = "HTML"
    try:
        r = requests.post(url, json=payload, timeout=40)
        data = r.json() if r.ok else {"ok": False, "error": r.text[:500]}
        data["_http_status"] = r.status_code
        data["_chat_id_used"] = chat
        data["_token_tail"] = token[-6:] if len(token) >= 6 else "short"
        return data
    except Exception as e: return {"ok": False, "error": f"{type(e).__name__}: {e}"}

def _tg_via_bot(text: str, chat_id: Optional[str] = None) -> None:
    chat = chat_id or CHAT_ID
    try:
        if BOT and hasattr(BOT, "tg_send"): BOT.tg_send(text, chat)
        elif BOT and hasattr(BOT, "send_telegram"): BOT.send_telegram(text)
    except Exception as e: log.warning("bot.tg_send failed: %s", e)

def _run_job(mode: str, chat_id: Optional[str] = None) -> None:
    mode = (mode or "day").lower().strip()
    target = str(chat_id or CHAT_ID).strip()
    RUNTIME["last_run"] = {"mode": mode, "at": _now(), "chat_id": target}
    RUNTIME["runs"] = int(RUNTIME.get("runs") or 0) + 1
    log.info("BG START mode=%s chat=%s cookie_len=%s", mode, target, len(RUNTIME.get("cookie") or ""))

    try:
        if BOT is None:
            msg = f"bot.py not loaded:\n{(BOT_IMPORT_ERROR or '')[-1500:]}"
            RUNTIME["last_error"] = msg
            _tg_send_raw(f"❌ bot.py not loaded\n{msg[:800]}", target)
            return

        if RUNTIME.get("cookie") and hasattr(BOT, "FULL_COOKIE"): BOT.FULL_COOKIE = RUNTIME["cookie"]

        try: _tg_via_bot(f"⏳ Запуск <b>{mode}</b>… клуб <code>{CLUB_SLUG}</code>", target)
        except: _tg_send_raw(f"⏳ Запуск {mode}… клуб {CLUB_SLUG}", target)

        if hasattr(BOT, "run"):
            try:
                sig = inspect.signature(BOT.run)  # нужно добавить: import inspect
                if len(sig.parameters) >= 2: BOT.run(mode, target)
                else: BOT.run(mode)
            except Exception as e: log.warning("BG run error: %s", e)
        else:
            _tg_send_raw("❌ В bot.py нет функции run()", target)
            RUNTIME["last_error"] = "no run()"
            return
        RUNTIME["last_error"] = None
        log.info("BG DONE mode=%s", mode)
    except Exception as e:
        tb = traceback.format_exc()
        RUNTIME["last_error"] = tb[-2000:]
        log.error("BG CRASH: %s\n%s", e, tb)
        _tg_send_raw(f"Извините, но я обосрался 💩\nГде: app._run_job\n{type(e).__name__}: {e}\n{tb[-900:]}", target)

def _start_bg(mode: str, chat_id: Optional[str] = None) -> None:
    threading.Thread(target=_run_job, args=(mode, chat_id), name=f"run-{mode}", daemon=True).start()

# ---------- routes ----------
@app.route("/", methods=["GET"]) def root(): return health()
@app.route("/health", methods=["GET"]) def health():
    payload = {
        "ok": BOT is not None and not BOT_IMPORT_ERROR,
        "service": SERVICE_NAME,
        "time": _now(),
        "bot_loaded": BOT is not None,
        "token_set": bool(BOT_TOKEN),
        "chat_id_set": bool(CHAT_ID),
        "run_key_set": bool(RUN_KEY),
        "cookie_set": bool(RUNTIME.get("cookie")),
        "cookie_len": len(RUNTIME.get("cookie") or ""),
        "club": CLUB_SLUG,
        "runs": RUNTIME.get("runs", 0),
        "last_run": RUNTIME.get("last_run"),
        "last_error": (RUNTIME.get("last_error") or None)[:400],
        "error": None if BOT is not None else "bot.py not loaded",
        "detail": (BOT_IMPORT_ERROR or "")[:800] if BOT_IMPORT_ERROR else None,
    }
    code = 200 if payload["ok"] else 500
    return jsonify(payload), code

@app.route("/test-tg", methods=["GET", "POST"])
def test_tg():
    bad = _need_key()
    if bad: return bad
    text = f"✅ Тест No Mercy Stats Bot\nclub: {CLUB_SLUG}\ntime: {_now()}"
    data = _tg_send_raw(text, CHAT_ID)
    if not data.get("ok"):
        data2 = _tg_send_raw(text.replace("<", "").replace(">", ""), CHAT_ID)
        data["retry_plain"] = data2
    return jsonify({"ok": bool(data.get("ok")), "msg": "see telegram field", "telegram": data}), (200 if data.get("ok") else 502)

@app.route("/run", methods=["GET", "POST"])
def run_endpoint():
    bad = _need_key()
    if bad: return bad
    if BOT is None: return jsonify({"ok": False, "error": "bot.py not loaded", "detail": (BOT_IMPORT_ERROR or "")[-1200:]}), 500
    mode = (request.args.get("mode") or (request.form.get("mode") if request.form else None) or "day").lower().strip()
    allowed = {"day","today","week","month","all","recent","history","now","daily","weekly"}
    if mode not in allowed: return jsonify({"ok": False, "error": "bad mode", "allowed": sorted(allowed)}), 400
    chat_override = (request.args.get("chat_id") or "").strip() or None
    _start_bg(mode, chat_override)
    return jsonify({"ok": True, "started": True, "mode": mode, "msg": "Работаю в фоне. Результат в Telegram через 1–5 мин.", "club": CLUB_SLUG, "cookie_len": len(RUNTIME.get("cookie") or "")})

@app.route("/set-cookie", methods=["GET", "POST"])
def set_cookie():
    bad = _need_key()
    if bad: return bad
    cookie = (request.args.get("cookie") or (request.form.get("cookie") if request.form else None) or "").strip()
    if request.is_json: cookie = cookie or (request.json.get("cookie") or "")
    if len(cookie) < 40: return jsonify({"ok": False, "error": "cookie too short"}), 400
    _apply_cookie_to_bot(cookie)
    return jsonify({"ok": True, "cookie_len": len(cookie), "msg": "cookie in memory + bot"})
    @app.route("/diag", methods=["GET"])
def diag():
    bad = _need_key()
    if bad: return bad
    import requests
    me = None
    try:
        r = requests.get(f"https://api.telegram.org/bot{BOT_TOKEN}/getMe", timeout=20)
        me = r.json()
    except: me = {"ok": False, "error": "no getMe"}
    chat_info = None
    try:
        r = requests.get(f"https://api.telegram.org/bot{BOT_TOKEN}/getChat", params={"chat_id": CHAT_ID}, timeout=20)
        chat_info = r.json()
    except: chat_info = {"ok": False, "error": "no getChat"}
    return jsonify({
        "ok": True, "time": _now(), "bot_loaded": BOT is not None,
        "getMe": me, "getChat": chat_info,
        "chat_id_env": CHAT_ID, "token_tail": (BOT_TOKEN or "")[-6:],
        "cookie_len": len(RUNTIME.get("cookie") or ""), "club": CLUB_SLUG,
        "last_run": RUNTIME.get("last_run"), "last_error": RUNTIME.get("last_error"),
        "bot_has_run": bool(BOT and hasattr(BOT, "run")),
        "bot_has_tg_send": bool(BOT and hasattr(BOT, "tg_send")),
    })

@app.route("/webhook", methods=["POST"])
def webhook():
    try: data = request.get_json(force=True, silent=True) or {}
    except: data = {}
    log.info("webhook update keys=%s", list(data.keys()))
    try:
        if BOT and hasattr(BOT, "webhook"): BOT.webhook(data)
    except Exception as e: log.error("bot.webhook error: %s", e)
    msg = data.get("message") or data.get("edited_message") or {}
    chat = (msg.get("chat") or {}).get("id")
    text = (msg.get("text") or "").strip().lower()
    if not chat or not text: return jsonify({"ok": True})
    cmd = text.split("@")[0].split()[0] if text.startswith("/") else ""
    mapping = {"/start":"all","/all":"all","/day":"day","/today":"day","/week":"week","/month":"month","/recent":"recent","/history":"recent","/ping":None}
    if cmd in mapping and mapping[cmd]:
        _start_bg(mapping[cmd], str(chat))
        return jsonify({"ok": True, "started": mapping[cmd]})
    if cmd == "/ping": _tg_send_raw("pong ✅", str(chat)); return jsonify({"ok": True})
    return jsonify({"ok": True})

@app.errorhandler(404) def not_found(_e): return jsonify({"ok": False, "error": "not found", "hint": "use /health /test-tg?key=... /run?key=...&mode=day /diag?key=..."}), 404
@app.errorhandler(500) def server_error(e): log.error("500: %s\n%s", e, traceback.format_exc()); return jsonify({"ok": False, "error": "internal", "detail": str(e)}), 500

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, debug=False)
