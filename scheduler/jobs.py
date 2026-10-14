from __future__ import annotations

import logging
from datetime import datetime
from zoneinfo import ZoneInfo

from aiogram import Bot
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from config import get_settings
from handlers.stats import run_stats

log = logging.getLogger(__name__)


def setup_scheduler(bot: Bot) -> AsyncIOScheduler:
    s = get_settings()
    tz = ZoneInfo(s.tz)
    scheduler = AsyncIOScheduler(timezone=tz)

    async def daily_job() -> None:
        log.info("daily_job start 23:55")
        try:
            # сутки + последние внесения
            await run_stats(bot, s.chat_id, "day")
            await run_stats(bot, s.chat_id, "recent")
        except Exception:
            log.exception("daily_job failed (swallowed — process lives)")

    scheduler.add_job(
        daily_job,
        CronTrigger(hour=s.daily_hour, minute=s.daily_minute, timezone=tz),
        id="daily_mangabuff",
        replace_existing=True,
        max_instances=1,
        coalesce=True,           # если проспали несколько тиков — один запуск
        misfire_grace_time=3600, # до 1 часа после 23:55 всё ещё выполнить
    )
    return scheduler


async def catchup_if_missed(bot: Bot) -> None:
    """
    При старте: если сейчас после 23:55 МСК и ещё не публиковали «сегодня» —
    можно форсировать (простая эвристика: только логируем; для строгого учёта нужен Redis flag).
    """
    s = get_settings()
    tz = ZoneInfo(s.tz)
    now = datetime.now(tz)
    log.info("scheduler catchup check now=%s", now.isoformat())
    # Без persistent store не шлём автоматом при каждом рестарте (анти-спам).
    # Надёжный catch-up: хранить last_success_date в Redis/file — добавь при необходимости.
