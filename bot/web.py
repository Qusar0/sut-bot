"""HTTP-сервер бота: лента подписки на календарь (п. 32) и проверка живости."""

import logging

from aiohttp import web

from bot import metrics
from bot.services.calendar import CalendarFeeds, user_by_token

log = logging.getLogger(__name__)


def build_app(feeds: CalendarFeeds) -> web.Application:
    async def calendar(request: web.Request) -> web.Response:
        token = request.match_info["token"]
        user = await user_by_token(token)
        if user is None or not user.group_id:
            raise web.HTTPNotFound()
        with metrics.timer("календарь: лента"):
            try:
                data = await feeds.for_group(user.group_id)
            except Exception:
                log.exception("лента календаря")
                raise web.HTTPServiceUnavailable() from None
        return web.Response(
            body=data,
            content_type="text/calendar",
            charset="utf-8",
            headers={"Cache-Control": "max-age=1800"},
        )

    async def health(_: web.Request) -> web.Response:
        return web.Response(text="ok")

    app = web.Application()
    app.router.add_get("/cal/{token}.ics", calendar)
    app.router.add_get("/health", health)
    return app


WEBHOOK_PATH = "/tg/webhook"


async def start_web(feeds: CalendarFeeds, host: str, port: int, dp=None, bot=None, secret: str | None = None):
    """Поднимает HTTP-сервер. Если переданы dp и bot — он же принимает вебхук Telegram."""
    app = build_app(feeds)
    if dp is not None and bot is not None:
        from aiogram.webhook.aiohttp_server import SimpleRequestHandler, setup_application

        SimpleRequestHandler(dispatcher=dp, bot=bot, secret_token=secret).register(app, path=WEBHOOK_PATH)
        setup_application(app, dp, bot=bot)
    runner = web.AppRunner(app, access_log=None)  # токены и ссылки календаря в логи не пишем
    await runner.setup()
    await web.TCPSite(runner, host, port).start()
    log.info("веб-сервер слушает %s:%s", host, port)
    return runner
