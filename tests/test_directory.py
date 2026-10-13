from datetime import date, datetime
from pathlib import Path

from bot.config import TZ
from bot.db.base import init_db
from bot.render.directory import render_slots_day, render_subject, subject_list, subject_stats, teacher_tail
from bot.services.directory import Directory, short_name
from bot.services.sut_public.models import Group
from bot.services.sut_public.parser import parse_week
from bot.services.users import save_groups

FIX = Path(__file__).parent / "fixtures"
WEEK = parse_week((FIX / "group_week.html").read_text(encoding="utf-8"), 56882, date(2026, 10, 13))


def test_short_name():
    assert short_name("Кокорин Михаил Станиславович") == "Кокорин М.С."
    assert short_name("Климов Алексей") == "Климов А."


async def test_directory_index():
    await init_db()
    await save_groups([Group(56882, "ИСТ-2633", "ИТПИ")])
    d = Directory()
    await d.update(56882, WEEK.monday, WEEK.lessons)
    await d.update(56882, WEEK.monday, WEEK.lessons)  # повторная запись не плодит дубли

    [t] = d.search_teachers("кокорин м")
    assert t.full_name == "Кокорин Михаил Станиславович"
    assert d.search_teachers("кокорин м с")  # инициалы через пробел
    slots = await d.teacher_slots(t.id, date(2026, 10, 12), date(2026, 10, 17))
    assert [(s.day.day, s.start) for s in slots] == [(12, "09:00"), (16, "09:00"), (16, "10:45")]
    assert slots[0].groups == ["ИСТ-2633"]
    assert "ИСТ-2633" in render_slots_day("👩‍🏫 " + t.full_name, slots, date(2026, 10, 12), teacher_tail)

    rooms = d.search_rooms("303")
    assert rooms and rooms[0].room == "303"
    assert d.search_rooms("303/2")[0].building == "Б22/2"
    r_slots = await d.room_slots(rooms[0].id, date(2026, 10, 12), date(2026, 10, 17))
    assert all(s.room == "303/2" for s in r_slots)

    # новый экземпляр поднимает справочник из базы
    d2 = Directory()
    await d2.load()
    assert d2.search_teachers("кокорин")


def test_subjects():
    names = subject_list([WEEK])
    assert "Иностранный язык" in names and "Иностранный язык (2)" not in names
    now = datetime(2026, 10, 14, 15, 0, tzinfo=TZ)
    st = subject_stats([WEEK], "Иностранный язык", now)
    # подгруппы схлопнуты: Пн 10:45, Ср 14:45, Ср 16:30
    assert len(st.lessons) == 3 and st.passed == 1
    assert st.by_kind == {"Практика": (1, 3)}
    text = render_subject("ИСТ-2633", [WEEK], st, {"Практика"}, now)
    assert "Неделя 7" in text and "Всего занятий: 3" in text
    assert "Нет занятий" in render_subject("ИСТ-2633", [WEEK], st, {"Лекция"}, now)
