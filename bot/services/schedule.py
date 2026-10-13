"""Кэш расписания поверх sut.ru и поиск изменений.

Одна неделя группы запрашивается с сайта не чаще раза в `schedule_cache_minutes`,
а параллельные запросы одной и той же недели склеиваются в один (важно при тысячах пользователей).
"""

import asyncio
import hashlib
import json
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import date, datetime, timedelta

from sqlalchemy import select

from bot.config import TZ, settings
from bot.db.base import Session
from bot.db.models import WeekSnapshot
from bot.services.sut_public.client import SutPublicClient
from bot.services.sut_public.models import Lesson, Week

log = logging.getLogger(__name__)


def monday_of(d: date) -> date:
    return d - timedelta(days=d.weekday())


def today() -> date:
    return datetime.now(TZ).date()


@dataclass
class Diff:
    group_id: int
    monday: date
    added: list[Lesson]
    removed: list[Lesson]

    @property
    def days(self) -> list[date]:
        return sorted({l.day for l in self.added + self.removed})


def _digest(lessons: list[Lesson]) -> str:
    keys = sorted(json.dumps(l.key(), ensure_ascii=False) for l in lessons)
    return hashlib.sha256("\n".join(keys).encode()).hexdigest()


def diff_lessons(group_id: int, monday: date, old: list[Lesson], new: list[Lesson]) -> Diff | None:
    old_k = {l.key(): l for l in old}
    new_k = {l.key(): l for l in new}
    added = [new_k[k] for k in new_k.keys() - old_k.keys()]
    removed = [old_k[k] for k in old_k.keys() - new_k.keys()]
    if not added and not removed:
        return None
    return Diff(
        group_id, monday, sorted(added, key=lambda l: (l.day, l.start)), sorted(removed, key=lambda l: (l.day, l.start))
    )


ChangeHandler = Callable[[Diff], Awaitable[None]]


class ScheduleService:
    def __init__(self, client: SutPublicClient):
        self.client = client
        self.on_change: ChangeHandler | None = None
        self._inflight: dict[tuple[int, date], asyncio.Future] = {}

    async def week(self, group_id: int, day: date, max_age: timedelta | None = None) -> Week:
        monday = monday_of(day)
        max_age = max_age if max_age is not None else timedelta(minutes=settings.schedule_cache_minutes)

        async with Session() as s:
            snap = await s.get(WeekSnapshot, (group_id, monday))
        if snap and datetime.now(TZ) - snap.fetched_at.astimezone(TZ) < max_age:
            return _week_from_snapshot(snap)

        key = (group_id, monday)
        if key in self._inflight:
            return await asyncio.shield(self._inflight[key])
        fut = asyncio.get_running_loop().create_future()
        self._inflight[key] = fut
        try:
            try:
                week = await self._refresh(group_id, monday)
            except Exception as e:
                if not snap:
                    raise
                log.warning("sut.ru недоступен, отдаю кэш %s %s: %s", group_id, monday, e)
                week = _week_from_snapshot(snap)
            fut.set_result(week)
            return week
        except asyncio.CancelledError:
            fut.cancel()
            raise
        except Exception as e:
            fut.set_exception(e)
            fut.exception()  # чтобы asyncio не ругался, если никто не ждал
            raise
        finally:
            self._inflight.pop(key, None)

    async def _refresh(self, group_id: int, monday: date) -> Week:
        week = await self.client.week(group_id, monday)
        digest = _digest(week.lessons)
        diff = None
        async with Session() as s:
            snap = await s.get(WeekSnapshot, (group_id, monday))
            if snap is None:
                snap = WeekSnapshot(group_id=group_id, monday=monday)
                s.add(snap)
            elif snap.digest != digest:
                old = [Lesson.from_dict(d) for d in snap.lessons]
                diff = diff_lessons(group_id, monday, old, week.lessons)
            snap.number, snap.parity = week.number, week.parity
            snap.lessons = [l.to_dict() for l in week.lessons]
            snap.digest = digest
            snap.fetched_at = datetime.now(TZ)
            await s.commit()
        # Об изменениях прошлых недель не сообщаем
        if diff and self.on_change and monday >= monday_of(today()):
            try:
                await self.on_change(diff)
            except Exception:
                log.exception("ошибка рассылки изменений")
        return week

    async def lessons_between(self, group_id: int, start: date, end: date) -> list[Lesson]:
        """Все занятия группы в интервале дат включительно."""
        result: list[Lesson] = []
        monday = monday_of(start)
        while monday <= end:
            w = await self.week(group_id, monday)
            result += [l for l in w.lessons if start <= l.day <= end]
            monday += timedelta(days=7)
        return result

    async def cached_groups_with_snapshots(self) -> list[int]:
        async with Session() as s:
            rows = await s.execute(select(WeekSnapshot.group_id).distinct())
            return [r[0] for r in rows]


def _week_from_snapshot(snap: WeekSnapshot) -> Week:
    return Week(
        group_id=snap.group_id,
        monday=snap.monday,
        number=snap.number,
        parity=snap.parity,
        lessons=[Lesson.from_dict(d) for d in snap.lessons],
    )
