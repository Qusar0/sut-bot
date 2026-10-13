"""Алерты администратору в Telegram: ошибки из логов, не чаще раза в 10 минут на одинаковую ошибку."""

import asyncio
import logging
import time
from html import escape

from aiogram import Bot

COOLDOWN = 600  # секунд между одинаковыми алертами
MAX_LEN = 3500


class TelegramAlertHandler(logging.Handler):
    """Логгер-хендлер: ERROR и выше уходят админу. Пароли и токены в логи бот не пишет."""

    def __init__(self, bot: Bot, admin_id: int):
        super().__init__(level=logging.ERROR)
        self.bot = bot
        self.admin_id = admin_id
        self._last: dict[str, float] = {}
        self._tasks: set[asyncio.Task] = set()

    def emit(self, record: logging.LogRecord) -> None:
        if record.name.startswith(("aiogram.event", "bot.alerts")):
            return
        key = f"{record.name}:{record.getMessage()[:120]}"
        now = time.monotonic()
        last = self._last.get(key)
        if last is not None and now - last < COOLDOWN:
            return
        self._last[key] = now
        text = (
            f"🚨 <b>{escape(record.levelname)}</b> · <code>{escape(record.name)}</code>\n{escape(record.getMessage())}"
        )
        if record.exc_info:
            text += "\n\n<pre>" + escape(self.format(record).splitlines()[-1][:500]) + "</pre>"
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        task = loop.create_task(self._send(text[:MAX_LEN]))
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def _send(self, text: str) -> None:
        try:
            await self.bot.send_message(self.admin_id, text, disable_notification=False)
        except Exception:  # алерты не должны ронять бота
            pass
