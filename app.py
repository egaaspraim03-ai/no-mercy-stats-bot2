#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""HTTP-кнопки = тот же bot.send_message + run()."""

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
    BOT_ERR = f"{type(e).__name__}: {e}\n{traceback.format_exc()[-1000:]}"


def env(k: str, d: str = "") -> str:
    return (os.environ.get(k) or d).strip()


def key_ok() -> bool:
    need = env("RUN_KEY")
    if not need:
        return True
    return request.args.get("key", "") == need


@app.get("/")
@app.get("/health")
def health():
    return jsonify(
        ok=BOT is not None,
        bot_loaded=BOT is not None,
        error=BOT_ERR,
        token_set=bool(env("BOT_TOKEN")),
        chat_id=env("CHAT_ID", "-1004375644856"),
        club=env("CLUB_SLUG", "utinoe-bratstvo"),
        cookie_len=len(env("FULL_COOKIE")),
        cookie_set=len(env("FULL_COOKIE")) > 40,
        service="no-mercy-stats-bot-unified",
    )


@app.get("/test-tg")
def test_tg():
    if not key_ok():
        return jsonify(ok=False, error="bad key"), 403
    if not BOT:
        return jsonify(ok=False, error="bot not loaded", detail=BOT_ERR), 500
    # Идентично TEST_DIRECT_123
    data = BOT.send_message("TEST_DIRECT_FROM_BOT ✅ unified")
    return jsonify(ok=bool(data.get("ok")), telegram=data)


@app.get("/run")
def run_api():
    if not key_ok():
        return jsonify(ok=False, error="bad key"), 403
    if not BOT:
        return jsonify(ok=False, error="bot not loaded", detail=BOT_ERR), 500
    mode = (request.args.get("mode") or "day").lower().strip()
    # СИНХРОННО — в чат придёт ⏳ + топ/ошибка до ответа браузеру
    result = BOT.run(mode)
    return jsonify(result)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 10000)))
