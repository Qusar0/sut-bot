"""Массовая отправка сообщений с соблюдением лимитов Telegram (~30 сообщений/с)."""
import asyncio
import logging

from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError, TelegramRetryAfter

from bot.services.users import set_user_fields

log = logging.getLogger(__name__)

RATE = 25  # сообщений в секунду, с запасом


class Broadcaster:
    def __init__(self, bot: Bot):
        self.bot = bot
        self._lock = asyncio.Lock()
        self._interval = 1 / RATE

    async def send(self, chat_id: int, text: str, **kwargs) -> bool:
        async with self._lock:  # глобальный темп на весь процесс
            await asyncio.sleep(self._interval)
        for _ in range(3):
            try:
                await self.bot.send_message(chat_id, text, **kwargs)
                return True
            except TelegramRetryAfter as e:
                await asyncio.sleep(e.retry_after + 1)
            except TelegramForbiddenError:
                await set_user_fields(chat_id, blocked=True)
                return False
            except TelegramBadRequest as e:
                log.warning("не отправлено %s: %s", chat_id, e)
                return False
        return False

    async def send_many(self, chat_ids: list[int], text: str, **kwargs) -> int:
        sent = 0
        for cid in chat_ids:
            sent += await self.send(cid, text, **kwargs)
        return sent
