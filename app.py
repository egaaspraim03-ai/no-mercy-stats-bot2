#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
MangaBuff No Mercy Stats Bot — app.py (Render / Gunicorn)
Максимально живучий HTTP-слой:
- health / test-tg (с РЕАЛЬным ответом Telegram)
- /run в фоне (не убивается таймаутом браузера)
- webhook команд
- set-cookie в runtime
- подробные логи в stdout (видны в Render Logs)
"""

from __future__ import annotations

import os
import sys
import traceback
import threading
import logging
from datetime import datetime, timezone
from typing import Any, Optional

from flask import Flask, request, jsonify

# ---------- logging (Render Logs) ----------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    stream=sys.stdout,
)
log = logging.getLogger("app")

# ---------- ENV ----------
BOT_TOKEN = (os.environ.get("BOT_TOKEN") or "").strip()
CHAT_ID = (os.environ.get("CHAT_ID") or "").strip()
RUN_KEY = (os.environ.get("RUN_KEY") or "duck2026").strip()
CLUB_SLUG = (os.environ.get("CLUB_SLUG") or "utinoe-bratstvo").strip()
FULL_COOKIE = (os.environ.get("FULL_COOKIE") or "").strip()
SERVICE_NAME = (os.environ.get("RENDER_SERVICE_NAME") or "no-mercy-stats-bot").strip()

# runtime cookie (обновление без redeploy, живёт до sleep/redeploy)
RUNTIME: dict[str, Any] = {
    "cookie": FULL_COOKIE,
    "last_run": None,
    "last_error": None,
    "runs": 0,
}

app = Flask(__name__)

# ---------- safe import bot ----------
BOT = None
BOT_IMPORT_ERROR: Optional[str] = None

try:
    import bot as _bot  # bot.py рядом
    BOT = _bot
    # подтянуть cookie из env в модуль
    if hasattr(BOT, "FULL_COOKIE") and RUNTIME["cookie"]:
        BOT.FULL_COOKIE = RUNTIME["cookie"]
    log.info("bot.py loaded OK")
except Exception:
    BOT_IMPORT_ERROR = traceback.format_exc()
    log.error("bot.py NOT loaded:\n%s", BOT_IMPORT_ERROR)


# ---------- helpers ----------
def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


def _key_ok() -> bool:
    key = (
        (request.args.get("key") or "")
        or (request.form.get("key") if request.form else "")
        or (request.headers.get("X-Run-Key") or "")
    ).strip()
    return bool(RUN_KEY) and key == RUN_KEY


def _need_key():
    if not _key_ok():
        return jsonify({"ok": False, "error": "bad key"}), 403
    return None


def _apply_cookie_to_bot(cookie: str) -> None:
    cookie = (cookie or "").strip()
    RUNTIME["cookie"] = cookie
    os.environ["FULL_COOKIE"] = cookie
    if BOT is not None and hasattr(BOT, "FULL_COOKIE"):
        BOT.FULL_COOKIE = cookie


def _tg_send_raw(text: str, chat_id: Optional[str] = None) -> dict:
    """
    Отправка с ПОЛНЫМ ответом Telegram (не глотаем ошибки).
    """
    import requests

    chat = str(chat_id or CHAT_ID or "").strip()
    token = (BOT_TOKEN or "").strip()
    if not token:
        return {"ok": False, "error": "BOT_TOKEN empty"}
    if not chat:
        return {"ok": False, "error": "CHAT_ID empty"}

    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {
        "chat_id": chat,
        "text": text[:4000],
        "disable_web_page_preview": True,
    }
    # HTML только если текст похож на разметку; иначе plain (меньше 400)
    if "<b>" in text or "<code>" in text or "<i>" in text:
        payload["parse_mode"] = "HTML"

    try:
        r = requests.post(url, json=payload, timeout=40)
        try:
            data = r.json()
        except Exception:
            data = {"ok": False, "error": "non-json", "body": r.text[:500]}
        data["_http_status"] = r.status_code
        data["_chat_id_used"] = chat
        data["_token_tail"] = token[-6:] if len(token) >= 6 else "short"
        return data
    except Exception as e:
        return {"ok": False, "error": f"{type(e).__name__}: {e}"}


def _tg_via_bot(text: str, chat_id: Optional[str] = None) -> None:
    """Пытаемся bot.tg_send / bot.send_telegram, иначе raw."""
    chat = chat_id or CHAT_ID
    try:
        if BOT is not None:
            if hasattr(BOT, "tg_send"):
                BOT.tg_send(text, chat)
                return
            if hasattr(BOT, "send_telegram"):
                BOT.send_telegram(text)
                return
    except Exception as e:
        log.warning("bot.tg_send failed: %s", e)
    _tg_send_raw(text, chat)


def _run_job(mode: str, chat_id: Optional[str] = None) -> None:
    """Фоновая задача: парсинг + отправка."""
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

        # cookie runtime → bot
        if RUNTIME.get("cookie") and hasattr(BOT, "FULL_COOKIE"):
            BOT.FULL_COOKIE = RUNTIME["cookie"]

        # «Запуск…» сразу (чтобы не было тишины)
        try:
            _tg_via_bot(f"⏳ Запуск <b>{mode}</b>… клуб <code>{CLUB_SLUG}</code>", target)
        except Exception:
            _tg_send_raw(f"⏳ Запуск {mode}… клуб {CLUB_SLUG}", target)

        # вызов bot.run
        if hasattr(BOT, "run"):
            try:
                # разные сигнатуры: run(mode) / run(mode, chat_id)
                import inspect
                sig = inspect.signature(BOT.run)
                if len(sig.parameters) >= 2:
                    result = BOT.run(mode, target)
                else:
                    result = BOT.run(mode)
                log.info("BG bot.run finished mode=%s result=%s", mode, result)
            except SystemExit as se:
                # die() внутри bot
                log.warning("BG SystemExit: %s", se)
                RUNTIME["last_error"] = str(se)
            except TypeError:
                # fallback без chat_id
                BOT.run(mode)
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
        _tg_send_raw(
            f"Извините, но я обосрался 💩\nГде: app._run_job\n{type(e).__name__}: {e}\n{tb[-900:]}",
            target,
        )


def _start_bg(mode: str, chat_id: Optional[str] = None) -> None:
    t = threading.Thread(
        target=_run_job,
        args=(mode, chat_id),
        name=f"run-{mode}",
        daemon=True,
    )
    t.start()


# ---------- routes ----------
@app.route("/", methods=["GET"])
def root():
    return health()


@app.route("/health", methods=["GET"])
def health():
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
        "proxy_set": bool((os.environ.get("PROXY") or "").strip()),
        "runs": RUNTIME.get("runs", 0),
        "last_run": RUNTIME.get("last_run"),
        "last_error": (RUNTIME.get("last_error") or None) and str(RUNTIME["last_error"])[:400],
        "error": None if BOT is not None else "bot.py not loaded",
        "detail": (BOT_IMPORT_ERROR or "")[:800] if BOT_IMPORT_ERROR else None,
    }
    code = 200 if payload["ok"] else 500
    return jsonify(payload), code


@app.route("/test-tg", methods=["GET", "POST"])
def test_tg():
    """Реальный ответ Telegram — больше никакой 'тишины с ok:true'."""
    bad = _need_key()
    if bad:
        return bad

    text = (
        f"✅ Тест No Mercy Stats Bot\n"
        f"time: {_now()}\n"
        f"club: {CLUB_SLUG}\n"
        f"cookie_len: {len(RUNTIME.get('cookie') or '')}\n"
        f"если видишь это — доставка в CHAT_ID работает"
    )
    data = _tg_send_raw(text, CHAT_ID)
    # дубль без HTML на всякий
    if not data.get("ok"):
        data2 = _tg_send_raw(text.replace("<", "").replace(">", ""), CHAT_ID)
        data["retry_plain"] = data2

    return jsonify(
        {
            "ok": bool(data.get("ok")),
            "msg": "see telegram field for real API result",
            "chat_id_env": CHAT_ID,
            "telegram": data,
        }
    ), (200 if data.get("ok") else 502)


@app.route("/run", methods=["GET", "POST"])
def run_endpoint():
    bad = _need_key()
    if bad:
        return bad

    if BOT is None:
        return jsonify(
            {
                "ok": False,
                "error": "bot.py not loaded",
                "detail": (BOT_IMPORT_ERROR or "")[-1200:],
            }
        ), 500

    mode = (
        request.args.get("mode")
        or (request.form.get("mode") if request.form else None)
        or "day"
    )
    mode = str(mode).lower().strip()
    allowed = {
        "day", "today", "week", "month", "all",
        "recent", "history", "now", "daily", "weekly",
    }
    if mode not in allowed:
        return jsonify({"ok": False, "error": "bad mode", "allowed": sorted(allowed)}), 400

    chat_override = (request.args.get("chat_id") or "").strip() or None
    _start_bg(mode, chat_override)

    return jsonify(
        {
            "ok": True,
            "started": True,
            "mode": mode,
            "msg": "Работаю в фоне. Результат в Telegram через 1–5 мин.",
            "club": CLUB_SLUG,
            "cookie_len": len(RUNTIME.get("cookie") or ""),
            "at": _now(),
        }
    )


@app.route("/set-cookie", methods=["GET", "POST"])
def set_cookie():
    """Обновить FULL_COOKIE без redeploy (до sleep Render)."""
    bad = _need_key()
    if bad:
        return bad

    cookie = (
        request.args.get("cookie")
        or (request.form.get("cookie") if request.form else None)
        or ""
    )
    if request.is_json and request.json:
        cookie = cookie or (request.json.get("cookie") or "")

    cookie = str(cookie).strip()
    if len(cookie) < 40:
        return jsonify({"ok": False, "error": "cookie too short"}), 400

    _apply_cookie_to_bot(cookie)
    log.info("cookie updated len=%s", len(cookie))
    return jsonify({"ok": True, "cookie_len": len(cookie), "msg": "cookie in memory + bot"})


@app.route("/diag", methods=["GET"])
def diag():
    """Расширенная диагностика (по ключу)."""
    bad = _need_key()
    if bad:
        return bad

    # getMe
    import requests
    me = None
    try:
        r = requests.get(f"https://api.telegram.org/bot{BOT_TOKEN}/getMe", timeout=20)
        me = r.json()
    except Exception as e:
        me = {"ok": False, "error": str(e)}

    # getChat
    chat_info = None
    try:
        r = requests.get(
            f"https://api.telegram.org/bot{BOT_TOKEN}/getChat",
            params={"chat_id": CHAT_ID},
            timeout=20,
        )
        chat_info = r.json()
    except Exception as e:
        chat_info = {"ok": False, "error": str(e)}

    return jsonify(
        {
            "ok": True,
            "time": _now(),
            "bot_loaded": BOT is not None,
            "getMe": me,
            "getChat": chat_info,
            "chat_id_env": CHAT_ID,
            "token_tail": (BOT_TOKEN or "")[-6:],
            "cookie_len": len(RUNTIME.get("cookie") or ""),
            "club": CLUB_SLUG,
            "last_run": RUNTIME.get("last_run"),
            "last_error": RUNTIME.get("last_error"),
            "bot_has_run": bool(BOT and hasattr(BOT, "run")),
            "bot_has_tg_send": bool(BOT and hasattr(BOT, "tg_send")),
        }
    )


@app.route("/webhook", methods=["POST"])
def webhook():
    """
    Telegram webhook (опционально).
    setWebhook: https://api.telegram.org/bot<TOKEN>/setWebhook?url=https://ТВОЙ.onrender.com/webhook
    """
    try:
        data = request.get_json(force=True, silent=True) or {}
    except Exception:
        data = {}

    log.info("webhook update keys=%s", list(data.keys()))

    # команды из bot.webhook если есть
    try:
        if BOT is not None and hasattr(BOT, "webhook"):
            BOT.webhook(data)
            return jsonify({"ok": True})
    except Exception as e:
        log.error("bot.webhook error: %s", e)

    # встроенные команды
    msg = data.get("message") or data.get("edited_message") or {}
    chat = (msg.get("chat") or {}).get("id")
    text = (msg.get("text") or "").strip().lower()
    if not chat or not text:
        return jsonify({"ok": True})

    mapping = {
        "/start": "all",
        "/all": "all",
        "/day": "day",
        "/today": "day",
        "/week": "week",
        "/month": "month",
        "/recent": "recent",
        "/history": "recent",
        "/ping": None,
    }
    # /day@HlebResult_bot
    cmd = text.split("@")[0].split()[0] if text.startswith("/") else ""
    if cmd == "/ping":
        _tg_send_raw("pong ✅", str(chat))
        return jsonify({"ok": True})
    if cmd in mapping and mapping[cmd]:
        _start_bg(mapping[cmd], str(chat))
        return jsonify({"ok": True, "started": mapping[cmd]})

    return jsonify({"ok": True})


@app.errorhandler(404)
def not_found(_e):
    return jsonify(
        {
            "ok": False,
            "error": "not found",
            "hint": "use /health /test-tg?key=... /run?key=...&mode=day /diag?key=...",
        }
    ), 404


@app.errorhandler(500)
def server_error(e):
    log.error("500: %s\n%s", e, traceback.format_exc())
    return jsonify({"ok": False, "error": "internal", "detail": str(e)}), 500


# gunicorn: app:app
if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, debug=False)
