from __future__ import annotations

import asyncio
import logging
import traceback

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import ErrorEvent

from config import get_settings
from handlers.stats import router as stats_router
from middlewares.errors import ErrorMiddleware
from middlewares.throttling import ThrottlingMiddleware
from scheduler.jobs import catchup_if_missed, setup_scheduler
from utils.logging_setup import setup_logging

log = logging.getLogger(__name__)


async def main() -> None:
    setup_logging()
    s = get_settings()

    bot = Bot(
        token=s.bot_token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    storage = MemoryStorage()
    if s.use_redis:
        try:
            from aiogram.fsm.storage.redis import RedisStorage
            from redis.asyncio import Redis

            storage = RedisStorage(redis=Redis.from_url(s.redis_dsn))
            log.info("FSM: Redis")
        except Exception:
            log.exception("Redis FSM failed — MemoryStorage")
            storage = MemoryStorage()

    dp = Dispatcher(storage=storage)
    dp.message.middleware(ThrottlingMiddleware())
    dp.callback_query.middleware(ThrottlingMiddleware())
    dp.message.middleware(ErrorMiddleware())
    dp.callback_query.middleware(ErrorMiddleware())
    dp.include_router(stats_router)

    @dp.errors()
    async def _on_error(event: ErrorEvent) -> bool:
        log.error("dp.errors: %s\n%s", event.exception, traceback.format_exc())
        return True

    scheduler = setup_scheduler(bot)
    scheduler.start()
    log.info("APScheduler started — daily %02d:%02d %s", s.daily_hour, s.daily_minute, s.tz)

    await catchup_if_missed(bot)

    try:
        me = await bot.get_me()
        log.info("Bot @%s id=%s chat_id=%s club=%s", me.username, me.id, s.chat_id, s.club_slug)
    except Exception:
        log.exception("getMe failed — check BOT_TOKEN")

    # Неубиваемый polling loop
    while True:
        try:
            await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())
            break
        except Exception:
            log.critical("polling crash — restart in 10s\n%s", traceback.format_exc())
            await asyncio.sleep(10)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        log.info("bye")
