#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Единый бот: Telegram = тот же sendMessage, что TEST_DIRECT_123.
MangaBuff → парсинг → sendMessage в группу.
"""

from __future__ import annotations

import os
import re
import traceback
from datetime import datetime
from html import escape
from zoneinfo import ZoneInfo
from urllib.parse import quote

import requests
from bs4 import BeautifulSoup

# optional anti-bot
try:
    from curl_cffi import requests as cffi_requests
    HAS_CFFI = True
except Exception:
    HAS_CFFI = False

try:
    import cloudscraper
    HAS_CS = True
except Exception:
    HAS_CS = False

# ---------- ENV (Render) ----------
BOT_TOKEN = os.environ.get("BOT_TOKEN", "").strip()
CHAT_ID = os.environ.get("CHAT_ID", "-1004375644856").strip()
FULL_COOKIE = os.environ.get("FULL_COOKIE", "").strip()
CLUB_SLUG = os.environ.get("CLUB_SLUG", "utinoe-bratstvo").strip()
PROXY = os.environ.get("PROXY", "").strip()

BASE = "https://mangabuff.ru"
BOOST = f"{BASE}/clubs/{CLUB_SLUG}/boost"
HISTORY = f"{BASE}/clubs/{CLUB_SLUG}/history"
MSK = ZoneInfo("Europe/Moscow")
API = f"https://api.telegram.org/bot{BOT_TOKEN}"

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/131.0.0.0 Safari/537.36"
)

PERIOD = {
    "day": "day", "today": "day", "daily": "day",
    "week": "week", "weekly": "week",
    "month": "month",
    "all": "all",
}
TITLES = {
    "day": "📅 Топ за сутки",
    "today": "📅 Топ за сутки",
    "week": "🏆 Топ за неделю",
    "month": "📆 Топ за месяц",
    "all": "📊 Топ за всё время",
}


def now_msk() -> str:
    return datetime.now(MSK).strftime("%d.%m.%Y %H:%M МСК")


# ========== TELEGRAM — как твой TEST_DIRECT_123 ==========

def send_message(text: str, chat_id: str | None = None, parse_mode: str | None = "HTML") -> dict:
    """
    Тот же API, что:
    https://api.telegram.org/botTOKEN/sendMessage?chat_id=...&text=...
    Сначала POST JSON (удобно), при сбое — GET как в браузере.
    """
    chat = str(chat_id or CHAT_ID).strip()
    if not BOT_TOKEN:
        return {"ok": False, "description": "BOT_TOKEN empty"}
    if not chat:
        return {"ok": False, "description": "CHAT_ID empty"}

    if len(text) > 4000:
        text = text[:3990] + "…"

    # 1) POST (основной)
    try:
        payload = {"chat_id": chat, "text": text, "disable_web_page_preview": True}
        if parse_mode:
            payload["parse_mode"] = parse_mode
        r = requests.post(f"{API}/sendMessage", json=payload, timeout=40)
        data = r.json() if r.content else {"ok": False, "description": f"http {r.status_code}"}
        if data.get("ok"):
            return data
        # если HTML сломал parse_mode — шлём plain
        if parse_mode and "parse" in str(data.get("description", "")).lower():
            return send_message(re.sub(r"<[^>]+>", "", text), chat, parse_mode=None)
        # fallback GET как в браузере
    except Exception as e:
        data = {"ok": False, "description": f"POST {type(e).__name__}: {e}"}

    # 2) GET — идентично твоему успешному тесту
    try:
        plain = re.sub(r"<[^>]+>", "", text) if parse_mode else text
        url = (
            f"{API}/sendMessage"
            f"?chat_id={quote(chat, safe='-')}"
            f"&text={quote(plain[:4000])}"
        )
        r = requests.get(url, timeout=40)
        return r.json() if r.content else {"ok": False, "description": f"GET http {r.status_code}"}
    except Exception as e:
        return {"ok": False, "description": f"GET {type(e).__name__}: {e}"}


def tg(text: str, chat_id: str | None = None) -> dict:
    return send_message(text, chat_id)


# ========== MANGABUFF ==========

def browser_headers() -> dict:
    h = {
        "User-Agent": UA,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "ru-RU,ru;q=0.9,en;q=0.8",
        "Referer": f"{BASE}/clubs/{CLUB_SLUG}",
        "Upgrade-Insecure-Requests": "1",
    }
    if FULL_COOKIE:
        h["Cookie"] = FULL_COOKIE
    return h


def _px():
    return {"http": PROXY, "https": PROXY} if PROXY else None


def fetch(url: str) -> tuple[bool, str, str]:
    """(ok, html, error). Никогда не роняет процесс."""
    h = browser_headers()
    px = _px()
    errs: list[str] = []

    if HAS_CFFI:
        try:
            r = cffi_requests.get(url, headers=h, proxies=px, timeout=25, impersonate="chrome131")
            t = r.text or ""
            if r.status_code == 200 and "ddos" not in t.lower() and len(t) > 1200:
                return True, t, ""
            errs.append(f"cffi {r.status_code} len={len(t)}")
        except Exception as e:
            errs.append(f"cffi {type(e).__name__}: {e}")

    if HAS_CS:
        try:
            r = cloudscraper.create_scraper().get(url, headers=h, proxies=px, timeout=25)
            t = r.text or ""
            if r.status_code == 200 and "ddos" not in t.lower() and len(t) > 1200:
                return True, t, ""
            errs.append(f"cs {r.status_code} len={len(t)}")
        except Exception as e:
            errs.append(f"cs {type(e).__name__}: {e}")

    try:
        r = requests.get(url, headers=h, proxies=px, timeout=25)
        t = r.text or ""
        if r.status_code == 200 and "ddos" not in t.lower() and len(t) > 1200:
            return True, t, ""
        errs.append(f"req {r.status_code} len={len(t)} ddos={'ddos' in t.lower()}")
    except Exception as e:
        errs.append(f"req {type(e).__name__}: {e}")

    return False, "", " | ".join(errs)[:800]


def parse_boost(html: str) -> list[tuple[str, str]]:
    soup = BeautifulSoup(html, "lxml")
    junk = {"главная", "каталог", "рейтинг", "подборки", "колоды", "клубы"}
    out: list[tuple[str, str]] = []
    for el in soup.select(
        "table tbody tr, .club-boosters-list tr, .boosters-table tr, "
        "[class*='booster'] tr, .flex.items-center"
    ):
        a = el.select_one("a[href*='/users/']")
        if not a:
            continue
        name = a.get_text(" ", strip=True)
        if not name or name.lower() in junk:
            continue
        full = " ".join(el.get_text(" ", strip=True).split()).replace("\xa0", " ")
        m = re.search(r"(\d[\d\s]*)\s*$", full)
        if m:
            score = m.group(1).replace(" ", "")
        else:
            nums = re.findall(r"\d+", full)
            if not nums:
                continue
            score = nums[-1]
        out.append((name, score))
        if len(out) >= 20:
            break
    seen, uniq = set(), []
    for n, s in out:
        if n not in seen:
            seen.add(n)
            uniq.append((n, s))
    return uniq


def parse_history(html: str, limit: int = 10) -> list[str]:
    soup = BeautifulSoup(html, "lxml")
    items: list[str] = []
    for el in soup.select("table tbody tr, .history-table tr, [class*='history'] tr, li"):
        a = el.select_one("a[href*='/users/']")
        if not a:
            continue
        name = a.get_text(" ", strip=True)
        if not name:
            continue
        items.append(" ".join(el.get_text(" ", strip=True).split())[:180])
        if len(items) >= limit:
            break
    return items


def fmt_top(title: str, rows: list[tuple[str, str]]) -> str:
    med = {1: "🥇", 2: "🥈", 3: "🥉"}
    lines = [f"<b>{escape(title)}</b>", f"<i>{escape(CLUB_SLUG)}</i> · {now_msk()}", ""]
    if not rows:
        lines.append("Пусто (HTML/сессия/селекторы).")
        return "\n".join(lines)
    for i, (n, s) in enumerate(rows, 1):
        lines.append(f"{med.get(i, f'{i}.')} <b>{escape(n)}</b> — <code>{escape(s)}</code>")
    return "\n".join(lines)


def fmt_hist(items: list[str]) -> str:
    lines = [f"<b>🕒 Последние 10</b>", f"<i>{escape(CLUB_SLUG)}</i> · {now_msk()}", ""]
    if not items:
        lines.append("Пусто.")
        return "\n".join(lines)
    for i, it in enumerate(items, 1):
        lines.append(f"{i}. {escape(it)}")
    return "\n".join(lines)


# ========== ГЛАВНЫЙ ПРОГОН ==========

def run(mode: str = "day", chat_id: str | None = None) -> dict:
    """
    1) sendMessage «⏳»
    2) MangaBuff
    3) sendMessage топ или ошибка
    Всё через один send_message.
    """
    mode = (mode or "day").lower().strip()
    chat = str(chat_id or CHAT_ID).strip()
    out: dict = {"mode": mode, "ok": False, "telegram": [], "error": None}

    def note(label: str, data: dict):
        out["telegram"].append({label: data})

    # --- как TEST_DIRECT: сразу пишем в группу ---
    r0 = send_message(
        f"⏳ Запуск <b>{escape(mode)}</b>\nклуб <code>{escape(CLUB_SLUG)}</code>\n{now_msk()}",
        chat,
    )
    note("start", r0)
    if not r0.get("ok"):
        out["error"] = f"Telegram start fail: {r0}"
        return out

    if not FULL_COOKIE or len(FULL_COOKIE) < 40:
        r = send_message("⚠️ FULL_COOKIE пустой. Обнови cookie в Render.", chat)
        note("cookie", r)
        out["error"] = "no cookie"
        return out

    try:
        if mode in ("recent", "history"):
            ok, html, err = fetch(HISTORY)
            if not ok:
                r = send_message(
                    f"💩 History недоступен\n<code>{escape(err)}</code>",
                    chat,
                )
                note("fail", r)
                out["error"] = err
                return out
            text = fmt_hist(parse_history(html))
            r = send_message(text, chat)
            note("result", r)
            out["ok"] = bool(r.get("ok"))
            if not out["ok"]:
                out["error"] = r
            return out

        period = PERIOD.get(mode)
        if not period:
            r = send_message(f"Неизвестный mode: {escape(mode)}", chat)
            note("bad_mode", r)
            out["error"] = "bad mode"
            return out

        url = f"{BOOST}?period={period}"
        ok, html, err = fetch(url)
        if not ok:
            r = send_message(
                f"💩 Boost ({escape(mode)}) недоступен\n<code>{escape(err)}</code>\n"
                f"Обнови FULL_COOKIE. Telegram работает.",
                chat,
            )
            note("fail", r)
            out["error"] = err
            return out

        rows = parse_boost(html)
        if not rows:
            r = send_message(
                f"⚠️ HTML ok (len={len(html)}), топ пустой. Сессия/селекторы. mode={escape(mode)}",
                chat,
            )
            note("empty", r)
            out["error"] = "empty"
            return out

        r = send_message(fmt_top(TITLES.get(mode, "Топ"), rows), chat)
        note("result", r)
        out["ok"] = bool(r.get("ok"))
        if not out["ok"]:
            out["error"] = r
        return out

    except Exception as e:
        tb = escape(traceback.format_exc()[-700:])
        r = send_message(
            f"💩 Краш: <code>{escape(type(e).__name__)}: {escape(str(e))}</code>\n<pre>{tb}</pre>",
            chat,
        )
        note("crash", r)
        out["error"] = str(e)
        return out
