import asyncio
import logging

from bot.alerts import TelegramAlertHandler


class FakeBot:
    def __init__(self):
        self.sent = []

    async def send_message(self, chat_id, text, **kw):
        self.sent.append((chat_id, text))


async def test_alert_cooldown():
    bot = FakeBot()
    log = logging.getLogger("bot.test_alerts")
    h = TelegramAlertHandler(bot, admin_id=1)
    log.addHandler(h)
    try:
        log.error("парсер сломался")
        log.error("парсер сломался")  # повтор в окне — не шлём
        log.warning("не ошибка")
        await asyncio.gather(*h._tasks)
    finally:
        log.removeHandler(h)
    assert len(bot.sent) == 1 and "парсер сломался" in bot.sent[0][1]
