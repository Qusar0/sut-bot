"""Выгрузка расписания в формате iCalendar (п. 32)."""

import hashlib
from datetime import datetime, timedelta

from icalendar import Alarm, Calendar, Event

from bot.config import TZ
from bot.render.text import kind_short, room_short
from bot.services.sut_public.models import Lesson, Week


def _uid(group_name: str, l: Lesson) -> str:
    raw = f"{group_name}|{l.day.isoformat()}|{l.start}|{l.subject}|{l.room}|{l.building}"
    return hashlib.sha1(raw.encode()).hexdigest() + "@sut-bot"


def _at(l: Lesson, hhmm: str) -> datetime:
    h, m = map(int, hhmm.split(":"))
    return datetime(l.day.year, l.day.month, l.day.day, h, m, tzinfo=TZ)


KIND_BITS = {"Лекция": 1, "Практика": 2, "Лабораторная": 4}


def _included(l: Lesson, kinds_mask: int, hidden: set[str]) -> bool:
    bit = KIND_BITS.get(kind_short(l.kind), 0)
    if bit and not kinds_mask & bit:
        return False
    return l.subject.split(" (")[0] not in hidden


def build_ics(
    group_name: str,
    weeks: list[Week],
    kinds_mask: int = 7,
    hidden_subjects: list[str] | tuple[str, ...] = (),
    alarm_minutes: int = 0,
) -> bytes:
    """Лента занятий. kinds_mask/hidden_subjects/alarm_minutes — настройки конструктора календаря."""
    hidden = set(hidden_subjects)
    cal = Calendar()
    cal.add("prodid", "-//sut-bot//Расписание СПбГУТ//RU")
    cal.add("version", "2.0")
    cal.add("calscale", "GREGORIAN")
    cal.add("x-wr-calname", f"Расписание {group_name}")
    cal.add("x-wr-timezone", "Europe/Moscow")
    cal.add("refresh-interval;value=duration", "PT6H")
    cal.add("x-published-ttl", "PT6H")

    stamp = datetime.now(TZ)
    for w in weeks:
        for l in w.lessons:
            if not l.start or not l.end or not _included(l, kinds_mask, hidden):
                continue
            ev = Event()
            ev.add("uid", _uid(group_name, l))
            ev.add("dtstamp", stamp)
            ev.add("dtstart", _at(l, l.start))
            ev.add("dtend", _at(l, l.end))
            ev.add("summary", f"{l.subject} ({kind_short(l.kind).lower()})")
            if l.room:
                ev.add("location", f"ауд. {room_short(l)}")
            desc = [kind_short(l.kind)]
            if l.teachers:
                desc.append("Преподаватель: " + ", ".join(l.teachers))
            desc.append(f"Группа: {group_name}")
            ev.add("description", "\n".join(desc))
            if alarm_minutes:
                alarm = Alarm()
                alarm.add("action", "DISPLAY")
                alarm.add("description", l.subject)
                alarm.add("trigger", timedelta(minutes=-alarm_minutes))
                ev.add_component(alarm)
            cal.add_component(ev)
    return cal.to_ical()
