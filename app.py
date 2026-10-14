#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Flask API. /run синхронный — результат в Telegram до ответа браузеру."""

from __future__ import annotations

import os
import traceback

from flask import Flask, jsonify, request

app = Flask(__name__)

BOT = None
BOT_ERR = None
try:
    import bot as BOT
except Exception as e:
    BOT_ERR = f"{type(e).__name__}: {e}\n{traceback.format_exc()[-1200:]}"


def env(name: str, default: str = "") -> str:
    return (os.environ.get(name) or default).strip()


def need_key() -> bool:
    key = env("RUN_KEY")
    if not key:
        return True  # если ключ не задан — не блокируем (или поставь False и требуй ключ)
    return request.args.get("key", "") == key


@app.get("/")
@app.get("/health")
def health():
    return jsonify(
        ok=BOT is not None,
        bot_loaded=BOT is not None,
        error=BOT_ERR,
        service="no-mercy-stats-bot",
        token_set=bool(env("BOT_TOKEN")),
        chat_id_set=bool(env("CHAT_ID")),
        cookie_set=bool(env("FULL_COOKIE")) and len(env("FULL_COOKIE")) > 40,
        cookie_len=len(env("FULL_COOKIE")),
        club=env("CLUB_SLUG", "utinoe-bratstvo"),
        run_key_set=bool(env("RUN_KEY")),
        proxy_set=bool(env("PROXY")),
    )


@app.get("/test-tg")
def test_tg():
    if not need_key():
        return jsonify(ok=False, error="bad key"), 403
    if BOT is None:
        return jsonify(ok=False, error="bot not loaded", detail=BOT_ERR), 500
    data = BOT.tg_send("✅ DIRECT TEST from Render bot.py — если видишь, tg_send OK")
    return jsonify(ok=bool(data.get("ok")), telegram=data)


@app.get("/run")
def run():
    if not need_key():
        return jsonify(ok=False, error="bad key"), 403
    if BOT is None:
        return jsonify(ok=False, error="bot not loaded", detail=BOT_ERR), 500
    mode = (request.args.get("mode") or "day").lower().strip()
    # СИНХРОННО: ждём до 90–120 сек (не фон!)
    result = BOT.run(mode)
    return jsonify(
        ok=result.get("ok", False),
        mode=mode,
        error=result.get("error"),
        steps=result.get("steps"),
        msg="Готово. Смотри Telegram (статус + топ или ошибка).",
    )


@app.get("/diag")
def diag():
    if not need_key():
        return jsonify(ok=False, error="bad key"), 403
    import requests as rq

    token = env("BOT_TOKEN")
    chat = env("CHAT_ID")
    out = {}
    try:
        out["getMe"] = rq.get(f"https://api.telegram.org/bot{token}/getMe", timeout=20).json()
    except Exception as e:
        out["getMe"] = str(e)
    try:
        out["getChat"] = rq.get(
            f"https://api.telegram.org/bot{token}/getChat",
            params={"chat_id": chat},
            timeout=20,
        ).json()
    except Exception as e:
        out["getChat"] = str(e)
    return jsonify(out)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 10000)))
