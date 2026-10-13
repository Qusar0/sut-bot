import logging
import time
from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, Message, TelegramObject

from bot import metrics
from bot.keyboards.main import consent_kb
from bot.services.users import has_actual_consent

log = logging.getLogger(__name__)

CONSENT_TEXT = (
    "Чтобы пользоваться ботом, нужно принять документы. Откройте их кнопками ниже и нажмите «Принимаю все документы»."
)

_FREE_COMMANDS = ("/start", "/docs", "/delete")
_FREE_CALLBACKS = ("legal:", "del:")


class ConsentMiddleware(BaseMiddleware):
    """Пропускает к функциям бота только тех, кто принял актуальные редакции документов (п. 69)."""

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        user = data.get("event_from_user")
        if user is None:
            return await handler(event, data)

        if isinstance(event, Message) and (event.text or "").startswith(_FREE_COMMANDS):
            return await handler(event, data)
        if isinstance(event, CallbackQuery) and (event.data or "").startswith(_FREE_CALLBACKS):
            return await handler(event, data)

        if await has_actual_consent(user.id):
            return await handler(event, data)

        if isinstance(event, CallbackQuery):
            await event.answer()
            await event.message.answer(CONSENT_TEXT, reply_markup=consent_kb())
        elif isinstance(event, Message):
            await event.answer(CONSENT_TEXT, reply_markup=consent_kb())
        return None


class TimingMiddleware(BaseMiddleware):
    """Замеряет время обработки каждого апдейта; медленные пишет в лог."""

    SLOW = 2.0  # секунд

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        if isinstance(event, Message):
            name = "ответ: " + ((event.text or "").split()[0][:24] if event.text else "сообщение")
        elif isinstance(event, CallbackQuery):
            name = "ответ: кнопка " + (event.data or "").split(":")[0]
        else:
            name = "ответ: другое"
        t0 = time.perf_counter()
        try:
            return await handler(event, data)
        finally:
            dt = time.perf_counter() - t0
            metrics.observe(name, dt)
            if dt > self.SLOW:
                log.warning("медленный ответ %.2f с: %s", dt, name)
