from __future__ import annotations

import time
from collections import defaultdict
from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, Message, TelegramObject

from config import get_settings


class ThrottlingMiddleware(BaseMiddleware):
    def __init__(self) -> None:
        self._last: dict[int, float] = defaultdict(float)
        self._rate = get_settings().throttle_seconds

    def _uid(self, event: TelegramObject) -> int | None:
        if isinstance(event, Message) and event.from_user:
            return event.from_user.id
        if isinstance(event, CallbackQuery) and event.from_user:
            return event.from_user.id
        return None

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        uid = self._uid(event)
        if uid is None:
            return await handler(event, data)
        now = time.monotonic()
        if now - self._last[uid] < self._rate:
            if isinstance(event, Message):
                try:
                    await event.answer("⏳ Слишком часто. Подожди секунду.")
                except Exception:
                    pass
            elif isinstance(event, CallbackQuery):
                try:
                    await event.answer("⏳ Подожди…", show_alert=False)
                except Exception:
                    pass
            return None
        self._last[uid] = now
        return await handler(event, data)
