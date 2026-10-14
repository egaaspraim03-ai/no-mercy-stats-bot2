from __future__ import annotations

import logging
import traceback
from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware
from aiogram.exceptions import TelegramAPIError, TelegramForbiddenError, TelegramRetryAfter
from aiogram.types import CallbackQuery, Message, TelegramObject

log = logging.getLogger(__name__)


class ErrorMiddleware(BaseMiddleware):
    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        try:
            return await handler(event, data)
        except TelegramRetryAfter as e:
            log.warning("RetryAfter %s: %s", e.retry_after, e)
            return None
        except TelegramForbiddenError as e:
            log.warning("Forbidden: %s", e)
            return None
        except TelegramAPIError as e:
            log.error("TelegramAPIError: %s\n%s", e, traceback.format_exc())
            await self._notify(event, "Временная ошибка Telegram API. Попробуй позже.")
            return None
        except Exception as e:
            log.critical("Unhandled: %s\n%s", e, traceback.format_exc())
            await self._notify(event, "Извините, произошла ошибка. Бот продолжает работать.")
            return None

    @staticmethod
    async def _notify(event: TelegramObject, text: str) -> None:
        try:
            if isinstance(event, Message):
                await event.answer(text)
            elif isinstance(event, CallbackQuery):
                await event.answer(text, show_alert=True)
        except Exception:
            pass
