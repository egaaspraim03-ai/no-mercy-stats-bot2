#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""MangaBuff → Telegram. Без SystemExit. Ошибки всегда в чат."""

from __future__ import annotations

import os
import re
import traceback
from datetime import datetime
from html import escape
from zoneinfo import ZoneInfo

import requests
from bs4 import BeautifulSoup

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

BOT_TOKEN = os.environ.get("BOT_TOKEN", "").strip()
CHAT_ID = os.environ.get("CHAT_ID", "").strip()
FULL_COOKIE = os.environ.get("FULL_COOKIE", "").strip()
CLUB_SLUG = os.environ.get("CLUB_SLUG", "utinoe-bratstvo").strip()
PROXY = os.environ.get("PROXY", "").strip()

BASE = "https://mangabuff.ru"
BOOST_URL = f"{BASE}/clubs/{CLUB_SLUG}/boost"
HISTORY_URL = f"{BASE}/clubs/{CLUB_SLUG}/history"
MSK = ZoneInfo("Europe/Moscow")

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/131.0.0.0 Safari/537.36"
)


def now_msk() -> str:
    return datetime.now(MSK).strftime("%d.%m.%Y %H:%M МСК")


def tg_send(text: str, chat_id: str | None = None) -> dict:
    """Всегда ходит в Telegram API и возвращает JSON. Не глотает ошибку молча."""
    chat = str(chat_id or CHAT_ID).strip()
    if not BOT_TOKEN or not chat:
        return {"ok": False, "description": "no BOT_TOKEN or CHAT_ID"}
    # Telegram limit ~4096
    if len(text) > 4000:
        text = text[:3990] + "…"
    try:
        r = requests.post(
            f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
            json={
                "chat_id": chat,
                "text": text,
                "parse_mode": "HTML",
                "disable_web_page_preview": True,
            },
            timeout=40,
        )
        try:
            data = r.json()
        except Exception:
            data = {"ok": False, "description": r.text[:500], "http": r.status_code}
        return data
    except Exception as e:
        return {"ok": False, "description": f"{type(e).__name__}: {e}"}


def headers() -> dict:
    h = {
        "User-Agent": UA,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "ru-RU,ru;q=0.9,en;q=0.8",
        "Referer": f"{BASE}/clubs/{CLUB_SLUG}",
        "Sec-Fetch-Dest": "document",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Site": "same-origin",
    }
    if FULL_COOKIE:
        h["Cookie"] = FULL_COOKIE
    return h


def proxies_dict():
    if not PROXY:
        return None
    return {"http": PROXY, "https": PROXY}


def fetch(url: str) -> tuple[bool, str, str]:
    """
    return: (ok, html_or_empty, error_or_empty)
    Никогда не кидает наружу.
    """
    h = headers()
    px = proxies_dict()
    errors: list[str] = []

    # 1) curl_cffi
    if HAS_CFFI:
        try:
            r = cffi_requests.get(
                url, headers=h, proxies=px, timeout=25, impersonate="chrome131"
            )
            text = r.text or ""
            if r.status_code == 200 and "ddos" not in text.lower() and len(text) > 1200:
                return True, text, ""
            errors.append(f"cffi status={r.status_code} len={len(text)} ddos={'ddos' in text.lower()}")
        except Exception as e:
            errors.append(f"cffi {type(e).__name__}: {e}")

    # 2) cloudscraper
    if HAS_CS:
        try:
            sc = cloudscraper.create_scraper()
            r = sc.get(url, headers=h, proxies=px, timeout=25)
            text = r.text or ""
            if r.status_code == 200 and "ddos" not in text.lower() and len(text) > 1200:
                return True, text, ""
            errors.append(f"cs status={r.status_code} len={len(text)}")
        except Exception as e:
            errors.append(f"cs {type(e).__name__}: {e}")

    # 3) plain requests
    try:
        r = requests.get(url, headers=h, proxies=px, timeout=25)
        text = r.text or ""
        if r.status_code == 200 and "ddos" not in text.lower() and len(text) > 1200:
            return True, text, ""
        errors.append(f"req status={r.status_code} len={len(text)} ddos={'ddos' in text.lower()}")
    except Exception as e:
        errors.append(f"req {type(e).__name__}: {e}")

    return False, "", " | ".join(errors)[:900]


def parse_boost(html: str) -> list[tuple[str, str]]:
    soup = BeautifulSoup(html, "lxml")
    out: list[tuple[str, str]] = []
    junk = {"главная", "каталог", "рейтинг", "подборки", "колоды", "клубы"}
    rows = soup.select(
        "table tbody tr, .club-boosters-list tr, .boosters-table tr, "
        "[class*='booster'] tr, .flex.items-center"
    )
    for el in rows:
        link = el.select_one("a[href*='/users/']")
        if not link:
            continue
        name = link.get_text(" ", strip=True)
        if not name or name.lower() in junk:
            continue
        full = " ".join(el.get_text(" ", strip=True).split())
        m = re.search(r"(\d[\d\s]*)\s*$", full.replace("\xa0", " "))
        if not m:
            nums = re.findall(r"\d+", full)
            if not nums:
                continue
            score = nums[-1]
        else:
            score = m.group(1).replace(" ", "")
        out.append((name, score))
        if len(out) >= 20:
            break
    seen = set()
    uniq = []
    for n, s in out:
        if n in seen:
            continue
        seen.add(n)
        uniq.append((n, s))
    return uniq


