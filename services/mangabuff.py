from __future__ import annotations

import asyncio
import logging
import random
import re
from dataclasses import dataclass
from typing import Any

from bs4 import BeautifulSoup

from config import get_settings

log = logging.getLogger(__name__)

try:
    from curl_cffi.requests import AsyncSession as CffiAsyncSession

    HAS_CFFI = True
except Exception:
    HAS_CFFI = False
    CffiAsyncSession = None  # type: ignore

import aiohttp

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:133.0) Gecko/20100101 Firefox/133.0",
]

JUNK = {"главная", "каталог", "рейтинг", "подборки", "колоды", "клубы", "войти"}


@dataclass
class FetchResult:
    ok: bool
    html: str = ""
    error: str = ""
    status: int | None = None


class MangaBuffClient:
    def __init__(self) -> None:
        self.s = get_settings()
        self.base = "https://mangabuff.ru"
        self.boost = f"{self.base}/clubs/{self.s.club_slug}/boost"
        self.history = f"{self.base}/clubs/{self.s.club_slug}/history"

    def _headers(self) -> dict[str, str]:
        ua = random.choice(USER_AGENTS)
        h = {
            "User-Agent": ua,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
            "Accept-Language": "ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7",
            "Cache-Control": "no-cache",
            "Pragma": "no-cache",
            "Upgrade-Insecure-Requests": "1",
            "Sec-Fetch-Dest": "document",
            "Sec-Fetch-Mode": "navigate",
            "Sec-Fetch-Site": "same-origin",
            "Referer": f"{self.base}/clubs/{self.s.club_slug}",
        }
        cookie = (self.s.full_cookie or "").strip()
        if cookie:
            h["Cookie"] = cookie
        return h

    def _is_blocked(self, status: int | None, text: str) -> bool:
        t = (text or "").lower()
        if status in (403, 429, 502, 503, 520, 521, 522, 523, 524):
            return True
        if "ddos" in t or "cloudflare" in t or "checking your browser" in t:
            return True
        if len(text) < 800 and status == 200:
            return True
        return False

    async def _fetch_once(self, url: str) -> FetchResult:
        headers = self._headers()
        proxy = (self.s.proxy or "").strip() or None
        timeout = self.s.fetch_timeout

        # 1) curl_cffi (лучше TLS fingerprint)
        if HAS_CFFI:
            try:
                async with CffiAsyncSession() as session:
                    r = await session.get(
                        url,
                        headers=headers,
                        proxy=proxy,
                        timeout=timeout,
                        impersonate="chrome131",
                        allow_redirects=True,
                    )
                    text = r.text or ""
                    if self._is_blocked(r.status_code, text):
                        return FetchResult(False, text, f"blocked status={r.status_code} len={len(text)}", r.status_code)
                    return FetchResult(True, text, "", r.status_code)
            except Exception as e:
                log.warning("cffi fetch fail: %s", e)

        # 2) aiohttp fallback
        try:
            conn = aiohttp.TCPConnector(ssl=False)
            async with aiohttp.ClientSession(connector=conn) as session:
                async with session.get(
                    url,
                    headers=headers,
                    proxy=proxy,
                    timeout=aiohttp.ClientTimeout(total=timeout),
                    allow_redirects=True,
                ) as r:
                    text = await r.text(errors="ignore")
                    if self._is_blocked(r.status, text):
                        return FetchResult(False, text, f"blocked status={r.status} len={len(text)}", r.status)
                    return FetchResult(True, text, "", r.status)
        except Exception as e:
            return FetchResult(False, "", f"{type(e).__name__}: {e}", None)

    async def fetch(self, url: str) -> FetchResult:
        delay = 1.0
        last = FetchResult(False, error="no attempts")
        for attempt in range(1, self.s.fetch_retries + 1):
            last = await self._fetch_once(url)
            if last.ok:
                log.info("fetch ok attempt=%s url=%s status=%s", attempt, url, last.status)
                return last
            log.warning("fetch fail attempt=%s url=%s err=%s", attempt, url, last.error)
            await asyncio.sleep(delay + random.uniform(0, 0.5))
            delay = min(delay * 2, 20.0)
        return last

    def parse_boost(self, html: str) -> list[tuple[str, str]]:
        soup = BeautifulSoup(html, "lxml")
        out: list[tuple[str, str]] = []
        rows = soup.select(
            "table tbody tr, .club-boosters-list tr, .boosters-table tr, "
            "[class*='booster'] tr, .flex.items-center"
        )
        for el in rows:
            link = el.select_one("a[href*='/users/']")
            if not link:
                continue
            name = link.get_text(" ", strip=True)
            if not name or name.lower() in JUNK:
                continue
            full = " ".join(el.get_text(" ", strip=True).split())
            m = re.search(r"(\d[\d\s]*)\s*$", full.replace("\xa0", " "))
            if not m:
                nums = re.findall(r"\d[\d\s]*", full)
                if not nums:
                    continue
                score = nums[-1].replace(" ", "")
            else:
                score = m.group(1).replace(" ", "")
            out.append((name, score))
            if len(out) >= 25:
                break
        # unique keep order
        seen: set[str] = set()
        uniq: list[tuple[str, str]] = []
        for n, sc in out:
            if n in seen:
                continue
            seen.add(n)
            uniq.append((n, sc))
        return uniq

    def parse_history(self, html: str, limit: int = 10) -> list[str]:
        soup = BeautifulSoup(html, "lxml")
        items: list[str] = []
        rows = soup.select(
            "table tbody tr, .history-table tr, .club-history tr, "
            "[class*='history'] tr, li, .flex"
        )
        for el in rows:
            link = el.select_one("a[href*='/users/']")
            if not link:
                continue
            name = link.get_text(" ", strip=True)
            if not name or name.lower() in JUNK:
                continue
            full = " ".join(el.get_text(" ", strip=True).split())
            items.append(full[:200])
            if len(items) >= limit:
                break
        return items

    PERIOD = {
        "day": "day",
        "today": "day",
        "daily": "day",
        "week": "week",
        "weekly": "week",
        "month": "month",
        "all": "all",
    }

    async def get_top(self, mode: str) -> tuple[bool, str, list[tuple[str, str]] | list[str]]:
        """
        Returns (ok, error_or_empty, data).
        Never raises to caller — safe for scheduler/handlers.
        """
        try:
            mode = (mode or "day").lower().strip()
            if mode in ("recent", "history"):
                fr = await self.fetch(self.history)
                if not fr.ok:
                    return False, fr.error or "history unavailable", []
                return True, "", self.parse_history(fr.html, 10)

            period = self.PERIOD.get(mode, "day")
            url = f"{self.boost}?period={period}"
            fr = await self.fetch(url)
            if not fr.ok:
                return False, fr.error or "boost unavailable", []
            rows = self.parse_boost(fr.html)
            if not rows:
                return False, "parsed empty (selectors/HTML changed or not logged in)", []
            return True, "", rows
        except Exception as e:
            log.exception("get_top crash")
            return False, f"{type(e).__name__}: {e}", []


def format_top(title: str, rows: list[tuple[str, str]]) -> str:
    if not rows:
        return f"{title}\n\nПусто."
    medals = {1: "🥇", 2: "🥈", 3: "🥉"}
    lines = [f"<b>{title}</b>", f"<i>клуб {get_settings().club_slug}</i>", ""]
    for i, (name, score) in enumerate(rows[:20], 1):
        m = medals.get(i, f"{i}.")
        lines.append(f"{m} <b>{_esc(name)}</b> — <code>{_esc(score)}</code>")
    return "\n".join(lines)


def format_history(items: list[str]) -> str:
    if not items:
        return "<b>🕒 Последние внесения</b>\n\nПусто."
    lines = ["<b>🕒 Последние 10 внесений</b>", ""]
    for i, it in enumerate(items, 1):
        lines.append(f"{i}. {_esc(it)}")
    return "\n".join(lines)


def _esc(s: str) -> str:
    return (
        str(s)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )
