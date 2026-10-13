from datetime import date, datetime
from pathlib import Path

from bot.config import TZ
from bot.render.text import render_reminder
from bot.scheduler.jobs import Jobs, is_quiet_time, reminder_lead
from bot.services.sut_public.models import Group
from bot.services.sut_public.parser import parse_week

FIX = Path(__file__).parent / "fixtures"
WEEK = parse_week((FIX / "group_week.html").read_text(encoding="utf-8"), 56882, date(2026, 10, 13))


class FakeSchedule:
    directory = None
    on_change = None

    async def week(self, group_id, day, max_age=None, background=False):
        return WEEK


class FakeBroadcaster:
    def __init__(self):
        self.sent: list[tuple[int, str, dict]] = []

    async def send(self, chat_id, text, **kw):
        self.sent.append((chat_id, text, kw))
        return True


def test_quiet_time():
    assert is_quiet_time(datetime(2026, 10, 13, 23, 30, tzinfo=TZ))
    assert is_quiet_time(datetime(2026, 10, 13, 6, 59, tzinfo=TZ))
    assert not is_quiet_time(datetime(2026, 10, 13, 12, 0, tzinfo=TZ))


def test_render_reminder():
    eng = [l for l in WEEK.by_day(date(2026, 10, 14)) if l.start == "14:45"]
    text = render_reminder(eng, 10)
    assert "Через 10 мин" in text and text.count("Иностранный язык") == 3
    assert "начало в 14:45" in render_reminder(eng, None)


async def test_remind():
    from bot.db.base import init_db
    from bot.services.users import get_or_create_user, save_groups, set_user_fields

    await init_db()
    await save_groups([Group(56882, "ИСТ-2633", "ИТПИ")])
    for tg, minutes in ((1001, 15), (1002, 0), (1003, 30)):
        await get_or_create_user(tg)
        await set_user_fields(tg, group_id=56882, remind_minutes=minutes)

    bc = FakeBroadcaster()
    jobs = Jobs(FakeSchedule(), bc)
    # вторник 13.10, первая пара в 13:00: в 12:45 напоминание тем, кто выбрал 15 минут
    await jobs.remind(datetime(2026, 10, 13, 12, 45, tzinfo=TZ), wait=True)
    assert [c for c, _, _ in bc.sent] == [1001]
    assert "История России" in bc.sent[0][1] and bc.sent[0][2]["disable_notification"] is False
    bc.sent.clear()
    await jobs.remind(datetime(2026, 10, 13, 12, 30, tzinfo=TZ), wait=True)
    assert [c for c, _, _ in bc.sent] == [1003]
    bc.sent.clear()
    await jobs.remind(datetime(2026, 10, 13, 12, 46, tzinfo=TZ), wait=True)
    assert bc.sent == []


def test_reminder_lead():
    assert reminder_lead(100) == 0  # успеваем за минуту
    assert reminder_lead(1500, rate=25) == 0
    assert reminder_lead(1501, rate=25) == 1
    assert reminder_lead(10_000, rate=25) == 6  # 10 000 сообщений идут ~7 минут — начинаем на 6 минут раньше
