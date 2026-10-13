"""Фоновые задачи: рассылки (п. 8), изменения (п. 9), напоминания и сводка (п. 51), обходы sut.ru."""

import logging
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from sqlalchemy import or_, select

from bot import metrics
from bot.broadcast import Broadcaster
from bot.config import TZ
from bot.db.base import Session
from bot.db.models import User
from bot.keyboards.main import day_nav, week_nav
from bot.render.text import render_day, render_diff, render_reminder, render_week
from bot.services.schedule import Diff, ScheduleService, monday_of, today
from bot.services.users import get_group, groups_count, save_groups

log = logging.getLogger(__name__)

QUIET_FROM, QUIET_TO = 23, 7  # тихие часы: уведомления без звука


def is_quiet_time(now: datetime | None = None) -> bool:
    h = (now or datetime.now(TZ)).hour
    return h >= QUIET_FROM or h < QUIET_TO


@dataclass(frozen=True)
class Recipient:
    tg_id: int
    quiet: bool  # включены тихие часы
    remind_minutes: int = 0


async def _recipients(*conditions) -> dict[int, list[Recipient]]:
    """Получатели по группам. Заблокировавшие бота и без группы — не в выборке."""
    async with Session() as s:
        q = select(User.group_id, User.tg_id, User.quiet_hours, User.remind_minutes).where(
            User.group_id.is_not(None), User.blocked.is_(False), *conditions
        )
        rows = (await s.execute(q)).all()
    res: dict[int, list[Recipient]] = defaultdict(list)
    for gid, tg, quiet, remind in rows:
        res[gid].append(Recipient(tg, quiet, remind))
    return res


