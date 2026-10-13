"""Клиент lk.sut.ru. Разметка и эндпоинты описаны в docs/recon.md, раздел 4.

Один экземпляр LkSession — одна учётка студента со своими cookies.
Все сессии делят общий ограничитель частоты, чтобы тысячи студентов не перегружали ЛК.
"""

import asyncio
import logging
import time

import httpx

from bot import metrics
from bot.services.sut_public.client import RateLimiter

log = logging.getLogger(__name__)

BASE = "https://lk.sut.ru/cabinet/"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/128.0 Safari/537.36",
    "Accept-Language": "ru-RU,ru;q=0.9",
    "X-Requested-With": "XMLHttpRequest",
}
ENCODING = "windows-1251"

# Признаки протухшей сессии
_EXPIRED_MARKERS = ("session_error", "У Вас нет прав доступа", "необходимо перезагрузить приложение")


class LkError(Exception):
    pass


class LkAuthError(LkError):
    """Неверный логин или пароль."""


class LkBlockedError(LkError):
    """Вход заблокирован (ЛК вернул error=...)."""


class LkUnavailable(LkError):
    """ЛК не отвечает или вернул ошибку сервера."""


# Общий темп для всех учёток. 0.25 с ≈ 4 запроса в секунду на весь бот.
_limiter = RateLimiter(0.25)


def _expired(text: str) -> bool:
    head = text[:300]
    return any(m in head for m in _EXPIRED_MARKERS)


class LkSession:
    def __init__(self, login: str, password: str, timeout: float = 25.0):
        self.login_name = login
        self._password = password
        self._http = httpx.AsyncClient(base_url=BASE, headers=HEADERS, timeout=timeout, follow_redirects=True)
        self._lock = asyncio.Lock()  # один запрос за раз на учётку: ЛК хранит состояние в сессии
        self.logged_in = False

    async def _request(self, method: str, url: str, **kw) -> str:
        await _limiter.wait()
        t0 = time.perf_counter()
        try:
            r = await self._http.request(method, url, **kw)
        except httpx.HTTPError as e:
            metrics.inc("ЛК: ошибка сети")
            raise LkUnavailable(str(e)) from e
        metrics.observe("ЛК: запрос", time.perf_counter() - t0)
        if r.status_code >= 500:
            metrics.inc("ЛК: ошибка сервера")
            raise LkUnavailable(f"HTTP {r.status_code}")
        return r.content.decode(ENCODING, errors="replace")

    async def login(self) -> str:
        """Входит в ЛК. Возвращает HTML главной страницы (там ФИО, роль, учебная неделя)."""
        await self._request("GET", "")  # получить PHPSESSID
        answer = (
            await self._request(
                "POST", "lib/autentificationok.php", data={"users": self.login_name, "parole": self._password}
            )
        ).strip()
        if "|" in answer:
            raise LkBlockedError(answer)
        if answer in ("", "0"):
            raise LkAuthError("неверный логин или пароль")
        main = await self._request("GET", "", params={"login": "yes"})
        if _expired(main) or 'id="users"' in main:
            raise LkAuthError("ЛК не пустил после входа")
        self.logged_in = True
        metrics.inc("ЛК: вход")
        return main

    async def post(self, modul: str, data: dict[str, str]) -> str:
        """POST в ЛК от имени студента. При протухшей сессии — один перелогин и повтор."""
        async with self._lock:
            for _ in range(2):
                if not self.logged_in:
                    await self.login()
                text = await self._request("POST", modul, data=data)
                if not _expired(text):
                    return text
                self.logged_in = False
                metrics.inc("ЛК: сессия протухла")
            raise LkUnavailable("сессия ЛК не восстанавливается")

    async def form(self, modul: str, key: str | int, **params: str) -> str:
        """Раздел ЛК, как его открывает left_click() в меню кабинета."""
        return await self.post(modul, {"key": str(key), **params})

    async def close(self) -> None:
        await self._http.aclose()
