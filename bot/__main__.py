import asyncio
import logging
from pathlib import Path

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.types import BotCommand

from bot.broadcast import Broadcaster
from bot.config import settings
from bot.db.base import init_db
from bot.handlers import admin, directory, legal, schedule, start
from bot.handlers import settings as settings_h
from bot.middlewares import ConsentMiddleware, TimingMiddleware
from bot.scheduler.jobs import Jobs
from bot.services.directory import Directory
from bot.services.schedule import ScheduleService
from bot.services.sut_public.client import SutPublicClient

COMMANDS = [
    BotCommand(command="start", description="Главное меню"),
    BotCommand(command="change", description="Сменить группу"),
    BotCommand(command="docs", description="Документы сервиса"),
    BotCommand(command="delete", description="Удалить все мои данные"),
]  # /stats — только для ADMIN_ID, в меню не показываем


async def main() -> None:
    await init_db()

    bot = Bot(settings.bot_token.get_secret_value(), default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    client = SutPublicClient(interval=settings.crawl_delay, interactive_interval=settings.interactive_delay)
    directory_svc = Directory()
    schedule_svc = ScheduleService(client, directory_svc)
    jobs = Jobs(schedule_svc, Broadcaster(bot))
    await jobs.startup()
    scheduler = jobs.install()

    dp = Dispatcher()
    dp["schedule"] = schedule_svc
    dp["directory"] = directory_svc
    dp.message.outer_middleware(TimingMiddleware())
    dp.callback_query.outer_middleware(TimingMiddleware())
    dp.message.outer_middleware(ConsentMiddleware())
    dp.callback_query.outer_middleware(ConsentMiddleware())
    # Порядок важен: legal и start раньше, т.к. ловят состояние выбора группы и служебные кнопки
    dp.include_routers(admin.router, legal.router, start.router, settings_h.router, schedule.router, directory.router)

    await bot.set_my_commands(COMMANDS)
    try:
        await dp.start_polling(bot)
    finally:
        scheduler.shutdown(wait=False)
        await client.close()
        await bot.session.close()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    Path("data").mkdir(exist_ok=True)
    asyncio.run(main())