def parse_history(html: str, limit: int = 10) -> list[str]:
    soup = BeautifulSoup(html, "lxml")
    items: list[str] = []
    junk = {"главная", "каталог", "рейтинг"}
    for el in soup.select("table tbody tr, .history-table tr, [class*='history'] tr, li"):
        link = el.select_one("a[href*='/users/']")
        if not link:
            continue
        name = link.get_text(" ", strip=True)
        if not name or name.lower() in junk:
            continue
        items.append(" ".join(el.get_text(" ", strip=True).split())[:180])
        if len(items) >= limit:
            break
    return items


def format_top(title: str, rows: list[tuple[str, str]]) -> str:
    medals = {1: "🥇", 2: "🥈", 3: "🥉"}
    lines = [f"<b>{escape(title)}</b>", f"<i>{escape(CLUB_SLUG)}</i> · {now_msk()}", ""]
    if not rows:
        lines.append("Пусто (селекторы/HTML/не залогинен).")
        return "\n".join(lines)
    for i, (name, score) in enumerate(rows, 1):
        m = medals.get(i, f"{i}.")
        lines.append(f"{m} <b>{escape(name)}</b> — <code>{escape(score)}</code>")
    return "\n".join(lines)


def format_history(items: list[str]) -> str:
    lines = [f"<b>🕒 Последние внесения</b>", f"<i>{escape(CLUB_SLUG)}</i> · {now_msk()}", ""]
    if not items:
        lines.append("Пусто.")
        return "\n".join(lines)
    for i, it in enumerate(items, 1):
        lines.append(f"{i}. {escape(it)}")
    return "\n".join(lines)


PERIOD = {
    "day": "day",
    "today": "day",
    "daily": "day",
    "week": "week",
    "weekly": "week",
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


def run(mode: str = "day", chat_id: str | None = None) -> dict:
    """
    Синхронный прогон. Всегда пишет в Telegram статус + результат или ошибку.
    return: dict для JSON API
    """
    mode = (mode or "day").lower().strip()
    target = str(chat_id or CHAT_ID).strip()
    report: dict = {"mode": mode, "ok": False, "steps": []}

    def step(name: str, data):
        report["steps"].append({name: data})

    # 0) старт в чат
    r0 = tg_send(f"⏳ Запуск <b>{escape(mode)}</b>… клуб <code>{escape(CLUB_SLUG)}</code>", target)
    step("start_tg", r0)
    if not r0.get("ok"):
        report["error"] = f"cannot send start: {r0}"
        return report

    if not FULL_COOKIE or len(FULL_COOKIE) < 40:
        msg = "⚠️ FULL_COOKIE пустой/короткий. Обнови cookie."
        step("cookie", tg_send(msg, target))
        report["error"] = "no cookie"
        return report

    try:
        if mode in ("recent", "history"):
            ok, html, err = fetch(HISTORY_URL)
            step("fetch_history", {"ok": ok, "err": err, "len": len(html)})
            if not ok:
                step("fail_tg", tg_send(
                    f"💩 MangaBuff history недоступен\n<code>{escape(err)}</code>",
                    target,
                ))
                report["error"] = err
                return report
            items = parse_history(html)
            step("parse", {"n": len(items)})
            step("result_tg", tg_send(format_history(items), target))
            report["ok"] = True
            return report

        period = PERIOD.get(mode)
        if not period:
            step("bad_mode", tg_send(f"Неизвестный mode: {escape(mode)}", target))
            report["error"] = "bad mode"
            return report

        url = f"{BOOST_URL}?period={period}"
        ok, html, err = fetch(url)
        step("fetch_boost", {"ok": ok, "err": err, "len": len(html), "url": url})
        if not ok:
            step("fail_tg", tg_send(
                f"💩 MangaBuff boost недоступен ({escape(mode)})\n"
                f"<code>{escape(err)}</code>\n"
                f"Обнови FULL_COOKIE или PROXY. Бот жив.",
                target,
            ))
            report["error"] = err
            return report

        rows = parse_boost(html)
        step("parse", {"n": len(rows)})
        if not rows:
            step("empty_tg", tg_send(
                f"⚠️ HTML получен (len={len(html)}), но топ пустой.\n"
                f"Сессия/селекторы. mode={escape(mode)}",
                target,
            ))
            report["error"] = "empty parse"
            return report

        title = TITLES.get(mode, "Топ")
        step("result_tg", tg_send(format_top(title, rows), target))
        report["ok"] = True
        return report

    except Exception as e:
        tb = traceback.format_exc()[-800:]
        step("crash_tg", tg_send(
            f"💩 Краш: <code>{escape(type(e).__name__)}: {escape(str(e))}</code>\n"
            f"<pre>{escape(tb)}</pre>",
            target,
        ))
        report["error"] = str(e)
        return report
