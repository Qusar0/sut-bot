from dataclasses import replace
from datetime import date
from pathlib import Path

from bot.keyboards.main import month_calendar
from bot.render.text import MAX_LEN, render_day, render_diff, render_period, render_week, room_short
from bot.services.schedule import diff_lessons
from bot.services.sut_public.models import Lesson
from bot.services.sut_public.parser import parse_week

FIX = Path(__file__).parent / "fixtures"
WEEK = parse_week((FIX / "group_week.html").read_text(encoding="utf-8"), 56882, date(2026, 10, 13))


def test_day():
    text = render_day("ИСТ-2633", WEEK, date(2026, 10, 13))
    assert "Вторник, 13 октября" in text
    assert "нечётная неделя (7)" in text
    assert "История России" in text and "ауд. 533/2" in text


def test_empty_day():
    assert "Пар нет" in render_day("ИСТ-2633", WEEK, date(2026, 10, 15))


def test_week_and_period_fit_limit():
    assert len(render_week("ИСТ-2633", WEEK)) < MAX_LEN
    parts = render_period("ИСТ-2633", [WEEK] * 5, date(2026, 10, 12), date(2026, 11, 11))
    assert all(len(p) <= MAX_LEN for p in parts)
    assert "Неделя 7 · нечётная" in parts[0]


def test_room_short():
    pe = next(l for l in WEEK.lessons if l.pair == "ФЗ")
    assert room_short(WEEK.lessons[0]) == "303/2"
    assert room_short(pe) == "Динамит · Ч13В"


def test_month_calendar():
    kb = month_calendar(date(2026, 10, 13), date(2026, 11, 12), {date(2026, 10, 13)})
    flat = [b for row in kb.inline_keyboard for b in row]
    assert any(b.callback_data == "dn:2026-10-13" and b.text == "13" for b in flat)
    assert all(len(row) == 6 for row in kb.inline_keyboard)


def test_lesson_roundtrip():
    l = WEEK.lessons[0]
    assert Lesson.from_dict(l.to_dict()) == l


def test_diff():
    old = WEEK.lessons
    moved = replace(old[0], room="999")
    new = [moved] + old[1:]
    d = diff_lessons(56882, WEEK.monday, old, new)
    assert d and d.added == [moved] and d.removed == [old[0]]
    text = render_diff("ИСТ-2633", d)
    assert "➕" in text and "➖" in text and "999" in text
    assert diff_lessons(56882, WEEK.monday, old, list(old)) is None


def test_diff_ignores_invisible_changes():
    """Пара отменена и добавлена с тем же видимым содержимым — это не изменение."""
    from dataclasses import replace

    old = WEEK.lessons
    # меняем только полное ФИО, «Кокорин М.С.» и всё остальное — то же
    same_view = replace(old[0], teachers=("Кокорин Михаил Станиславович (и.о.)",))
    assert diff_lessons(56882, WEEK.monday, old, [same_view] + old[1:]) is None


def test_diff_real_change_still_reported():
    from dataclasses import replace

    old = WEEK.lessons
    moved = replace(old[0], room="999", teachers_short="Иванов И.И.", teachers=("Иванов Иван Иванович",))
    d = diff_lessons(56882, WEEK.monday, old, [moved] + old[1:])
    assert d and d.added == [moved] and d.removed == [old[0]]
