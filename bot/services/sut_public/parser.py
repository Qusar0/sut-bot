"""Парсинг HTML открытого расписания sut.ru. Разметка описана в docs/recon.md."""
import re
from datetime import date, timedelta

from selectolax.lexbor import LexborHTMLParser

from .models import Group, Lesson, Week

_TIME_RE = re.compile(r"\d{2}:\d{2}")
_WEEK_RE = re.compile(r"(Чётная|Нечётная|Четная|Нечетная)\s+неделя\s*\((\d+)\)", re.I)


class ParseError(Exception):
    pass


def _text(node) -> str:
    return node.text(strip=True) if node is not None else ""


def parse_groups(html: str) -> list[Group]:
    tree = LexborHTMLParser(html)
    groups: dict[int, Group] = {}
    for block in tree.css(".vt252"):
        faculty = _text(block.css_first(".vt253"))
        for a in block.css("a.vt256[data-i]"):
            gid = int(a.attributes["data-i"])
            groups[gid] = Group(id=gid, name=a.attributes.get("data-nm", "").strip(), faculty=faculty)
    if not groups:
        raise ParseError("список групп пуст — изменилась разметка?")
    return list(groups.values())


def _split_room(raw: str) -> tuple[str, str]:
    raw = re.sub(r"^ауд\.?:?\s*", "", raw.strip(), flags=re.I)
    room, _, building = raw.partition(";")
    return room.strip(), building.strip()


def parse_week(html: str, group_id: int, any_day: date) -> Week:
    """Разбирает страницу недели. any_day — дата, с которой запрашивали страницу."""
    tree = LexborHTMLParser(html)
    header = tree.css_first(".vt234")
    if header is None:
        raise ParseError("нет заголовка недели (.vt234)")

    monday = any_day - timedelta(days=any_day.weekday())
    m = _WEEK_RE.search(header.text())
    number = int(m.group(2)) if m else None
    parity = None
    if m:
        parity = "Нечётная" if m.group(1).lower().startswith("неч") else "Чётная"

    week = Week(group_id=group_id, monday=monday, number=number, parity=parity)

    for row in tree.css(".vt244b > .vt244"):
        slot = row.css_first(".vt239")
        pair = _text(slot.css_first(".vt283"))
        times = _TIME_RE.findall(slot.text())
        start, end = (times + ["", ""])[:2]
        for cell in row.css(".rasp-day"):
            dm = re.search(r"rasp-day(\d)", cell.attributes.get("class", ""))
            if not dm:
                continue
            day = monday + timedelta(days=int(dm.group(1)) - 1)
            for node in cell.css(".vt258"):
                teacher = node.css_first(".teacher")
                full = teacher.attributes.get("title", "") if teacher is not None else ""
                room, building = _split_room(_text(node.css_first(".vt242")))
                week.lessons.append(
                    Lesson(
                        day=day,
                        pair=pair,
                        start=start,
                        end=end,
                        subject=_text(node.css_first(".vt240")),
                        kind=_text(node.css_first(".vt243")),
                        room=room,
                        building=building,
                        teachers=tuple(t.strip() for t in full.split(";") if t.strip()),
                        teachers_short=_text(teacher),
                    )
                )
    return week
