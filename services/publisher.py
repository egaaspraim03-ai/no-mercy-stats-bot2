from __future__ import annotations

import asyncio
import logging
from typing import Sequence

from aiogram import Bot
from aiogram.exceptions import TelegramRetryAfter, TelegramAPIError

from config import get_settings

log = logging.getLogger(__name__)


async def send_long_html(bot: Bot, chat_id: str | int, text: str, chunk: int = 3500) -> None:
    """Split long HTML messages; respect 429."""
    parts = _chunk_text(text, chunk)
    for i, part in enumerate(parts):
        await _send_with_retry(bot, chat_id, part)
        if i < len(parts) - 1:
            await asyncio.sleep(0.35)


def _chunk_text(text: str, size: int) -> list[str]:
    if len(text) <= size:
        return [text]
    lines = text.split("\n")
    out: list[str] = []
    buf: list[str] = []
    n = 0
    for line in lines:
        if n + len(line) + 1 > size and buf:
            out.append("\n".join(buf))
            buf = [line]
            n = len(line)
        else:
            buf.append(line)
            n += len(line) + 1
    if buf:
        out.append("\n".join(buf))
    return out


async def _send_with_retry(bot: Bot, chat_id: str | int, text: str, attempts: int = 5) -> None:
    delay = 1.0
    for attempt in range(1, attempts + 1):
        try:
            await bot.send_message(
                chat_id=chat_id,
                text=text,
                parse_mode="HTML",
                disable_web_page_preview=True,
            )
            return
        except TelegramRetryAfter as e:
            wait = float(e.retry_after) + 0.5
            log.warning("429 retry_after=%s attempt=%s", wait, attempt)
            await asyncio.sleep(wait)
        except TelegramAPIError as e:
            log.error("send fail attempt=%s: %s", attempt, e)
            await asyncio.sleep(delay)
            delay = min(delay * 2, 30)
        except Exception as e:
            log.error("send unexpected: %s", e)
            await asyncio.sleep(delay)
            delay = min(delay * 2, 30)
    log.error("give up sending to %s", chat_id)


async def notify_admins(bot: Bot, text: str) -> None:
    s = get_settings()
    for admin in s.admin_ids:
        try:
            await send_long_html(bot, admin, text)
        except Exception:
            log.exception("admin notify fail id=%s", admin)
