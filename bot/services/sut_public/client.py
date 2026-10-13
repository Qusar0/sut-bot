"""HTTP-клиент открытого расписания sut.ru с ограничением частоты запросов."""

import asyncio
import time
from datetime import date

import httpx

from bot import metrics

from .models import Group, Week
from .parser import parse_groups, parse_week

BASE_URL = "https://www.sut.ru/studentu/raspisanie/raspisanie-zanyatiy-studentov-ochnoy-i-vecherney-form-obucheniya"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/128.0 Safari/537.36",
    "Accept-Language": "ru-RU,ru;q=0.9",
}


class RateLimiter:
    """Не чаще одного запроса в `interval` секунд на весь процесс."""

    def __init__(self, interval: float):
        self.interval = interval
        self._lock = asyncio.Lock()
        self._last = 0.0

    async def wait(self) -> None:
        async with self._lock:
            delay = self._last + self.interval - time.monotonic()
            if delay > 0:
                await asyncio.sleep(delay)
            self._last = time.monotonic()


class SutPublicClient:
    """Два независимых темпа: быстрый для запросов пользователей и медленный для фонового обхода."""

    def __init__(self, interval: float = 1.0, interactive_interval: float = 0.2, timeout: float = 20.0):
        self._http = httpx.AsyncClient(headers=HEADERS, timeout=timeout, follow_redirects=True)
        self._bg = RateLimiter(interval)
        self._fg = RateLimiter(interactive_interval)

    async def get_url(self, url: str, background: bool = True) -> str:
        """Любая страница sut.ru (например, профили преподавателей) с тем же ограничением частоты."""
        return await self._get(background=background, url=url)

    async def _get(self, params: dict | None = None, background: bool = False, url: str = BASE_URL) -> str:
        limiter = self._bg if background else self._fg
        last_exc: Exception | None = None
        for attempt in range(3):
            await limiter.wait()
            t0 = time.perf_counter()
            try:
                r = await self._http.get(url, params=params)
                r.raise_for_status()
                metrics.observe("sut.ru: запрос", time.perf_counter() - t0)
                return r.text
            except httpx.HTTPError as e:
                metrics.inc("sut.ru: ошибка")
                last_exc = e
                await asyncio.sleep(2**attempt)
        raise last_exc  # type: ignore[misc]

    async def groups(self) -> list[Group]:
        return parse_groups(await self._get(background=True))

    async def week(self, group_id: int, any_day: date, background: bool = False) -> Week:
        html = await self._get({"group": group_id, "date": any_day.isoformat()}, background=background)
        with metrics.timer("sut.ru: парсинг"):
            return parse_week(html, group_id, any_day)

    async def close(self) -> None:
        await self._http.aclose()
