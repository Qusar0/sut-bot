"""Фоновые задачи: рассылки расписания (п. 8), поиск изменений (п. 9), обновление списка групп."""
import logging
from collections import defaultdict
from datetime import timedelta

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from sqlalchemy import or_, select

from bot.broadcast import Broadcaster
from bot.config import TZ
from bot.db.base import Session
from bot.db.models import User
from bot.keyboards.main import day_nav, week_nav
from bot.render.text import render_day, render_diff, render_week
from bot.services.schedule import Diff, ScheduleService, monday_of, today
from bot.services.users import get_group, groups_count, save_groups

log = logging.getLogger(__name__)


async def _users_by_group(*conditions) -> dict[int, list[int]]:
    async with Session() as s:
        q = select(User.group_id, User.tg_id).where(User.group_id.is_not(None), User.blocked.is_(False), *conditions)
        rows = (await s.execute(q)).all()
    res: dict[int, list[int]] = defaultdict(list)
    for gid, tg in rows:
        res[gid].append(tg)
    return res


class Jobs:
    def __init__(self, schedule: ScheduleService, broadcaster: Broadcaster):
        self.schedule = schedule
        self.bc = broadcaster
        schedule.on_change = self.on_change

    async def refresh_groups(self) -> None:
        groups = await self.schedule.client.groups()
        await save_groups(groups)
        log.info("список групп обновлён: %d", len(groups))

    async def send_tomorrow(self) -> None:
        day = today() + timedelta(days=1)
        if day.weekday() == 6:
            return
        for gid, users in (await _users_by_group(User.notify_tomorrow.is_(True))).items():
            group = await get_group(gid)
            try:
                week = await self.schedule.week(gid, day, max_age=timedelta(hours=2))
            except Exception:
                log.exception("рассылка на завтра: группа %s", gid)
                continue
            if not week.by_day(day):
                continue  # пар нет — не беспокоим
            text = "🌙 Расписание на завтра\n\n" + render_day(group.name, week, day)
            await self.bc.send_many(users, text, reply_markup=day_nav(day))

    async def send_next_week(self) -> None:
        monday = monday_of(today()) + timedelta(days=7)
        for gid, users in (await _users_by_group(User.notify_week.is_(True))).items():
            group = await get_group(gid)
            try:
                week = await self.schedule.week(gid, monday, max_age=timedelta(hours=2))
            except Exception:
                log.exception("рассылка на неделю: группа %s", gid)
                continue
            text = "📬 Расписание на следующую неделю\n\n" + render_week(group.name, week)
            await self.bc.send_many(users, text, reply_markup=week_nav(monday))

    async def check_changes(self) -> None:
        """Обновляет текущую и следующую неделю всех групп, где есть пользователи; изменения уходят через on_change."""
        groups = await _users_by_group(or_(User.notify_changes.is_(True), User.notify_tomorrow.is_(True)))
        monday = monday_of(today())
        for gid in groups:
            for m in (monday, monday + timedelta(days=7)):
                try:
                    await self.schedule.week(gid, m, max_age=timedelta(minutes=20))
                except Exception:
                    log.warning("проверка изменений: группа %s неделя %s недоступна", gid, m)

    async def on_change(self, diff: Diff) -> None:
        group = await get_group(diff.group_id)
        users = (await _users_by_group(User.notify_changes.is_(True), User.group_id == diff.group_id)).get(diff.group_id, [])
        if users:
            await self.bc.send_many(users, render_diff(group.name, diff))

    async def startup(self) -> None:
        if await groups_count() == 0:
            await self.refresh_groups()

    def install(self) -> AsyncIOScheduler:
        sch = AsyncIOScheduler(timezone=TZ)
        opts = {"max_instances": 1, "coalesce": True, "misfire_grace_time": 600}
        sch.add_job(self.refresh_groups, CronTrigger(hour=4, minute=0, timezone=TZ), **opts)
        sch.add_job(self.send_tomorrow, CronTrigger(hour=20, minute=0, timezone=TZ), **opts)
        sch.add_job(self.send_next_week, CronTrigger(day_of_week="sun", hour=18, minute=0, timezone=TZ), **opts)
        sch.add_job(self.check_changes, CronTrigger(hour="7-22", minute="*/30", timezone=TZ), **opts)
        sch.start()
        return sch
