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

from bot import metrics
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
        # Горячий кэш в памяти: (группа, понедельник) -> (неделя, когда получена). Без похода в БД.
        self._mem: dict[tuple[int, date], tuple[Week, datetime]] = {}
        self._tasks: set[asyncio.Task] = set()

    async def week(self, group_id: int, day: date, max_age: timedelta | None = None, background: bool = False) -> Week:
        monday = monday_of(day)
        key = (group_id, monday)
        max_age = max_age if max_age is not None else timedelta(minutes=settings.schedule_cache_minutes)
        now = datetime.now(TZ)

        if (hit := self._mem.get(key)) and now - hit[1] < max_age:
            metrics.inc("кэш: память")
            return hit[0]

        async with Session() as s:
            snap = await s.get(WeekSnapshot, (group_id, monday))
        if snap and now - snap.fetched_at.astimezone(TZ) < max_age:
            metrics.inc("кэш: БД")
            week = _week_from_snapshot(snap)
            self._mem[key] = (week, snap.fetched_at.astimezone(TZ))
            return week

        if key in self._inflight:
            metrics.inc("кэш: склеенный запрос")
            return await asyncio.shield(self._inflight[key])
        metrics.inc("кэш: промах")
        fut = asyncio.get_running_loop().create_future()
        self._inflight[key] = fut
        try:
            try:
                week = await self._refresh(group_id, monday, background)
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

    async def _refresh(self, group_id: int, monday: date, background: bool = False) -> Week:
        week = await self.client.week(group_id, monday, background=background)
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
        self._mem[(group_id, monday)] = (week, snap.fetched_at)
        # Об изменениях прошлых недель не сообщаем. Рассылку запускаем фоном, чтобы не задерживать ответ.
        if diff and self.on_change and monday >= monday_of(today()):
            metrics.inc("изменения найдены")
            task = asyncio.create_task(self._notify(diff))
            self._tasks.add(task)
            task.add_done_callback(self._tasks.discard)
        return week

    async def _notify(self, diff: Diff) -> None:
        try:
            await self.on_change(diff)
        except Exception:
            log.exception("ошибка рассылки изменений")

    async def weeks_between(self, group_id: int, start: date, end: date) -> list[Week]:
        """Недели, покрывающие интервал; загружаются параллельно."""
        mondays = []
        m = monday_of(start)
        while m <= end:
            mondays.append(m)
            m += timedelta(days=7)
        return list(await asyncio.gather(*(self.week(group_id, m) for m in mondays)))


def _week_from_snapshot(snap: WeekSnapshot) -> Week:
    return Week(
        group_id=snap.group_id,
        monday=snap.monday,
        number=snap.number,
        parity=snap.parity,
        lessons=[Lesson.from_dict(d) for d in snap.lessons],
    )
