from datetime import date
from pathlib import Path

from bot.services.sut_public.parser import parse_groups, parse_week

FIX = Path(__file__).parent / "fixtures"


def test_parse_groups():
    groups = parse_groups((FIX / "groups_index.html").read_text(encoding="utf-8"))
    assert len(groups) > 300
    ist = next(g for g in groups if g.name == "ИСТ-2633")
    assert ist.id == 56882
    assert ist.faculty


def test_parse_week():
    week = parse_week((FIX / "group_week.html").read_text(encoding="utf-8"), 56882, date(2026, 10, 13))
    assert week.monday == date(2026, 10, 12)
    assert week.number == 7 and week.parity == "Нечётная"
    assert len(week.lessons) == 21

    monday = week.by_day(date(2026, 10, 12))
    first = monday[0]
    assert (first.pair, first.start, first.end) == ("1", "09:00", "10:35")
    assert first.subject == "Начертательная геометрия"
    assert first.kind == "Лабораторная работа"
    assert (first.room, first.building) == ("303", "Б22/2")
    assert first.teachers == ("Кокорин Михаил Станиславович",)

    pe = [l for l in week.lessons if l.pair == "ФЗ"]
    assert pe and pe[0].room == "Динамит" and len(pe[0].teachers) == 3
