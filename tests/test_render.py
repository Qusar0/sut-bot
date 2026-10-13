from dataclasses import replace
from datetime import date
from pathlib import Path

from bot.render.text import MAX_LEN, render_day, render_diff, render_period, render_week
from bot.services.schedule import diff_lessons
from bot.services.sut_public.models import Lesson
from bot.services.sut_public.parser import parse_week

FIX = Path(__file__).parent / "fixtures"
WEEK = parse_week((FIX / "group_week.html").read_text(encoding="utf-8"), 56882, date(2026, 10, 13))


def test_day():
    text = render_day("ИСТ-2633", WEEK, date(2026, 10, 13))
    assert "Вторник, 13 октября" in text
    assert "Нечётная неделя (7)" in text
    assert "История России" in text and "ауд. 533 (Б22/2)" in text


def test_empty_day():
    assert "Пар нет" in render_day("ИСТ-2633", WEEK, date(2026, 10, 15))


def test_week_and_period_fit_limit():
    assert len(render_week("ИСТ-2633", WEEK)) < MAX_LEN
    parts = render_period("ИСТ-2633", WEEK.lessons * 5, date(2026, 10, 12), date(2026, 11, 11))
    assert all(len(p) <= MAX_LEN for p in parts)


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
