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
from bot.handlers import admin, calendar, directory, legal, lk, schedule, start
from bot.handlers import settings as settings_h
from bot.middlewares import ConsentMiddleware, TimingMiddleware
from bot.scheduler.jobs import Jobs
from bot.services.calendar import CalendarFeeds
from bot.services.directory import Directory
from bot.services.lk.service import LkService
from bot.services.schedule import ScheduleService
from bot.services.staff import StaffService
from bot.services.sut_public.client import SutPublicClient
from bot.web import WEBHOOK_PATH, start_web

COMMANDS = [
    BotCommand(command="start", description="Главное меню"),
    BotCommand(command="change", description="Сменить группу"),
    BotCommand(command="docs", description="Документы сервиса"),
    BotCommand(command="delete", description="Удалить все мои данные"),
]  # /stats — только для ADMIN_ID, в меню не показываем


def _storage():
    if settings.redis_url:
        from aiogram.fsm.storage.redis import RedisStorage

        return RedisStorage.from_url(settings.redis_url)
    from aiogram.fsm.storage.memory import MemoryStorage

    return MemoryStorage()


async def main() -> None:
    await init_db()

    bot = Bot(settings.bot_token.get_secret_value(), default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    if settings.admin_id:
        from bot.alerts import TelegramAlertHandler

        logging.getLogger().addHandler(TelegramAlertHandler(bot, settings.admin_id))
    client = SutPublicClient(
        interval=settings.crawl_delay,
        interactive_interval=settings.interactive_delay,
        proxy=settings.sut_proxy,
    )
    directory_svc = Directory()
    schedule_svc = ScheduleService(client, directory_svc)
    staff_svc = StaffService(client)
    lk_svc = LkService()
    bc = Broadcaster(bot)
    jobs = Jobs(schedule_svc, bc, staff_svc, lk_svc)
    await jobs.startup()
    scheduler = jobs.install()

    dp = Dispatcher(storage=_storage())
    dp["schedule"] = schedule_svc
    dp["directory"] = directory_svc
    dp["staff"] = staff_svc
    dp["lk"] = lk_svc
    feeds = CalendarFeeds(schedule_svc)
    dp["calendar_feeds"] = feeds
    dp.message.outer_middleware(TimingMiddleware())
    dp.callback_query.outer_middleware(TimingMiddleware())
    dp.message.outer_middleware(ConsentMiddleware())
    dp.callback_query.outer_middleware(ConsentMiddleware())
    # Порядок важен: legal и start раньше, т.к. ловят состояние выбора группы и служебные кнопки
    dp.include_routers(
        admin.router,
        legal.router,
        start.router,
        settings_h.router,
        schedule.router,
        calendar.router,
        lk.router,
        directory.router,  # последним: ловит свободный текст
    )

    await bot.set_my_commands(COMMANDS)
    if settings.public_url:  # кнопка-меню Telegram открывает Mini App (нужен HTTPS)
        from aiogram.types import MenuButtonWebApp, WebAppInfo

        try:
            await bot.set_chat_menu_button(
                menu_button=MenuButtonWebApp(
                    text="Приложение", web_app=WebAppInfo(url=settings.public_url.rstrip("/") + "/app")
                )
            )
        except Exception:
            logging.getLogger(__name__).warning("не удалось установить кнопку Mini App")
    webhook = settings.use_webhook and settings.public_url
    secret = settings.webhook_secret.get_secret_value() if settings.webhook_secret else None
    web_runner = await start_web(
        feeds,
        settings.web_host,
        settings.web_port,
        dp=dp if webhook else None,
        bot=bot,
        secret=secret,
        webapp={"schedule": schedule_svc, "directory": directory_svc, "staff": staff_svc, "lk": lk_svc, "bot": bc},
    )
    try:
        if webhook:
            url = settings.public_url.rstrip("/") + WEBHOOK_PATH
            await bot.set_webhook(url, secret_token=secret, drop_pending_updates=False)
            logging.getLogger(__name__).info("режим вебхука: %s", url)
            await asyncio.Event().wait()  # работаем, пока процесс не остановят
        else:
            await bot.delete_webhook(drop_pending_updates=False)
            await dp.start_polling(bot)
    finally:
        await web_runner.cleanup()
        scheduler.shutdown(wait=False)
        await client.close()
        await lk_svc.close()
        await bot.session.close()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    logging.getLogger("alembic").setLevel(logging.WARNING)
    Path("data").mkdir(exist_ok=True)
    asyncio.run(main())
