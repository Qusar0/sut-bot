"""Календарь (п. 32): секретные ссылки на подписку, настройки конструктора и сборка ленты .ics."""

import secrets
import time
from dataclasses import dataclass
from urllib.parse import quote

from sqlalchemy import select

from bot.config import settings
from bot.db.base import Session
from bot.db.models import CalendarToken, User
from bot.render.ics import build_ics
from bot.services.schedule import ScheduleService
from bot.services.users import get_group

FEED_TTL = 1800  # секунд: одинаковая лента пересобирается не чаще раза в 30 минут
ALARM_STEPS = [0, 10, 15, 30, 60]  # напоминание в календаре, по кругу


@dataclass(frozen=True)
class CalendarPrefs:
    kinds_mask: int = 7
    hidden_subjects: tuple[str, ...] = ()
    alarm_minutes: int = 0


def _prefs(row: CalendarToken) -> CalendarPrefs:
    return CalendarPrefs(row.kinds_mask, tuple(sorted(row.hidden_subjects or [])), row.alarm_minutes)


async def _row(s, tg_id: int) -> CalendarToken:
    row = await s.get(CalendarToken, tg_id)
    if row is None:
        row = CalendarToken(
            tg_id=tg_id, token=secrets.token_urlsafe(24), kinds_mask=7, hidden_subjects=[], alarm_minutes=0
        )
        s.add(row)
        await s.flush()
    return row


async def get_token(tg_id: int, reset: bool = False) -> str:
    async with Session() as s:
        row = await _row(s, tg_id)
        if reset:  # меняем только токен: настройки конструктора сохраняются
            row.token = secrets.token_urlsafe(24)
        await s.commit()
        return row.token


async def get_prefs(tg_id: int) -> CalendarPrefs:
    async with Session() as s:
        row = await _row(s, tg_id)
        await s.commit()
        return _prefs(row)


async def update_prefs(tg_id: int, **fields) -> CalendarPrefs:
    async with Session() as s:
        row = await _row(s, tg_id)
        for k, v in fields.items():
            setattr(row, k, list(v) if k == "hidden_subjects" else v)
        await s.commit()
        return _prefs(row)


async def user_by_token(token: str) -> tuple[User, CalendarPrefs] | None:
    async with Session() as s:
        row = (await s.execute(select(CalendarToken).where(CalendarToken.token == token))).scalar_one_or_none()
        if row is None:
            return None
        user = await s.get(User, row.tg_id)
        return (user, _prefs(row)) if user else None


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
    """Кэш готовых лент: подписчики одной группы с одинаковыми настройками — одна сборка."""

    def __init__(self, schedule: ScheduleService):
        self.schedule = schedule
        self._cache: dict[tuple, tuple[float, bytes]] = {}

    async def for_group(self, group_id: int, prefs: CalendarPrefs | None = None) -> bytes:
        prefs = prefs or CalendarPrefs()
        key = (group_id, prefs)
        hit = self._cache.get(key)
        if hit and time.monotonic() - hit[0] < FEED_TTL:
            return hit[1]
        group = await get_group(group_id)
        weeks = await self.schedule.semester(group_id)
        data = build_ics(group.name, weeks, prefs.kinds_mask, prefs.hidden_subjects, prefs.alarm_minutes)
        if len(self._cache) > 5000:
            self._cache.clear()
        self._cache[key] = (time.monotonic(), data)
        return data
