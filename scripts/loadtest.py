"""Нагрузочный тест бота без Telegram и без настоящего sut.ru.

    DATABASE_URL=postgresql+asyncpg://... python -m scripts.loadtest --users 10000

Что меряем:
  1. Пик: N пользователей за `--window` секунд жмут «Сегодня» — путь обработчика
     (пользователь → группа → неделя из кэша/сайта → текст ответа).
  2. Задача напоминаний при N пользователях с включённым напоминанием.
  3. Оценка времени массовой рассылки с лимитом Telegram.
sut.ru подменён заглушкой с задержкой `--upstream-ms`, чтобы не нагружать сайт вуза.
"""

import argparse
import asyncio
import random
import statistics
import time
from datetime import date, datetime
from pathlib import Path

from bot import metrics
from bot.broadcast import RATE
from bot.config import TZ
from bot.db.base import Session, init_db
from bot.db.models import User
from bot.render.text import render_day
from bot.scheduler.jobs import Jobs
from bot.services.schedule import ScheduleService
from bot.services.sut_public.models import Group
from bot.services.sut_public.parser import parse_week
from bot.services.users import get_group, get_user, save_groups

FIXTURE = Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "group_week.html"
GROUPS = 408


class FakeSutClient:
    """Отдаёт одну и ту же реальную неделю с искусственной задержкой сайта."""

    def __init__(self, delay: float):
        self.delay = delay
        self.requests = 0
        self.html = FIXTURE.read_text(encoding="utf-8")

    async def week(self, group_id: int, any_day: date, background: bool = False):
        self.requests += 1
        await asyncio.sleep(self.delay)
        return parse_week(self.html, group_id, any_day)


class NullBroadcaster:
    def __init__(self):
        self.sent = 0

    async def send(self, chat_id, text, **kw):
        self.sent += 1
        return True


def pct(values: list[float], p: float) -> float:
    values = sorted(values)
    return values[min(len(values) - 1, int(p * (len(values) - 1)))] * 1000


async def seed(n: int) -> None:
    await init_db()
    await save_groups([Group(100000 + g, f"ГР-{g:04d}", "TEST") for g in range(GROUPS)])
    async with Session() as s:
        exists = {u for (u,) in (await s.execute(User.__table__.select().with_only_columns(User.tg_id))).all()}
        for i in range(n):
            tg = 10_000_000 + i
            if tg not in exists:
                s.add(User(tg_id=tg, group_id=100000 + i % GROUPS, remind_minutes=15))
        await s.commit()


async def handle_today(tg_id: int, schedule: ScheduleService, day: date) -> float:
    t0 = time.perf_counter()
    user = await get_user(tg_id)
    group = await get_group(user.group_id)
    week = await schedule.week(group.id, day)
    render_day(group.name, week, day)
    return time.perf_counter() - t0


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--users", type=int, default=10_000)
    ap.add_argument("--window", type=float, default=60.0, help="за сколько секунд все пользователи жмут кнопку")
    ap.add_argument("--upstream-ms", type=float, default=300.0)
    args = ap.parse_args()

    print(f"Готовлю {args.users} пользователей в {GROUPS} группах…")
    await seed(args.users)
    client = FakeSutClient(args.upstream_ms / 1000)
    schedule = ScheduleService(client)  # type: ignore[arg-type]
    day = date(2026, 10, 13)

    # 1. пик нажатий
    ids = [10_000_000 + i for i in range(args.users)]
    random.shuffle(ids)
    latencies: list[float] = []
    errors = 0
    t_start = time.perf_counter()

    async def one(i: int, tg: int) -> None:
        nonlocal errors
        await asyncio.sleep(args.window * i / len(ids))
        try:
            latencies.append(await handle_today(tg, schedule, day))
        except Exception:
            errors += 1

    await asyncio.gather(*(one(i, tg) for i, tg in enumerate(ids)))
    elapsed = time.perf_counter() - t_start
    print("\n1. Пик «Сегодня»")
    print(f"   запросов: {len(latencies)} за {elapsed:.1f} с ({len(latencies) / elapsed:.0f}/с), ошибок: {errors}")
    print(
        f"   время ответа: p50 {pct(latencies, 0.5):.0f} мс · p95 {pct(latencies, 0.95):.0f} мс · "
        f"p99 {pct(latencies, 0.99):.0f} мс · max {max(latencies) * 1000:.0f} мс"
    )
    print(f"   запросов к sut.ru: {client.requests} (на {GROUPS} групп)")
    print(f"   кэш: {dict((k, v) for k, v in metrics.counters.items() if k.startswith('кэш'))}")

    # 2. задача напоминаний
    bc = NullBroadcaster()
    jobs = Jobs(schedule, bc)  # type: ignore[arg-type]
    t0 = time.perf_counter()
    # из-за опережения (lead) напоминания к паре в 13:00 при большом числе получателей стартуют раньше
    for minute in range(25, 46):
        await jobs.remind(datetime(2026, 10, 13, 12, minute, tzinfo=TZ), wait=True)
        if bc.sent:
            break
    print(f"\n2. Напоминания (все за 15 мин, пара в 13:00): рассылка стартует в 12:{minute:02d}")
    print(f"   расчёт и постановка в очередь: {(time.perf_counter() - t0) * 1000:.0f} мс, сообщений: {bc.sent}")
    print(f"   доставка при лимите Telegram {RATE}/с: ~{bc.sent / RATE / 60:.1f} мин")

    # 3. массовая рассылка
    print("\n3. Вечерняя рассылка «на завтра»")
    print(f"   {args.users} сообщений при {RATE}/с: ~{args.users / RATE / 60:.1f} мин")
    print(
        f"   p95 для «Сегодня» в норме, если < 300 мс. Медленных ответов (>1 с): {sum(1 for x in latencies if x > 1)}"
    )
    if latencies:
        print(f"   среднее: {statistics.mean(latencies) * 1000:.0f} мс")


if __name__ == "__main__":
    asyncio.run(main())
