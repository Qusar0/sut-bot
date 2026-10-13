from datetime import date
from pathlib import Path

from icalendar import Calendar

from bot.render.ics import build_ics
from bot.services.calendar import get_token, subscribe_links
from bot.services.sut_public.parser import parse_week

FIX = Path(__file__).parent / "fixtures"
WEEK = parse_week((FIX / "group_week.html").read_text(encoding="utf-8"), 56882, date(2026, 10, 13))


def test_build_ics():
    cal = Calendar.from_ical(build_ics("ИСТ-2633", [WEEK]))
    events = [c for c in cal.walk("VEVENT")]
    assert len(events) == len(WEEK.lessons)
    first = min(events, key=lambda e: e.decoded("dtstart"))
    assert str(first["summary"]) == "Начертательная геометрия (лабораторная)"
    assert str(first["location"]) == "ауд. 303/2"
    assert first.decoded("dtstart").isoformat() == "2026-10-12T09:00:00+03:00"
    assert len({str(e["uid"]) for e in events}) == len(events)  # UID уникальны и стабильны


def test_subscribe_links():
    links = subscribe_links("https://bot.example.ru/cal/abc.ics", "Расписание ИСТ-2633")
    assert links["google"].startswith("https://calendar.google.com/calendar/r?cid=webcal%3A%2F%2Fbot.example.ru")
    assert "addfromweb?url=https%3A%2F%2Fbot.example.ru" in links["outlook"]


async def test_token_reset():
    from bot.db.base import init_db
    from bot.services.users import get_or_create_user

    await init_db()
    await get_or_create_user(777)
    t1 = await get_token(777)
    assert await get_token(777) == t1
    t2 = await get_token(777, reset=True)
    assert t2 != t1 and len(t2) >= 30


def test_ics_filters_and_alarm():
    data = build_ics("ИСТ-2633", [WEEK], kinds_mask=1, hidden_subjects=["Информатика"], alarm_minutes=15)
    events = list(Calendar.from_ical(data).walk("VEVENT"))
    kinds = {str(e["summary"]).rsplit("(", 1)[1] for e in events}
    assert kinds == {"лекция)"}  # только лекции
    assert not any(str(e["summary"]).startswith("Информатика") for e in events)
    alarms = list(events[0].walk("VALARM"))
    assert alarms and alarms[0].decoded("trigger").total_seconds() == -15 * 60


async def test_prefs_survive_reset():
    from bot.services.calendar import get_prefs, update_prefs

    await update_prefs(777, kinds_mask=3, alarm_minutes=30, hidden_subjects=["Физическая культура и спорт"])
    await get_token(777, reset=True)
    p = await get_prefs(777)
    assert (p.kinds_mask, p.alarm_minutes, p.hidden_subjects) == (3, 30, ("Физическая культура и спорт",))
