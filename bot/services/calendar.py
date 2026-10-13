"""Секретные ссылки на подписку календаря и сборка ленты .ics (п. 32)."""

import secrets
import time
from urllib.parse import quote

from bot.config import settings
from bot.db.base import Session
from bot.db.models import CalendarToken, User
from bot.render.ics import build_ics
from bot.services.schedule import ScheduleService
from bot.services.users import get_group

FEED_TTL = 1800  # секунд: лента группы пересобирается не чаще раза в 30 минут


async def get_token(tg_id: int, reset: bool = False) -> str:
    async with Session() as s:
        row = await s.get(CalendarToken, tg_id)
        if row is None or reset:
            if row is not None:
                await s.delete(row)
                await s.flush()
            row = CalendarToken(tg_id=tg_id, token=secrets.token_urlsafe(24))
            s.add(row)
            await s.commit()
        return row.token


async def user_by_token(token: str) -> User | None:
    from sqlalchemy import select

    async with Session() as s:
        row = (await s.execute(select(CalendarToken).where(CalendarToken.token == token))).scalar_one_or_none()
        return await s.get(User, row.tg_id) if row else None


def feed_url(token: str) -> str | None:
    if not settings.public_url:
        return None
    return f"{settings.public_url.rstrip('/')}/cal/{token}.ics"


def subscribe_links(url: str, name: str) -> dict[str, str]:
    webcal = "webcal://" + url.split("://", 1)[1]
    return {
        "google": "https://calendar.google.com/calendar/r?cid=" + quote(webcal, safe=""),
        "outlook": "https://outlook.live.com/calendar/0/addfromweb?url="
        + quote(url, safe="")
        + "&name="
        + quote(name, safe=""),
    }


class CalendarFeeds:
    """Кэш готовых лент по группам: 3000 подписчиков одной группы — одна сборка."""

    def __init__(self, schedule: ScheduleService):
        self.schedule = schedule
        self._cache: dict[int, tuple[float, bytes]] = {}

    async def for_group(self, group_id: int) -> bytes:
        hit = self._cache.get(group_id)
        if hit and time.monotonic() - hit[0] < FEED_TTL:
            return hit[1]
        group = await get_group(group_id)
        weeks = await self.schedule.semester(group_id)
        data = build_ics(group.name, weeks)
        self._cache[group_id] = (time.monotonic(), data)
        return data
