#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
MangaBuff club stats → Telegram
Strong free build: curl_cffi + cloudscraper + cookie
Works on GitHub Actions + Render
"""

from __future__ import annotations

import os
import re
import sys
import traceback
from html import escape
from datetime import datetime
from typing import List, Optional, Tuple
from zoneinfo import ZoneInfo

import requests
from bs4 import BeautifulSoup

try:
    from curl_cffi import requests as cffi_requests
    HAS_CFFI = True
except Exception:
    HAS_CFFI = False
    cffi_requests = None

try:
    import cloudscraper
    HAS_CS = True
except Exception:
    HAS_CS = False
    cloudscraper = None

# ---------- ENV ----------
BOT_TOKEN = os.environ.get("BOT_TOKEN", "").strip()
CHAT_ID = os.environ.get("CHAT_ID", "").strip()
FULL_COOKIE = os.environ.get("FULL_COOKIE", "").strip()
CLUB_SLUG = os.environ.get("CLUB_SLUG", "utinoe-bratstvo").strip()
RUN_KEY = os.environ.get("RUN_KEY", "duck2026").strip()
PROXY = os.environ.get("PROXY", "").strip()  # optional: http://ip:port or http://user:pass@ip:port

BASE = "https://mangabuff.ru"
BOOST_URL = f"{BASE}/clubs/{CLUB_SLUG}/boost"
HISTORY_URL = f"{BASE}/clubs/{CLUB_SLUG}/history"
MSK = ZoneInfo("Europe/Moscow")

JUNK_NAMES = {
    "главная", "каталог", "рейтинг", "подборки", "колоды",
    "лента", "клубы", "профиль", "новости", "меню", "поиск",
}


def now_msk() -> str:
    return datetime.now(MSK).strftime("%d.%m.%Y %H:%M МСК")


def tg_send(text: str, chat_id: Optional[str] = None) -> bool:
    chat = str(chat_id or CHAT_ID).strip()
    if not BOT_TOKEN or not chat:
        print("WARN: no BOT_TOKEN or CHAT_ID", flush=True)
        return False
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
        if r.status_code != 200:
            print("TG fail:", r.status_code, r.text[:400], flush=True)
            return False
        return True
    except Exception as e:
        print("TG exception:", type(e).__name__, e, flush=True)
        return False


def die(where: str, detail: str = "") -> None:
    msg = (
        "Извините пожалуйста, но я <b>обосрался</b> 💩\n"
        f"<b>Где:</b> {escape(str(where))}\n"
        f"<b>Detail:</b> <code>{escape(str(detail)[:1400])}</code>\n"
        "я головой бился об крышу унитаза вместо того чтобы работать как надо"
    )
    tg_send(msg)
    print(f"DIE [{where}] {detail}", flush=True)
    raise SystemExit(1)


def browser_headers() -> dict:
    h = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/131.0.0.0 Safari/537.36"
        ),
        "Accept": (
            "text/html,application/xhtml+xml,application/xml;q=0.9,"
            "image/avif,image/webp,image/apng,*/*;q=0.8"
        ),
        "Accept-Language": "ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7",
        "Accept-Encoding": "gzip, deflate, br",
        "Connection": "keep-alive",
        "Upgrade-Insecure-Requests": "1",
        "Sec-Ch-Ua": '"Google Chrome";v="131", "Chromium";v="131", "Not_A Brand";v="24"',
        "Sec-Ch-Ua-Mobile": "?0",
        "Sec-Ch-Ua-Platform": '"Windows"',
        "Sec-Fetch-Site": "same-origin",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-User": "?1",
        "Sec-Fetch-Dest": "document",
        "Referer": f"{BASE}/clubs/{CLUB_SLUG}",
        "Origin": BASE,
        "Cache-Control": "max-age=0",
    }
    if FULL_COOKIE:
        h["Cookie"] = FULL_COOKIE
    return h


def proxy_dict() -> Optional[dict]:
    if not PROXY:
        return None
    p = PROXY if "://" in PROXY else f"http://{PROXY}"
    return {"http": p, "https": p}


def is_ok_html(text: str, status: int) -> bool:
    if status != 200 or not text:
        return False
    low = text.lower()
    bad = (
        "ddos-guard",
        "ddos guard",
        "checking your browser",
        "please wait",
        "access denied",
        "cf-browser-verification",
        "just a moment",
    )
    if any(b in low for b in bad):
        return False
    if len(text) < 1500:
        return False
    return True


def fetch(url: str) -> str:
    """curl_cffi → cloudscraper → requests. No free-proxy roulette."""
    h = browser_headers()
    px = proxy_dict()
    errors: List[str] = []

    # 1) curl_cffi (best TLS fingerprint)
    if HAS_CFFI:
        for imp in ("chrome131", "chrome124", "chrome120", "chrome"):
            try:
                r = cffi_requests.get(
                    url,
                    headers=h,
                    proxies=px,
                    timeout=30,
                    impersonate=imp,
                    allow_redirects=True,
                )
                if is_ok_html(r.text or "", r.status_code):
                    print(f"fetch OK curl_cffi {imp} len={len(r.text)}", flush=True)
                    return r.text
                errors.append(
                    f"cffi/{imp}: status={r.status_code} len={len(r.text or '')}"
                )
            except Exception as e:
                errors.append(f"cffi/{imp}: {type(e).__name__}: {e}")

    # 2) cloudscraper
    if HAS_CS:
        try:
            sc = cloudscraper.create_scraper(
                browser={"browser": "chrome", "platform": "windows", "mobile": False}
            )
            r = sc.get(url, headers=h, proxies=px, timeout=30)
            if is_ok_html(r.text or "", r.status_code):
                print(f"fetch OK cloudscraper len={len(r.text)}", flush=True)
                return r.text
            errors.append(
                f"cloudscraper: status={r.status_code} len={len(r.text or '')}"
            )
        except Exception as e:
            errors.append(f"cloudscraper: {type(e).__name__}: {e}")

    # 3) plain requests + session
    try:
        s = requests.Session()
        r = s.get(url, headers=h, proxies=px, timeout=35, allow_redirects=True)
        if is_ok_html(r.text or "", r.status_code):
            print(f"fetch OK requests len={len(r.text)}", flush=True)
            return r.text
        low = (r.text or "").lower()
        errors.append(
            f"requests: status={r.status_code} len={len(r.text or '')} "
            f"ddos={'yes' if 'ddos' in low else 'no'}"
        )
    except Exception as e:
        errors.append(f"requests: {type(e).__name__}: {e}")

    detail = (
        "MangaBuff не отдал страницу (403/ddos/короткий HTML).\n"
        f"url={url}\n"
        f"cffi={HAS_CFFI} cloudscraper={HAS_CS} proxy={bool(PROXY)} "
        f"cookie_len={len(FULL_COOKIE)}\n"
        + " | ".join(errors[-8:])
        + "\n\n1) Обнови FULL_COOKIE (Cookie Manager → ВСЯ строка)\n"
        "2) PROXY=http://ip:port (residential) если есть\n"
        "3) Free-прокси почти не работают против DDoS-Guard"
    )
    die("fetch", detail)
    return ""


def parse_boost(html: str) -> List[Tuple[str, str]]:
    soup = BeautifulSoup(html, "lxml")
    out: List[Tuple[str, str]] = []
    seen = set()
    rows = soup.select(
        "table tbody tr, table tr, "
        ".club-boosters-list tr, .boosters-table tr, "
        "[class*='booster'] tr, [class*='member'] tr, "
        "[class*='rating'] tr, li"
    )
    for el in rows:
        a = el.select_one("a[href*='/users/'], a[href*='/user/']")
        if not a:
            continue
        name = (a.get_text(strip=True) or "").strip()
        if not name or name.lower() in JUNK_NAMES:
            continue
        full = " ".join(el.get_text(" ", strip=True).split())
        m = re.search(r"(\d[\d\s\u00a0]*)\s*$", full)
        if not m:
            nums = re.findall(r"\d[\d\s\u00a0]*", full)
            if not nums:
                continue
            score = re.sub(r"\D", "", nums[-1])
        else:
            score = re.sub(r"\D", "", m.group(1))
        key = name.lower()
        if not score or key in seen:
            continue
        seen.add(key)
        out.append((name, score))
        if len(out) >= 25:
            break
    return out


def parse_history(html: str) -> List[str]:
    soup = BeautifulSoup(html, "lxml")
    out: List[str] = []
    for el in soup.select(
        ".club-history-list li, .history-table tr, "
        "[class*='history'] li, [class*='history'] tr, li, tr"
    ):
        t = " ".join(el.get_text(" ", strip=True).split())
        if 10 < len(t) < 220:
            low = t.lower()
            if "главная" in low or "каталог" in low:
                continue
            out.append(t)
            if len(out) >= 12:
                break
    return out


def format_top(title: str, rows: List[Tuple[str, str]]) -> str:
    lines = [
        f"<b>{escape(title)}</b>",
        f"<i>{now_msk()}</i>",
        f"Клуб: <code>{escape(CLUB_SLUG)}</code>",
        "",
    ]
    if not rows:
        lines.append("⚠️ Пусто (активность / cookie / защита / селектор)")
        lines.append(f'\n<a href="{BOOST_URL}">открыть boost</a>')
        return "\n".join(lines)
    medals = ["🥇", "🥈", "🥉"]
    for i, (nick, score) in enumerate(rows[:20]):
        p = medals[i] if i < 3 else f"{i + 1}."
        lines.append(f"{p} <b>{escape(nick)}</b> — <code>{escape(score)}</code>")
    lines.append(f'\n<a href="{BOOST_URL}">открыть boost</a>')
    return "\n".join(lines)


def format_history(rows: List[str]) -> str:
    lines = [
        "<b>📜 Последние кто внёс</b>",
        f"<i>{now_msk()}</i>",
        f"Клуб: <code>{escape(CLUB_SLUG)}</code>",
        "",
    ]
    if not rows:
        lines.append("⚠️ История пустая")
        lines.append(f'\n<a href="{HISTORY_URL}">история</a>')
        return "\n".join(lines)
    for i, t in enumerate(rows[:10], 1):
        lines.append(f"{i}. {escape(t)}")
    lines.append(f'\n<a href="{HISTORY_URL}">история</a>')
    return "\n".join(lines)


def run(mode: Optional[str] = None, chat_id: Optional[str] = None) -> str:
    mode = (mode or "all").lower().strip()
    target = chat_id or CHAT_ID

    print(
        f"=== RUN mode={mode} club={CLUB_SLUG} "
        f"cookie_len={len(FULL_COOKIE)} cffi={HAS_CFFI} cs={HAS_CS} "
        f"proxy={bool(PROXY)} ===",
        flush=True,
    )

    if not BOT_TOKEN or not CHAT_ID:
        die("config", "Нет BOT_TOKEN или CHAT_ID (Secrets / Environment)")
    if not FULL_COOKIE or len(FULL_COOKIE) < 40:
        die("config", "FULL_COOKIE пустой или слишком короткий. Cookie Manager → вся строка.")

    tg_send(
        f"⏳ Запуск <b>{escape(mode)}</b>…\n"
        f"клуб <code>{escape(CLUB_SLUG)}</code>\n"
        f"cffi={HAS_CFFI} cloudscraper={HAS_CS}",
        target,
    )

    period_map = {
        "day": "?period=day",
        "today": "?period=day",
        "now": "?period=day",
        "daily": "?period=day",
        "week": "?period=week",
        "weekly": "?period=week",
        "month": "?period=month",
        "all": "?period=all",
    }
    titles = {
        "day": "📅 Топ сегодня",
        "today": "📅 Топ сегодня",
        "now": "📅 Топ сегодня",
        "daily": "📅 Топ сегодня",
        "week": "🏆 Топ неделя",
        "weekly": "🏆 Топ неделя",
        "month": "📆 Топ месяц",
        "all": "📊 Топ (все время)",
    }

    try:
        if mode in period_map:
            html = fetch(BOOST_URL + period_map[mode])
            rows = parse_boost(html)
            tg_send(format_top(titles.get(mode, "📊 Топ"), rows), target)

        if mode in ("recent", "history", "all"):
            html = fetch(HISTORY_URL)
            items = parse_history(html)
            tg_send(format_history(items), target)

        if mode not in period_map and mode not in ("recent", "history", "all"):
            die("mode", f"Неизвестный mode={mode}. Используй: day|week|month|all|recent")

        tg_send("✅ Готово", target)
        return "ok"
    except SystemExit:
        raise
    except Exception as e:
        die("краш", f"{type(e).__name__}: {e}\n{traceback.format_exc()[-1200:]}")
        return "fail"


if __name__ == "__main__":
    m = sys.argv[1] if len(sys.argv) > 1 else "all"
    run(m)