class Jobs:
    def __init__(self, schedule: ScheduleService, broadcaster: Broadcaster, staff=None):
        self.schedule = schedule
        self.bc = broadcaster
        self.staff = staff
        self._staff_empty = False
        schedule.on_change = self.on_change

    async def _send(self, recipients: list[Recipient], text: str, **kwargs) -> None:
        quiet_now = is_quiet_time()
        for r in recipients:
            await self.bc.send(r.tg_id, text, disable_notification=quiet_now and r.quiet, **kwargs)

    # --- справочники ---

    async def refresh_groups(self) -> None:
        groups = await self.schedule.client.groups()
        await save_groups(groups)
        log.info("список групп обновлён: %d", len(groups))

    async def refresh_staff(self) -> None:
        if self.staff is not None:
            await self.staff.refresh_lists()

    async def crawl_all(self) -> None:
        """Обход всех групп на текущую и следующую неделю — для расписаний преподавателей и аудиторий."""
        from bot.services.users import all_group_ids

        monday = monday_of(today())
        ok = failed = 0
        for gid in await all_group_ids():
            for m in (monday, monday + timedelta(days=7)):
                try:
                    await self.schedule.week(gid, m, max_age=timedelta(hours=2), background=True)
                    ok += 1
                except Exception:
                    failed += 1
        log.info("обход групп завершён: %d недель, ошибок %d", ok, failed)

    # --- рассылки расписания ---

    async def send_tomorrow(self) -> None:
        day = today() + timedelta(days=1)
        if day.weekday() == 6:
            return
        for gid, users in (await _recipients(User.notify_tomorrow.is_(True))).items():
            group = await get_group(gid)
            try:
                week = await self.schedule.week(gid, day, max_age=timedelta(hours=2), background=True)
            except Exception:
                log.exception("рассылка на завтра: группа %s", gid)
                continue
            if not week.by_day(day):
                continue  # пар нет — не беспокоим
            text = "🌙 Расписание на завтра\n\n" + render_day(group.name, week, day)
            await self._send(users, text, reply_markup=day_nav(day))

    async def send_next_week(self) -> None:
        monday = monday_of(today()) + timedelta(days=7)
        for gid, users in (await _recipients(User.notify_week.is_(True))).items():
            group = await get_group(gid)
            try:
                week = await self.schedule.week(gid, monday, max_age=timedelta(hours=2), background=True)
            except Exception:
                log.exception("рассылка на неделю: группа %s", gid)
                continue
            text = "📬 Расписание на следующую неделю\n\n" + render_week(group.name, week)
            await self._send(users, text, reply_markup=week_nav(monday))

    async def send_morning(self) -> None:
        """Утренняя сводка (п. 51): расписание на сегодня, если есть пары."""
        day = today()
        if day.weekday() == 6:
            return
        for gid, users in (await _recipients(User.morning_digest.is_(True))).items():
            group = await get_group(gid)
            try:
                week = await self.schedule.week(gid, day, max_age=timedelta(hours=3), background=True)
            except Exception:
                log.exception("утренняя сводка: группа %s", gid)
                continue
            if week.by_day(day):
                text = "☀️ Доброе утро! Пары сегодня\n\n" + render_day(group.name, week, day)
                await self._send(users, text, reply_markup=day_nav(day))

    async def remind(self, now: datetime | None = None) -> None:
        """Напоминания перед парой (п. 51). Запускается раз в минуту."""
        now = (now or datetime.now(TZ)).replace(second=0, microsecond=0)
        if now.weekday() == 6:
            return
        groups = await _recipients(User.remind_minutes > 0)
        for gid, users in groups.items():
            try:
                # неделя почти всегда уже в памяти — проверка изменений обновляет её каждые 30 минут
                week = await self.schedule.week(gid, now.date(), max_age=timedelta(hours=1), background=True)
            except Exception:
                continue
            lessons = week.by_day(now.date())
            if not lessons:
                continue
            by_minutes: dict[int, list[Recipient]] = defaultdict(list)
            for r in users:
                by_minutes[r.remind_minutes].append(r)
            for minutes, rs in by_minutes.items():
                target = (now + timedelta(minutes=minutes)).strftime("%H:%M")
                starting = [l for l in lessons if l.start == target]
                if starting:
                    metrics.inc("напоминания: отправлено", len(rs))
                    await self._send(rs, render_reminder(starting, minutes))

    # --- изменения ---

    async def check_changes(self) -> None:
        """Обновляет текущую и следующую неделю групп, где есть пользователи; изменения уходят через on_change."""
        groups = await _recipients(
            or_(User.notify_changes.is_(True), User.notify_tomorrow.is_(True), User.remind_minutes > 0)
        )
        monday = monday_of(today())
        for gid in groups:
            for m in (monday, monday + timedelta(days=7)):
                try:
                    await self.schedule.week(gid, m, max_age=timedelta(minutes=20), background=True)
                except Exception:
                    log.warning("проверка изменений: группа %s неделя %s недоступна", gid, m)

    async def on_change(self, diff: Diff) -> None:
        group = await get_group(diff.group_id)
        users = (await _recipients(User.notify_changes.is_(True), User.group_id == diff.group_id)).get(
            diff.group_id, []
        )
        if users:
            await self._send(users, render_diff(group.name, diff))

    # --- запуск ---

    async def startup(self) -> None:
        if await groups_count() == 0:
            await self.refresh_groups()
        self._staff_empty = self.staff is not None and await self.staff.count() == 0
        if self.schedule.directory is not None:
            await self.schedule.directory.load()
            if n := await self.schedule.directory.rebuild_if_empty():
                log.info("индекс построен из %d сохранённых недель", n)

    def install(self) -> AsyncIOScheduler:
        sch = AsyncIOScheduler(timezone=TZ)
        opts = {"max_instances": 1, "coalesce": True, "misfire_grace_time": 600}

        def timed(name, fn):
            async def run():
                with metrics.timer(f"задача: {name}"):
                    await fn()

            return run

        def cron(**kw) -> CronTrigger:
            return CronTrigger(timezone=TZ, **kw)

        sch.add_job(timed("список групп", self.refresh_groups), cron(hour=4, minute=0), **opts)
        sch.add_job(timed("на завтра", self.send_tomorrow), cron(hour=20, minute=0), **opts)
        sch.add_job(timed("на неделю", self.send_next_week), cron(day_of_week="sun", hour=18, minute=0), **opts)
        sch.add_job(timed("утренняя сводка", self.send_morning), cron(hour=7, minute=30), **opts)
        # напоминания: пары начинаются с 9:00 до 18:30, напоминание максимум за 30 минут
        sch.add_job(
            timed("напоминания", self.remind),
            cron(hour="8-20", minute="*"),
            **{**opts, "misfire_grace_time": 30},
        )
        sch.add_job(
            timed("обход всех групп", self.crawl_all),
            cron(hour="6-21/3", minute=15),
            next_run_time=datetime.now(TZ) + timedelta(seconds=30),  # и сразу после запуска
            **opts,
        )
        sch.add_job(
            timed("профили преподавателей", self.refresh_staff),
            cron(day_of_week="mon", hour=5, minute=0),
            next_run_time=datetime.now(TZ) + timedelta(seconds=20) if self._staff_empty else None,
            **opts,
        )
        sch.add_job(timed("проверка изменений", self.check_changes), cron(hour="7-22", minute="*/30"), **opts)
        sch.start()
        return sch
