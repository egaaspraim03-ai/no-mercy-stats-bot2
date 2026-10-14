from __future__ import annotations

import logging

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

from config import get_settings
from services.mangabuff import MangaBuffClient, format_history, format_top
from services.publisher import notify_admins, send_long_html

router = Router(name="stats")
log = logging.getLogger(__name__)

TITLES = {
    "day": "📅 Топ за сутки",
    "today": "📅 Топ за сутки",
    "week": "🏆 Топ за неделю",
    "month": "📆 Топ за месяц",
    "all": "📊 Топ за всё время",
}


async def run_stats(bot, chat_id: str | int, mode: str, reply_to: Message | None = None) -> None:
    s = get_settings()
    mode = mode.lower().strip()
    client = MangaBuffClient()

    if reply_to:
        try:
            await reply_to.answer(f"⏳ Собираю <b>{mode}</b>…")
        except Exception:
            pass

    if not (s.full_cookie or "").strip():
        msg = "⚠️ FULL_COOKIE пустой. Обнови cookie в .env / env."
        await send_long_html(bot, chat_id, msg)
        await notify_admins(bot, msg)
        return

    ok, err, data = await client.get_top(mode)
    if not ok:
        fail = (
            f"Извините, MangaBuff недоступен 💩\n"
            f"<b>mode:</b> {mode}\n"
            f"<b>detail:</b> <code>{err}</code>\n"
            f"Бот жив. Обнови FULL_COOKIE или PROXY."
        )
        await send_long_html(bot, chat_id, fail)
        await notify_admins(bot, fail)
        return

    if mode in ("recent", "history"):
        text = format_history(data)  # type: ignore[arg-type]
    else:
        text = format_top(TITLES.get(mode, "Топ"), data)  # type: ignore[arg-type]

    await send_long_html(bot, chat_id, text)


@router.message(Command("start", "help"))
async def cmd_help(message: Message) -> None:
    await message.answer(
        "Команды:\n"
        "/day — сутки\n"
        "/week — неделя\n"
        "/month — месяц\n"
        "/all — всё время\n"
        "/recent — последние 10\n"
        "/ping — проверка\n\n"
        "Авто: каждый день 23:55 МСК → топ суток + recent"
    )


@router.message(Command("ping"))
async def cmd_ping(message: Message) -> None:
    await message.answer("pong ✅")


@router.message(Command("day", "today"))
async def cmd_day(message: Message) -> None:
    await run_stats(message.bot, message.chat.id, "day", message)


@router.message(Command("week"))
async def cmd_week(message: Message) -> None:
    await run_stats(message.bot, message.chat.id, "week", message)


@router.message(Command("month"))
async def cmd_month(message: Message) -> None:
    await run_stats(message.bot, message.chat.id, "month", message)


@router.message(Command("all"))
async def cmd_all(message: Message) -> None:
    await run_stats(message.bot, message.chat.id, "all", message)


@router.message(Command("recent", "history"))
async def cmd_recent(message: Message) -> None:
    await run_stats(message.bot, message.chat.id, "recent", message)
