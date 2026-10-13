"""Оформление расписаний преподавателей и аудиторий (п. 11, 16) и предметов (п. 20–22, 24)."""

import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from html import escape

from bot.config import TZ
from bot.render.text import MAX_LEN, WEEKDAYS, WEEKDAYS_SHORT, day_title, kind_mark, kind_short, room_short, short_date
from bot.services.directory import Slot
from bot.services.sut_public.models import Lesson, Week

# --- преподаватель / аудитория ---


def _slot_body(slot: Slot, tail: str) -> str:
    lines = [
        f"{kind_mark(slot.kind)} <b>{escape(slot.subject)}</b>",
        escape(kind_short(slot.kind)) + (f" · ауд. {escape(slot.room)}" if slot.room else ""),
    ]
    if tail:
        lines.append(f"<i>{escape(tail)}</i>")
    return "\n".join(lines)


def teacher_tail(slot: Slot) -> str:
    return ", ".join(slot.groups)


def room_tail(slot: Slot) -> str:
    return " · ".join(p for p in (", ".join(slot.groups), "; ".join(slot.teachers)) if p)


def render_slots_day(title: str, slots: list[Slot], day: date, tail: Callable[[Slot], str]) -> str:
    head = f"<b>{escape(title)}</b>\n📅 {day_title(day)}"
    items = [s for s in slots if s.day == day]
    if not items:
        return head + "\n\nЗанятий нет"
    blocks: dict[tuple[str, str, str], list[Slot]] = {}
    for s in items:
        blocks.setdefault((s.pair, s.start, s.end), []).append(s)
    out = []
    for (pair, start, end), group in blocks.items():
        name = f"{pair} пара" if pair.isdigit() else pair
        out.append(f"<b>{escape(name)}</b> · {start}–{end}\n" + "\n\n".join(_slot_body(s, tail(s)) for s in group))
    return head + "\n\n" + "\n\n\n".join(out)


def render_slots_week(title: str, slots: list[Slot], monday: date, tail: Callable[[Slot], str]) -> str:
    end = monday + timedelta(days=5)
    out = [f"<b>{escape(title)}</b>\n🗓 {short_date(monday)} — {short_date(end)}"]
    for i in range(6):
        d = monday + timedelta(days=i)
        items = [s for s in slots if s.day == d]
        block = f"<b>{WEEKDAYS[i]}, {d.day}</b>\n"
        if not items:
            block += "<i>занятий нет</i>"
        else:
            lines = []
            for s in items:
                details = " · ".join(escape(p) for p in (s.room, tail(s)) if p)
                lines.append(f"{kind_mark(s.kind)} <code>{s.start}</code> {escape(s.subject)}\n      └ {details}")
            block += "\n".join(lines)
        out.append(block)
    text = "\n\n".join(out)
    return text if len(text) <= MAX_LEN else text[: MAX_LEN - 20] + "\n…"


# --- предметы ---

_SUBGROUP = re.compile(r"\s*\(\d+\)$")


def base_subject(name: str) -> str:
    """«Иностранный язык (2)» → «Иностранный язык»: подгруппы считаем одним предметом."""
    return _SUBGROUP.sub("", name).strip()


KINDS = ("Лекция", "Практика", "Лабораторная")


@dataclass
class SubjectStats:
    name: str
    lessons: list[Lesson]  # без дублей подгрупп, по времени
    passed: int
    by_kind: dict[str, tuple[int, int]]  # вид -> (прошло, всего)
    teachers: list[str]


def _is_passed(l: Lesson, now: datetime) -> bool:
    if l.day != now.date():
        return l.day < now.date()
    return l.end <= now.strftime("%H:%M")


def subject_list(weeks: list[Week]) -> list[str]:
    return sorted({base_subject(l.subject) for w in weeks for l in w.lessons})


def subject_stats(weeks: list[Week], name: str, now: datetime | None = None) -> SubjectStats:
    now = now or datetime.now(TZ)
    seen, lessons, teachers = set(), [], []
    for w in weeks:
        for l in sorted(w.lessons, key=lambda x: (x.day, x.start)):
            if base_subject(l.subject) != name:
                continue
            for t in l.teachers_short.split("; "):
                if t and t not in teachers:
                    teachers.append(t)
            key = (l.day, l.start, kind_short(l.kind))
            if key in seen:  # подгруппы одного занятия
                continue
            seen.add(key)
            lessons.append(l)
    by_kind: dict[str, tuple[int, int]] = {}
    passed = 0
    for l in lessons:
        k = kind_short(l.kind)
        done = _is_passed(l, now)
        passed += done
        p, t = by_kind.get(k, (0, 0))
        by_kind[k] = (p + done, t + 1)
    return SubjectStats(name, lessons, passed, by_kind, teachers)


def render_subjects(group_name: str, weeks: list[Week]) -> str:
    n = len(subject_list(weeks))
    return f"<b>📚 Предметы группы {escape(group_name)}</b>\n<i>текущий семестр · {n}</i>\n\nВыберите предмет:"


def render_subject(
    group_name: str, weeks: list[Week], stats: SubjectStats, kinds: set[str], now: datetime | None = None
) -> str:
    now = now or datetime.now(TZ)
    head = f"<b>📘 {escape(stats.name)}</b>\n{escape(group_name)} · текущий семестр"
    if stats.teachers:
        head += "\n👩‍🏫 " + escape(", ".join(stats.teachers))

    number_of = {w.monday: w.number for w in weeks}
    blocks, cur_monday, lines = [], None, []
    for l in stats.lessons:
        if kind_short(l.kind) not in kinds:
            continue
        monday = l.day - timedelta(days=l.day.weekday())
        if monday != cur_monday:
            if lines:
                blocks.append("\n".join(lines))
            cur_monday = monday
            num = number_of.get(monday)
            lines = [f"<b>Неделя {num}</b>" if num else f"<b>Неделя с {short_date(monday)}</b>"]
        mark = "✅" if _is_passed(l, now) else "▫️"
        room = f" · {escape(room_short(l))}" if l.room else ""
        lines.append(
            f"{mark} {WEEKDAYS_SHORT[l.day.weekday()]} {l.day:%d.%m} · <code>{l.start}</code> {kind_mark(l.kind)}{room}"
        )
    if lines:
        blocks.append("\n".join(lines))

    total = len(stats.lessons)
    summary = [f"<b>Всего занятий: {total}</b> · ✅ прошло {stats.passed} · ▫️ впереди {total - stats.passed}"]
    for k in KINDS:
        if k in stats.by_kind:
            p, t = stats.by_kind[k]
            summary.append(f"{kind_mark(k)} {k}: {p}/{t} · осталось {t - p}")

    body = "\n\n".join(blocks) if blocks else "<i>Нет занятий выбранного типа</i>"
    text = head + "\n\n" + body + "\n\n" + "\n".join(summary)
    if len(text) > MAX_LEN:  # очень длинный предмет: показываем ближайшие занятия
        keep = MAX_LEN - len(head) - len("\n".join(summary)) - 60
        text = head + "\n\n…" + body[-keep:] + "\n\n" + "\n".join(summary)
    return text
