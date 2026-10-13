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


async def start_web(feeds: CalendarFeeds, host: str, port: int) -> web.AppRunner:
    runner = web.AppRunner(build_app(feeds), access_log=None)  # токены в логи не пишем
    await runner.setup()
    await web.TCPSite(runner, host, port).start()
    log.info("веб-сервер слушает %s:%s", host, port)
    return runner
