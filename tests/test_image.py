import io
from datetime import date
from pathlib import Path

from PIL import Image

from bot.render.image import counter_key, lesson_counters, render_day_image
from bot.services.sut_public.parser import parse_week

FIX = Path(__file__).parent / "fixtures"
WEEK = parse_week((FIX / "group_week.html").read_text(encoding="utf-8"), 56882, date(2026, 10, 13))


def test_counters_collapse_subgroups():
    c = lesson_counters(WEEK.lessons)
    eng = sorted(v for k, v in c.items() if k[2] == "Иностранный язык")
    assert eng == [(1, 3), (2, 3), (3, 3)]  # три подгруппы в одно время — одно занятие


def test_render_day_image():
    day = date(2026, 10, 14)
    lessons = WEEK.by_day(day)
    png = render_day_image("ИСТ-2633", day, lessons, "нечётная неделя (7)", lesson_counters(WEEK.lessons))
    img = Image.open(io.BytesIO(png))
    assert img.format == "PNG" and img.width == 1080 and img.height > 1000
    assert counter_key(lessons[0])[3] == "Практика"


def test_render_empty_day():
    png = render_day_image("ИСТ-2633", date(2026, 10, 15), [])
    assert Image.open(io.BytesIO(png)).height < 600


def test_changes_pdf():
    from dataclasses import replace

    from bot.render.image import render_changes_pdf

    old = WEEK.by_day(date(2026, 10, 13))[2]
    new = replace(old, room="501", start="14:45")
    pdf = render_changes_pdf("ИСТ-2633", [new], [old])
    assert pdf.startswith(b"%PDF")
